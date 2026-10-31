"""记事本自检：隔离“输入层”与“目标窗口”问题。

流程：
1. 记录启动前的顶层窗口集合；
2. 启动一个新的记事本（打开临时文件）；
3. 等待**新的**记事本顶层窗口出现；
4. 严格抢焦点、摘 IME、点击文本区、清空、输入测试串；
5. 通过 WM_GETTEXT 读取刚启动的记事本文本（仅自检用，绝不用于目标密码框）。

测试串不是密码；本模块不会读取目标登录器任何内容。
"""

from __future__ import annotations

import os
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import winapi
from .input import InputDiagnostics, InputSender, SendInputFailure
from .keymap import UnsupportedCharacterError, describe_unsupported
from ..security.secret import wipe

DEFAULT_TEST_TEXT = "Abc123!@#"


@dataclass
class SelfTestResult:
    ok: bool
    headline: str
    detail: str
    expected: str = DEFAULT_TEST_TEXT
    actual: str | None = None
    hwnd: int = 0
    window_title: str = ""
    events_total: int = 0
    events_failed: int = 0
    steps: list[str] = field(default_factory=list)


def _notepad_exe() -> str:
    windir = os.environ.get("WINDIR", r"C:\Windows")
    return str(Path(windir) / "System32" / "notepad.exe")


def _is_notepad_window(info: winapi.WindowInfo) -> bool:
    title = info.title.lower()
    cls = info.class_name.lower()
    exe = info.exe.lower()
    if cls == "notepad":
        return True
    if "notepad.exe" in exe:
        return True
    return ("记事本" in title or "notepad" in title) and "login" not in title


def _find_text_child(hwnd: int) -> int:
    for child in _enum_children(hwnd):
        cls = winapi.get_class_name(child).lower()
        if cls in {
            "richeditd2dpt",
            "richedit50w",
            "richedit20w",
            "richedit",
            "edit",
        }:
            return child
    return winapi.find_child_edit(hwnd)


def _enum_children(hwnd: int) -> list[int]:
    import ctypes
    import ctypes.wintypes as wintypes

    result: list[int] = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def _cb(child, _lparam):  # type: ignore[no-untyped-def]
        result.append(int(child))
        return True

    winapi.USER32.EnumChildWindows(hwnd, callback_type(_cb), 0)
    return result


def _read_notepad_text(hwnd: int) -> str | None:
    child = _find_text_child(hwnd)
    candidates = [child] if child else []
    candidates.append(hwnd)
    for candidate in candidates:
        if not candidate:
            continue
        text = winapi.read_window_text_message(candidate)
        if text is not None:
            return text
    return None


