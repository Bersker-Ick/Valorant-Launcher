"""本机测试用的原生 Win32 登录窗口（不是游戏登录器）。

用途：
* 在没有游戏登录器/DMA 风险的情况下验证 UIA 找控件、校准、输入与结果判定；
* 原生 EDIT 控件，UIA 能看到 IsPassword 与 BoundingRectangle；
* 输入 ``test`` / ``Abc123!@#`` 显示“登录成功”并关闭；其它组合显示“密码错误”。

只用于开发与人工验收，不参与打包。运行::

    py -3.13 tools\\mock_login.py
"""

from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wintypes
import sys

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

WS_OVERLAPPEDWINDOW = 0x00CF0000
WS_CHILD = 0x40000000
WS_VISIBLE = 0x10000000
WS_BORDER = 0x00800000
ES_AUTOHSCROLL = 0x0080
ES_PASSWORD = 0x0020
BS_PUSHBUTTON = 0x00000000
WM_CREATE = 0x0001
WM_COMMAND = 0x0111
WM_CLOSE = 0x0010
WM_DESTROY = 0x0002
WM_SETFONT = 0x0030
WM_TIMER = 0x0113
BN_CLICKED = 0
DEFAULT_GUI_FONT = 17

WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)


class WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ("style", wintypes.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
    ]


user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.DefWindowProcW.restype = ctypes.c_ssize_t
user32.CreateWindowExW.argtypes = [
    wintypes.DWORD,
    wintypes.LPCWSTR,
    wintypes.LPCWSTR,
    wintypes.DWORD,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    wintypes.HWND,
    wintypes.HMENU,
    wintypes.HINSTANCE,
    ctypes.c_void_p,
]
user32.CreateWindowExW.restype = wintypes.HWND
user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
user32.RegisterClassW.restype = wintypes.ATOM
user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
user32.GetMessageW.restype = wintypes.BOOL
user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.DispatchMessageW.restype = ctypes.c_ssize_t
user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.SendMessageW.restype = ctypes.c_ssize_t
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowTextW.restype = ctypes.c_int
user32.SetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPCWSTR]
user32.SetWindowTextW.restype = wintypes.BOOL
user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
user32.GetWindowTextLengthW.restype = ctypes.c_int
user32.EnableWindow.argtypes = [wintypes.HWND, wintypes.BOOL]
user32.EnableWindow.restype = wintypes.BOOL
user32.SetTimer.argtypes = [wintypes.HWND, ctypes.c_size_t, wintypes.UINT, ctypes.c_void_p]
user32.SetTimer.restype = ctypes.c_size_t
user32.KillTimer.argtypes = [wintypes.HWND, ctypes.c_size_t]
user32.KillTimer.restype = wintypes.BOOL
user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.PostMessageW.restype = wintypes.BOOL
user32.LoadCursorW.argtypes = [wintypes.HINSTANCE, ctypes.c_void_p]
user32.LoadCursorW.restype = wintypes.HANDLE
kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
kernel32.GetModuleHandleW.restype = wintypes.HINSTANCE
gdi32.GetStockObject.argtypes = [ctypes.c_int]
gdi32.GetStockObject.restype = wintypes.HGDIOBJ

CLASS_NAME = "MockLoginWindow"
WINDOW_TITLE = "Mock Login - 登录助手测试"
ID_ACCOUNT = 101
ID_PASSWORD = 102
ID_LOGIN = 103
ID_STATUS = 104
TIMER_ID = 1

_account = 0
_password = 0
_status = 0
_button = 0
_pending_result = 0
_stay_open = False


def _get_text(hwnd: int) -> str:
    length = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    return buf.value


