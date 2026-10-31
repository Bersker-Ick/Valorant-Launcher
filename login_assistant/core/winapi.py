"""Win32 / 系统 API 封装（仅使用公开 API，不读写其它进程内存）。

本模块覆盖：
* 顶层窗口枚举、标题/类名/进程/EXE/完整性级别
* 前台焦点获取与严格校验（AttachThreadInput + SetForegroundWindow）
* 客户区坐标换算、DPI 感知
* IME 摘除/恢复、BlockInput
* 目标线程键盘布局查询

不包含任何注入、hook、调试或内存读写。
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wintypes
import os
import time
from dataclasses import dataclass, field
from typing import Callable, Iterable

from .models import (
    IntegrityInfo,
    WindowInfo,
    integrity_label,
)

USER32 = ctypes.WinDLL("user32", use_last_error=True)
KERNEL32 = ctypes.WinDLL("kernel32", use_last_error=True)
ADVAPI32 = ctypes.WinDLL("advapi32", use_last_error=True)
DWMAPI = ctypes.WinDLL("dwmapi", use_last_error=True)
NTDLL = ctypes.WinDLL("ntdll", use_last_error=True)
SHCORE = ctypes.WinDLL("shcore", use_last_error=True)

GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000
WS_EX_APPWINDOW = 0x00040000

GA_ROOT = 2
SW_RESTORE = 9
SMTO_BLOCK = 0x0001
SMTO_ABORTIFHUNG = 0x0002
WM_GETTEXT = 0x000D

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
TOKEN_QUERY = 0x0008
TokenIntegrityLevel = 25

DWMWA_CLOAKED = 14

SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79

DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = ctypes.c_void_p(-4)


# ---------------------------------------------------------------------------
# 基本类型与函数签名
# ---------------------------------------------------------------------------
class RECT(ctypes.Structure):
    _fields_ = [
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    ]

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top


class POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class GUITHREADINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("hwndActive", wintypes.HWND),
        ("hwndFocus", wintypes.HWND),
        ("hwndCapture", wintypes.HWND),
        ("hwndMenuOwner", wintypes.HWND),
        ("hwndMoveSize", wintypes.HWND),
        ("hwndCaret", wintypes.HWND),
        ("rcCaret", RECT),
    ]


class SID_AND_ATTRIBUTES(ctypes.Structure):
    _fields_ = [
        ("Sid", ctypes.c_void_p),
        ("Attributes", wintypes.DWORD),
    ]


class TOKEN_MANDATORY_LABEL(ctypes.Structure):
    _fields_ = [("Label", SID_AND_ATTRIBUTES)]


class OSVERSIONINFOEXW(ctypes.Structure):
    _fields_ = [
        ("dwOSVersionInfoSize", wintypes.DWORD),
        ("dwMajorVersion", wintypes.DWORD),
        ("dwMinorVersion", wintypes.DWORD),
        ("dwBuildNumber", wintypes.DWORD),
        ("dwPlatformId", wintypes.DWORD),
        ("szCSDVersion", wintypes.WCHAR * 128),
        ("wServicePackMajor", wintypes.WORD),
        ("wServicePackMinor", wintypes.WORD),
        ("wSuiteMask", wintypes.WORD),
        ("wProductType", wintypes.BYTE),
        ("wReserved", wintypes.BYTE),
    ]


USER32.EnumWindows.argtypes = [ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM), wintypes.LPARAM]
USER32.EnumWindows.restype = wintypes.BOOL
USER32.EnumChildWindows.argtypes = [wintypes.HWND, ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM), wintypes.LPARAM]
USER32.EnumChildWindows.restype = wintypes.BOOL
USER32.IsWindow.argtypes = [wintypes.HWND]
USER32.IsWindow.restype = wintypes.BOOL
USER32.IsWindowVisible.argtypes = [wintypes.HWND]
USER32.IsWindowVisible.restype = wintypes.BOOL
USER32.IsWindowEnabled.argtypes = [wintypes.HWND]
USER32.IsWindowEnabled.restype = wintypes.BOOL
USER32.IsIconic.argtypes = [wintypes.HWND]
USER32.IsIconic.restype = wintypes.BOOL
USER32.IsHungAppWindow.argtypes = [wintypes.HWND]
USER32.IsHungAppWindow.restype = wintypes.BOOL
USER32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
USER32.GetWindowTextLengthW.restype = ctypes.c_int
USER32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
USER32.GetWindowTextW.restype = ctypes.c_int
USER32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
USER32.GetClassNameW.restype = ctypes.c_int
USER32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
USER32.GetWindowThreadProcessId.restype = wintypes.DWORD
USER32.GetForegroundWindow.argtypes = []
USER32.GetForegroundWindow.restype = wintypes.HWND
KERNEL32.GetCurrentThreadId.argtypes = []
KERNEL32.GetCurrentThreadId.restype = wintypes.DWORD
USER32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
USER32.AttachThreadInput.restype = wintypes.BOOL
USER32.SetForegroundWindow.argtypes = [wintypes.HWND]
USER32.SetForegroundWindow.restype = wintypes.BOOL
USER32.BringWindowToTop.argtypes = [wintypes.HWND]
USER32.BringWindowToTop.restype = wintypes.BOOL
USER32.SetActiveWindow.argtypes = [wintypes.HWND]
USER32.SetActiveWindow.restype = wintypes.HWND
USER32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
USER32.ShowWindow.restype = wintypes.BOOL
USER32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(RECT)]
USER32.GetWindowRect.restype = wintypes.BOOL
USER32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(RECT)]
USER32.GetClientRect.restype = wintypes.BOOL
USER32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(POINT)]
USER32.ClientToScreen.restype = wintypes.BOOL
USER32.ScreenToClient.argtypes = [wintypes.HWND, ctypes.POINTER(POINT)]
USER32.ScreenToClient.restype = wintypes.BOOL
USER32.GetCursorPos.argtypes = [ctypes.POINTER(POINT)]
USER32.GetCursorPos.restype = wintypes.BOOL
USER32.GetGUIThreadInfo.argtypes = [wintypes.DWORD, ctypes.POINTER(GUITHREADINFO)]
USER32.GetGUIThreadInfo.restype = wintypes.BOOL
USER32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
USER32.GetAncestor.restype = wintypes.HWND
USER32.IsChild.argtypes = [wintypes.HWND, wintypes.HWND]
USER32.IsChild.restype = wintypes.BOOL
USER32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
USER32.GetWindowLongW.restype = wintypes.LONG
USER32.GetKeyboardLayout.argtypes = [wintypes.DWORD]
USER32.GetKeyboardLayout.restype = wintypes.HKL
USER32.SetProcessDPIAware.argtypes = []
USER32.SetProcessDPIAware.restype = wintypes.BOOL
USER32.GetDpiForWindow.argtypes = [wintypes.HWND]
USER32.GetDpiForWindow.restype = wintypes.UINT
USER32.GetSystemMetrics.argtypes = [ctypes.c_int]
USER32.GetSystemMetrics.restype = ctypes.c_int
USER32.BlockInput.argtypes = [wintypes.BOOL]
USER32.BlockInput.restype = wintypes.BOOL
USER32.SendMessageTimeoutW.argtypes = [
    wintypes.HWND,
    wintypes.UINT,
    wintypes.WPARAM,
    wintypes.LPARAM,
    wintypes.UINT,
    wintypes.UINT,
    ctypes.POINTER(ctypes.c_size_t),
]
USER32.SendMessageTimeoutW.restype = wintypes.LPARAM
USER32.FindWindowExW.argtypes = [wintypes.HWND, wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR]
USER32.FindWindowExW.restype = wintypes.HWND
USER32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
USER32.PostMessageW.restype = wintypes.BOOL
USER32.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
USER32.SetProcessDpiAwarenessContext.restype = wintypes.BOOL
USER32.GetThreadDpiAwarenessContext.argtypes = []
USER32.GetThreadDpiAwarenessContext.restype = ctypes.c_void_p
USER32.AreDpiAwarenessContextsEqual.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
USER32.AreDpiAwarenessContextsEqual.restype = wintypes.BOOL
USER32.GetAwarenessFromDpiAwarenessContext.argtypes = [ctypes.c_void_p]
USER32.GetAwarenessFromDpiAwarenessContext.restype = ctypes.c_int

DWMAPI.DwmGetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
DWMAPI.DwmGetWindowAttribute.restype = ctypes.c_long

KERNEL32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
KERNEL32.OpenProcess.restype = wintypes.HANDLE
KERNEL32.CloseHandle.argtypes = [wintypes.HANDLE]
KERNEL32.CloseHandle.restype = wintypes.BOOL
KERNEL32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
KERNEL32.QueryFullProcessImageNameW.restype = wintypes.BOOL
KERNEL32.GetCurrentProcess.argtypes = []
KERNEL32.GetCurrentProcess.restype = wintypes.HANDLE
KERNEL32.GetCurrentProcessId.argtypes = []
KERNEL32.GetCurrentProcessId.restype = wintypes.DWORD

ADVAPI32.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
ADVAPI32.OpenProcessToken.restype = wintypes.BOOL
ADVAPI32.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
ADVAPI32.GetTokenInformation.restype = wintypes.BOOL
ADVAPI32.GetSidSubAuthorityCount.argtypes = [ctypes.c_void_p]
ADVAPI32.GetSidSubAuthorityCount.restype = ctypes.POINTER(ctypes.c_ubyte)
ADVAPI32.GetSidSubAuthority.argtypes = [ctypes.c_void_p, wintypes.DWORD]
ADVAPI32.GetSidSubAuthority.restype = ctypes.POINTER(wintypes.DWORD)

NTDLL.RtlGetVersion.argtypes = [ctypes.POINTER(OSVERSIONINFOEXW)]
NTDLL.RtlGetVersion.restype = ctypes.c_long


# ---------------------------------------------------------------------------
# DPI / 版本
# ---------------------------------------------------------------------------
def current_dpi_awareness() -> str:
    try:
        context = USER32.GetThreadDpiAwarenessContext()
        for value, label in (
            (-4, "Per-Monitor V2"),
            (-3, "Per-Monitor V1"),
            (-2, "System"),
            (-1, "Unaware"),
        ):
            if USER32.AreDpiAwarenessContextsEqual(context, DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 if value == -4 else ctypes.c_void_p(value)):
                return label
        awareness = int(USER32.GetAwarenessFromDpiAwarenessContext(context))
        return {0: "Unaware", 1: "System", 2: "Per-Monitor"}.get(awareness, f"未知({awareness})")
    except Exception:
        return "未知"


def set_dpi_awareness() -> str:
    """在创建任何窗口前调用，开启 Per-Monitor v2；返回实际感知模式。"""
    existing = current_dpi_awareness()
    if existing in {"Per-Monitor V2", "Per-Monitor V1", "Per-Monitor"}:
        return existing
    try:
        if USER32.SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2):
            return current_dpi_awareness()
    except Exception:
        pass
    try:
        # PROCESS_PER_MONITOR_DPI_AWARE = 2
        if SHCORE.SetProcessDpiAwareness(2) == 0:
            return current_dpi_awareness()
    except Exception:
        pass
    try:
        if USER32.SetProcessDPIAware():
            return current_dpi_awareness()
    except Exception:
        pass
    return current_dpi_awareness()


def get_os_version() -> tuple[int, int, int, str]:
    info = OSVERSIONINFOEXW()
    info.dwOSVersionInfoSize = ctypes.sizeof(OSVERSIONINFOEXW)
    try:
        NTDLL.RtlGetVersion(ctypes.byref(info))
        return int(info.dwMajorVersion), int(info.dwMinorVersion), int(info.dwBuildNumber), str(info.szCSDVersion)
    except Exception:
        return 0, 0, 0, ""


def os_version_string() -> str:
    major, minor, build, csd = get_os_version()
    if not major:
        return "Windows (unknown)"
    name = "Windows 11" if build >= 22000 else "Windows 10" if major == 10 else f"Windows {major}.{minor}"
    return f"{name} {major}.{minor}.{build} {csd}".strip()


def dpi_for_window(hwnd: int) -> int:
    try:
        return int(USER32.GetDpiForWindow(hwnd)) or 96
    except Exception:
        return 96


def virtual_screen_rect() -> tuple[int, int, int, int]:
    """返回虚拟桌面物理像素矩形 (left, top, width, height)。"""
    try:
        return (
            int(USER32.GetSystemMetrics(SM_XVIRTUALSCREEN)),
            int(USER32.GetSystemMetrics(SM_YVIRTUALSCREEN)),
            int(USER32.GetSystemMetrics(SM_CXVIRTUALSCREEN)),
            int(USER32.GetSystemMetrics(SM_CYVIRTUALSCREEN)),
        )
    except Exception:
        return (0, 0, 0, 0)


# ---------------------------------------------------------------------------
# 进程 / 完整性级别
# ---------------------------------------------------------------------------
def get_process_exe(pid: int) -> str:
    if pid <= 0:
        return ""
    handle = KERNEL32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(32768)
        size = wintypes.DWORD(len(buf))
        if KERNEL32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return buf.value
        return ""
    finally:
        KERNEL32.CloseHandle(handle)


def get_integrity_level(pid: int) -> IntegrityInfo:
    if pid <= 0:
        return IntegrityInfo(None, "未知", None)
    process = KERNEL32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not process:
        err = ctypes.get_last_error()
        return IntegrityInfo(None, "未知（无法打开进程）", err)
    token = wintypes.HANDLE()
    try:
        if not ADVAPI32.OpenProcessToken(process, TOKEN_QUERY, ctypes.byref(token)):
            return IntegrityInfo(None, "未知（无法打开令牌）", ctypes.get_last_error())
        needed = wintypes.DWORD(0)
        ADVAPI32.GetTokenInformation(token, TokenIntegrityLevel, None, 0, ctypes.byref(needed))
        if not needed.value:
            return IntegrityInfo(None, "未知（令牌无完整性信息）", ctypes.get_last_error())
        buffer = ctypes.create_string_buffer(needed.value)
        if not ADVAPI32.GetTokenInformation(
            token, TokenIntegrityLevel, buffer, needed.value, ctypes.byref(needed)
        ):
            return IntegrityInfo(None, "未知（读取令牌失败）", ctypes.get_last_error())
        label = ctypes.cast(buffer, ctypes.POINTER(TOKEN_MANDATORY_LABEL)).contents
        sid = label.Label.Sid
        if not sid:
            return IntegrityInfo(None, "未知（SID 为空）", None)
        count_ptr = ADVAPI32.GetSidSubAuthorityCount(sid)
        if not count_ptr:
            return IntegrityInfo(None, "未知（SID 计数为空）", None)
        count = int(count_ptr[0])
        if count <= 0:
            return IntegrityInfo(None, "未知（SID 计数为 0）", None)
        rid_ptr = ADVAPI32.GetSidSubAuthority(sid, count - 1)
        if not rid_ptr:
            return IntegrityInfo(None, "未知（SID RID 为空）", None)
        rid = int(rid_ptr[0])
        return IntegrityInfo(rid, integrity_label(rid))
    finally:
        if token:
            KERNEL32.CloseHandle(token)
        KERNEL32.CloseHandle(process)


def self_integrity() -> IntegrityInfo:
    return get_integrity_level(int(KERNEL32.GetCurrentProcessId()))


def is_elevated() -> bool:
    info = self_integrity()
    return bool(info.rid is not None and info.rid >= 0x3000)


# ---------------------------------------------------------------------------
# 窗口枚举与查询
# ---------------------------------------------------------------------------
def _is_cloaked(hwnd: int) -> bool:
    value = wintypes.DWORD(0)
    try:
        hr = DWMAPI.DwmGetWindowAttribute(hwnd, DWMWA_CLOAKED, ctypes.byref(value), ctypes.sizeof(value))
        return hr == 0 and value.value != 0
    except Exception:
        return False


def get_window_title(hwnd: int) -> str:
    length = USER32.GetWindowTextLengthW(hwnd)
    if length <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(length + 1)
    USER32.GetWindowTextW(hwnd, buf, length + 1)
    return buf.value


def get_class_name(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(256)
    USER32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def get_window_pid(hwnd: int) -> int:
    pid = wintypes.DWORD(0)
    USER32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return int(pid.value)


def get_window_thread_id(hwnd: int) -> int:
    pid = wintypes.DWORD(0)
    return int(USER32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid)))


def get_window_info(hwnd: int, include_integrity: bool = False) -> WindowInfo | None:
    if not hwnd or not USER32.IsWindow(hwnd):
        return None
    pid = get_window_pid(hwnd)
    integrity = get_integrity_level(pid) if include_integrity else None
    return WindowInfo(
        hwnd=int(hwnd),
        title=get_window_title(hwnd),
        class_name=get_class_name(hwnd),
        pid=pid,
        exe=get_process_exe(pid),
        integrity=integrity,
    )


def enum_top_windows(
    *,
    visible_only: bool = True,
    exclude_pid: int | None = None,
    include_tool_windows: bool = False,
    include_cloaked: bool = False,
) -> list[WindowInfo]:
    """按 Z 序（顶层优先）返回顶层窗口。"""
    result: list[WindowInfo] = []
    exe_cache: dict[int, str] = {}

    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def _callback(hwnd, _lparam):  # type: ignore[no-untyped-def]
        if visible_only and not USER32.IsWindowVisible(hwnd):
            return True
        if not include_cloaked and _is_cloaked(hwnd):
            return True
        style = USER32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        if not include_tool_windows and (style & WS_EX_TOOLWINDOW):
            return True
        title = get_window_title(hwnd)
        if not title:
            return True
        pid = get_window_pid(hwnd)
        if exclude_pid is not None and pid == exclude_pid:
            return True
        if pid not in exe_cache:
            exe_cache[pid] = get_process_exe(pid)
        result.append(
            WindowInfo(
                hwnd=int(hwnd),
                title=title,
                class_name=get_class_name(hwnd),
                pid=pid,
                exe=exe_cache[pid],
            )
        )
        return True

    USER32.EnumWindows(callback_type(_callback), 0)
    return result


def get_foreground_window() -> int:
    return int(USER32.GetForegroundWindow() or 0)


def get_window_rect(hwnd: int) -> RECT | None:
    rect = RECT()
    if not USER32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return None
    return rect


def get_client_rect(hwnd: int) -> RECT | None:
    rect = RECT()
    if not USER32.GetClientRect(hwnd, ctypes.byref(rect)):
        return None
    return rect


def get_client_origin(hwnd: int) -> tuple[int, int]:
    point = POINT(0, 0)
    if not USER32.ClientToScreen(hwnd, ctypes.byref(point)):
        raise OSError(f"ClientToScreen 失败 (WinError {ctypes.get_last_error()})")
    return int(point.x), int(point.y)


def get_client_rect_screen(hwnd: int) -> tuple[int, int, int, int]:
    rect = get_client_rect(hwnd)
    if rect is None:
        raise OSError("GetClientRect 失败")
    x, y = get_client_origin(hwnd)
    return x, y, rect.width, rect.height


def screen_to_client(hwnd: int, x: int, y: int) -> tuple[int, int]:
    point = POINT(int(x), int(y))
    if not USER32.ScreenToClient(hwnd, ctypes.byref(point)):
        raise OSError("ScreenToClient 失败")
    return int(point.x), int(point.y)


def get_cursor_pos() -> tuple[int, int]:
    point = POINT()
    if not USER32.GetCursorPos(ctypes.byref(point)):
        return (0, 0)
    return int(point.x), int(point.y)


def get_foreground_info(include_integrity: bool = True) -> WindowInfo | None:
    return get_window_info(get_foreground_window(), include_integrity=include_integrity)


def get_keyboard_layout_for_window(hwnd: int) -> int:
    tid = get_window_thread_id(hwnd)
    if tid:
        try:
            hkl = USER32.GetKeyboardLayout(tid)
            if hkl:
                return int(hkl)
        except Exception:
            pass
    try:
        return int(USER32.GetKeyboardLayout(0) or 0)
    except Exception:
        return 0


# ---------------------------------------------------------------------------
# 焦点
# ---------------------------------------------------------------------------
@dataclass
class FocusReport:
    ok: bool
    message: str
    foreground: int = 0
    attached: bool = False
    set_foreground_result: bool = False
    errors: list[str] = field(default_factory=list)


def focus_window(hwnd: int, timeout_ms: int = 500) -> FocusReport:
    """严格抢焦点：AttachThreadInput -> SetForegroundWindow -> 校验。"""
    errors: list[str] = []
    if not hwnd or not USER32.IsWindow(hwnd):
        return FocusReport(False, "目标窗口已不存在", errors=["IsWindow=False"])
    if not USER32.IsWindowVisible(hwnd):
        return FocusReport(False, "目标窗口不可见", errors=["IsWindowVisible=False"])
    if USER32.IsIconic(hwnd):
        return FocusReport(False, "目标窗口已最小化，请先还原窗口", errors=["IsIconic=True"])
    if not USER32.IsWindowEnabled(hwnd):
        return FocusReport(False, "目标窗口处于禁用状态", errors=["IsWindowEnabled=False"])
    if USER32.IsHungAppWindow(hwnd):
        return FocusReport(False, "目标窗口无响应（hung），已中止", errors=["IsHungAppWindow=True"])

    foreground_now = get_foreground_window()
    if foreground_now == int(hwnd):
        return FocusReport(
            True,
            "目标窗口已经在前台",
            foreground=foreground_now,
            set_foreground_result=True,
            errors=[],
        )

    current_tid = int(KERNEL32.GetCurrentThreadId())
    target_tid = get_window_thread_id(hwnd)
    attached = False
    set_fg = False
    try:
        if target_tid and target_tid != current_tid:
            attached = bool(USER32.AttachThreadInput(current_tid, target_tid, True))
            if not attached:
                errors.append(f"AttachThreadInput 失败 (WinError {ctypes.get_last_error()})")
        USER32.BringWindowToTop(hwnd)
        set_fg = bool(USER32.SetForegroundWindow(hwnd))
        if not set_fg:
            errors.append(f"SetForegroundWindow 返回 0 (WinError {ctypes.get_last_error()})")
        USER32.SetActiveWindow(hwnd)
        deadline = time.monotonic() + max(0.05, timeout_ms / 1000.0)
        foreground = get_foreground_window()
        while time.monotonic() < deadline:
            if foreground == hwnd:
                break
            time.sleep(0.02)
            foreground = get_foreground_window()
        if foreground != hwnd:
            return FocusReport(
                False,
                "无法把目标窗口置于前台（可能被系统前台锁或权限限制拦截）",
                foreground=foreground,
                attached=attached,
                set_foreground_result=set_fg,
                errors=errors,
            )
        return FocusReport(
            True,
            "已获取目标窗口焦点",
            foreground=foreground,
            attached=attached,
            set_foreground_result=set_fg,
            errors=errors,
        )
    finally:
        if attached:
            USER32.AttachThreadInput(current_tid, target_tid, False)


def get_focus_hwnd_for_thread(thread_id: int) -> int:
    info = GUITHREADINFO()
    info.cbSize = ctypes.sizeof(GUITHREADINFO)
    if not USER32.GetGUIThreadInfo(thread_id, ctypes.byref(info)):
        return 0
    return int(info.hwndFocus or 0)


@dataclass(frozen=True)
class TargetFocusInfo:
    focus_hwnd: int
    in_target: bool
    focus_pid: int
    detail: str


def target_focus_info(hwnd: int) -> TargetFocusInfo:
    """检查目标线程当前的焦点控件是否属于目标窗口。"""
    tid = get_window_thread_id(hwnd)
    if not tid:
        return TargetFocusInfo(0, False, 0, "无法取得目标线程")
    focus = get_focus_hwnd_for_thread(tid)
    if not focus:
        return TargetFocusInfo(0, False, 0, "目标线程当前无焦点控件")
    focus_pid = get_window_pid(focus)
    root = int(USER32.GetAncestor(focus, GA_ROOT) or 0)
    in_target = (
        focus == int(hwnd)
        or root == int(hwnd)
        or bool(USER32.IsChild(hwnd, focus))
    )
    return TargetFocusInfo(
        focus,
        in_target,
        focus_pid,
        f"焦点 hwnd=0x{focus:X} root=0x{root:X} pid={focus_pid}",
    )


# ---------------------------------------------------------------------------
# IME / BlockInput / DPI / 消息读取
# ---------------------------------------------------------------------------
_IMM32 = None
try:
    _IMM32 = ctypes.WinDLL("imm32", use_last_error=True)
    _IMM32.ImmAssociateContext.argtypes = [wintypes.HWND, wintypes.HANDLE]
    _IMM32.ImmAssociateContext.restype = wintypes.HANDLE
except OSError:  # pragma: no cover
    _IMM32 = None


@dataclass
class ImeState:
    ok: bool
    hwnd: int
    previous: int = 0
    detail: str = ""


def detach_ime(hwnd: int) -> ImeState:
    if _IMM32 is None:
        return ImeState(False, hwnd, 0, "imm32 不可用")
    try:
        previous = _IMM32.ImmAssociateContext(hwnd, None)
        return ImeState(True, hwnd, int(previous or 0), "已摘除 IME 上下文")
    except Exception as exc:  # pragma: no cover
        return ImeState(False, hwnd, 0, f"ImmAssociateContext 异常: {type(exc).__name__}")


def restore_ime(state: ImeState) -> bool:
    if _IMM32 is None or not state.ok:
        return False
    try:
        _IMM32.ImmAssociateContext(state.hwnd, wintypes.HANDLE(state.previous))
        return True
    except Exception:  # pragma: no cover
        return False


def block_input(enable: bool) -> tuple[bool, int]:
    ctypes.set_last_error(0)
    ok = bool(USER32.BlockInput(bool(enable)))
    return ok, ctypes.get_last_error()


# ---------------------------------------------------------------------------
# 只读窗口文本（仅用于自检记事本，绝不用于目标密码框）
# ---------------------------------------------------------------------------
def read_window_text_message(hwnd: int, max_chars: int = 4096) -> str | None:
    """通过 WM_GETTEXT 读取控件文本。

    仅用于本工具自己启动的记事本自检；不对目标登录器的密码框调用。
    """
    if not hwnd or not USER32.IsWindow(hwnd):
        return None
    buf = ctypes.create_unicode_buffer(max_chars + 1)
    result = ctypes.c_size_t(0)
    lparam = ctypes.cast(buf, ctypes.c_void_p).value or 0
    ok = USER32.SendMessageTimeoutW(
        hwnd,
        WM_GETTEXT,
        wintypes.WPARAM(max_chars),
        wintypes.LPARAM(lparam),
        SMTO_ABORTIFHUNG | SMTO_BLOCK,
        1000,
        ctypes.byref(result),
    )
    if not ok:
        return None
    return buf.value


def find_child_edit(hwnd: int) -> int:
    """在窗口下找第一个标准 Edit/RichEdit 子控件（自检用）。"""
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    found = 0

    def _cb(child, _lparam):  # type: ignore[no-untyped-def]
        nonlocal found
        cls = get_class_name(child).lower()
        if cls in ("edit", "richedit", "richedit20w", "richedit50w", "richeditd2dpt"):
            found = int(child)
            return False
        return True

    USER32.EnumChildWindows(hwnd, callback_type(_cb), 0)
    return found


def is_window_valid(hwnd: int) -> bool:
    return bool(hwnd and USER32.IsWindow(hwnd))


def is_minimized(hwnd: int) -> bool:
    return bool(USER32.IsIconic(hwnd))


def is_enabled(hwnd: int) -> bool:
    return bool(USER32.IsWindowEnabled(hwnd))


def is_hung(hwnd: int) -> bool:
    return bool(USER32.IsHungAppWindow(hwnd))