def run_notepad_selftest(
    *,
    test_text: str = DEFAULT_TEST_TEXT,
    block_input: bool = False,
    delay_min_ms: int = 40,
    delay_max_ms: int = 80,
    diagnostics: InputDiagnostics | None = None,
    timeout_s: float = 8.0,
) -> SelfTestResult:
    steps: list[str] = []
    result = SelfTestResult(
        ok=False,
        headline="自检未完成",
        detail="",
        expected=test_text,
        steps=steps,
    )

    try:
        payload = bytearray(test_text.encode("utf-8"))
    except UnicodeEncodeError:
        result.headline = "测试串编码失败"
        result.detail = "测试串无法编码为 UTF-8"
        return result

    if any(byte > 0x7E or byte < 0x20 for byte in payload):
        result.headline = "测试串包含不可模拟字符"
        result.detail = describe_unsupported(payload)
        wipe(payload)
        return result

    before = {info.hwnd for info in winapi.enum_top_windows(include_tool_windows=True)}
    temp_dir = Path(tempfile.gettempdir()) / "LoginAssistant"
    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_file = temp_dir / f"selftest_{int(time.time())}.txt"
    try:
        temp_file.write_text("LoginAssistant 自检文件，可关闭\n", encoding="utf-8")
    except OSError as exc:
        wipe(payload)
        result.headline = "无法创建自检临时文件"
        result.detail = f"{type(exc).__name__}"
        return result

    steps.append(f"启动记事本：{temp_file.name}")
    try:
        subprocess.Popen([_notepad_exe(), str(temp_file)], close_fds=True)
    except OSError as exc:
        wipe(payload)
        result.headline = "无法启动记事本"
        result.detail = f"{type(exc).__name__}: {exc}"
        return result

    target: winapi.WindowInfo | None = None
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        time.sleep(0.15)
        for info in winapi.enum_top_windows(include_tool_windows=True):
            if info.hwnd in before:
                continue
            if _is_notepad_window(info):
                target = winapi.get_window_info(info.hwnd, include_integrity=True) or info
                break
        if target:
            break
    if not target:
        wipe(payload)
        result.headline = "未检测到新的记事本窗口"
        result.detail = (
            "可能被已有记事本以标签页接管，或系统未安装记事本。"
            "请关闭所有记事本窗口后重试。"
        )
        return result

    result.hwnd = target.hwnd
    result.window_title = target.title
    steps.append(f"找到窗口：{target.title} (0x{target.hwnd:X}, PID {target.pid})")

    focus = winapi.focus_window(target.hwnd, timeout_ms=800)
    steps.append(focus.message)
    if not focus.ok:
        wipe(payload)
        result.headline = "记事本抢焦点失败"
        result.detail = focus.message
        return result

    sender = InputSender(
        hkl=winapi.get_keyboard_layout_for_window(target.hwnd),
        delay_min_ms=delay_min_ms,
        delay_max_ms=delay_max_ms,
        diagnostics=diagnostics,
    )
    ime = winapi.detach_ime(target.hwnd)
    steps.append(ime.detail)
    blocked = False
    try:
        if block_input:
            ok, err = winapi.block_input(True)
            blocked = ok
            steps.append("BlockInput(True) 成功" if ok else f"BlockInput(True) 失败 (WinError {err})")
            if not ok:
                result.detail = f"BlockInput 失败，已继续（WinError {err}）；"

        try:
            x, y, width, height = winapi.get_client_rect_screen(target.hwnd)
        except OSError as exc:
            result.headline = "读取记事本客户区失败"
            result.detail = str(exc)
            return result
        if width < 10 or height < 10:
            result.headline = "记事本窗口尺寸异常"
            result.detail = f"客户区 {width}x{height}"
            return result

        click = sender.click_screen(x + width // 2, y + height // 2)
        steps.append(f"点击文本区：{click.detail}")
        time.sleep(0.08)
        if winapi.get_foreground_window() != target.hwnd:
            result.headline = "点击后焦点不在记事本"
            result.detail = "可能被其它窗口抢走焦点，请关闭弹窗后重试"
            return result

        focus_info = winapi.target_focus_info(target.hwnd)
        if not focus_info.in_target:
            result.headline = "记事本文本区未获得焦点"
            result.detail = focus_info.detail
            return result

        sender.clear_field()
        steps.append("已清空记事本内容")
        report = sender.type_bytes(payload, progress=None)
        steps.append(f"已发送 {report.sent_chars}/{report.total_chars} 个字符")
        time.sleep(0.25)
        if winapi.get_foreground_window() != target.hwnd:
            result.headline = "输入过程中焦点丢失"
            result.detail = "输入可能被其它窗口接收，已停止"
            return result

        actual = _read_notepad_text(target.hwnd)
        result.actual = actual
        steps.append("读取回显完成（WM_GETTEXT）")
        if actual == test_text:
            result.ok = True
            result.headline = "记事本自检通过"
            result.detail = "SendInput 扫描码输入在本机有效。"
        else:
            result.headline = "记事本自检失败：回显不一致"
            result.detail = (
                "这说明输入层或键盘布局有问题。请检查："
                "① 目标布局是否为英文；② 是否有安全软件拦截模拟输入；"
                "③ 记事本是否获得焦点。"
            )
    except SendInputFailure as exc:
        result.headline = "SendInput 调用失败"
        result.detail = f"{exc}"
    except UnsupportedCharacterError as exc:
        result.headline = "测试串无法输入"
        result.detail = str(exc)
    except Exception as exc:  # pragma: no cover - 自检本身不崩溃
        result.headline = "自检异常"
        result.detail = f"{type(exc).__name__}: {exc}"
    finally:
        if blocked:
            ok, err = winapi.block_input(False)
            steps.append("BlockInput(False) 成功" if ok else f"BlockInput(False) 失败 (WinError {err})")
        if ime.ok:
            restored = winapi.restore_ime(ime)
            steps.append("IME 已恢复" if restored else "IME 恢复失败")
        wipe(payload)
        result.events_total = diagnostics.total_events if diagnostics else 0
        result.events_failed = diagnostics.failures if diagnostics else 0
        if result.ok and result.detail:
            result.detail = result.detail
        steps.append("记事本窗口保留，可人工核对；本工具不会读取/修改其它窗口内容")

    return result