def _wndproc(hwnd, msg, wparam, lparam):  # type: ignore[no-untyped-def]
    global _account, _password, _status, _button, _pending_result
    if msg == WM_CREATE:
        hinst = kernel32.GetModuleHandleW(None)
        font = gdi32.GetStockObject(DEFAULT_GUI_FONT)
        for text, cid, x, y, w, h, extra_style in (
            ("账号", ID_ACCOUNT + 1000, 26, 22, 70, 24, 0),
            ("密码", ID_PASSWORD + 1000, 26, 72, 70, 24, 0),
        ):
            label = user32.CreateWindowExW(0, "Static", text, WS_CHILD | WS_VISIBLE, x, y, w, h, hwnd, wintypes.HMENU(cid), hinst, None)
            user32.SendMessageW(label, WM_SETFONT, wintypes.WPARAM(font), wintypes.LPARAM(True))
        _account = user32.CreateWindowExW(0, "Edit", "", WS_CHILD | WS_VISIBLE | WS_BORDER | ES_AUTOHSCROLL, 100, 20, 300, 26, hwnd, wintypes.HMENU(ID_ACCOUNT), hinst, None)
        _password = user32.CreateWindowExW(0, "Edit", "", WS_CHILD | WS_VISIBLE | WS_BORDER | ES_AUTOHSCROLL | ES_PASSWORD, 100, 70, 300, 26, hwnd, wintypes.HMENU(ID_PASSWORD), hinst, None)
        _button = user32.CreateWindowExW(0, "Button", "登录", WS_CHILD | WS_VISIBLE | BS_PUSHBUTTON, 100, 120, 120, 34, hwnd, wintypes.HMENU(ID_LOGIN), hinst, None)
        _status = user32.CreateWindowExW(0, "Static", "测试提示：输入 test / Abc123!@# 可成功", WS_CHILD | WS_VISIBLE, 100, 170, 330, 50, hwnd, wintypes.HMENU(ID_STATUS), hinst, None)
        for control in (_account, _password, _button, _status):
            user32.SendMessageW(control, WM_SETFONT, wintypes.WPARAM(font), wintypes.LPARAM(True))
        return 0
    if msg == WM_COMMAND:
        cid = int(wparam) & 0xFFFF
        code = (int(wparam) >> 16) & 0xFFFF
        if cid == ID_LOGIN and code == BN_CLICKED:
            account = _get_text(_account)
            password = _get_text(_password)
            if account == "test" and password == "Abc123!@#":
                _pending_result = 1
                user32.SetWindowTextW(_status, "登录成功，正在进入…")
                user32.EnableWindow(_button, False)
                user32.SetTimer(hwnd, TIMER_ID, 900, None)
            else:
                user32.SetWindowTextW(_status, "密码错误，请重试")
            return 0
        return 0
    if msg == WM_TIMER and int(wparam) == TIMER_ID:
        user32.KillTimer(hwnd, TIMER_ID)
        if _pending_result == 1 and not _stay_open:
            user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
        return 0
    if msg == WM_CLOSE:
        user32.DestroyWindow(hwnd)
        return 0
    if msg == WM_DESTROY:
        user32.PostQuitMessage(0)
        return 0
    return user32.DefWindowProcW(hwnd, msg, wparam, lparam)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--minimized", action="store_true", help="以最小化/不激活方式启动（用于 UIA 检查）")
    parser.add_argument("--no-activate", action="store_true", help="显示但不抢前台（SW_SHOWNOACTIVATE）")
    parser.add_argument("--stay-open", action="store_true", help="登录成功后不关闭窗口（便于自动化测试）")
    args = parser.parse_args()
    global _stay_open
    _stay_open = args.stay_open
    hinst = kernel32.GetModuleHandleW(None)
    wc = WNDCLASSW()
    wc.style = 0
    wc.lpfnWndProc = WNDPROC(_wndproc)
    wc.cbClsExtra = 0
    wc.cbWndExtra = 0
    wc.hInstance = hinst
    wc.hIcon = 0
    wc.hCursor = user32.LoadCursorW(None, ctypes.c_void_p(32512))
    wc.hbrBackground = gdi32.GetStockObject(0)  # WHITE_BRUSH
    wc.lpszMenuName = None
    wc.lpszClassName = CLASS_NAME
    user32.RegisterClassW(ctypes.byref(wc))
    hwnd = user32.CreateWindowExW(
        0,
        CLASS_NAME,
        WINDOW_TITLE,
        WS_OVERLAPPEDWINDOW,
        420,
        260,
        500,
        280,
        None,
        None,
        hinst,
        None,
    )
    if not hwnd:
        raise ctypes.WinError(ctypes.get_last_error())
    user32.ShowWindow(hwnd, 7 if args.minimized else 4 if args.no_activate else 1)
    user32.UpdateWindow(hwnd)
    if sys.stdout is not None:
        print(f"MockLoginWindow hwnd=0x{int(hwnd):X} pid={ctypes.windll.kernel32.GetCurrentProcessId()}", flush=True)
    msg = wintypes.MSG()
    while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
        user32.TranslateMessage(ctypes.byref(msg))
        user32.DispatchMessageW(ctypes.byref(msg))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
