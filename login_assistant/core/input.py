"""SendInput 键盘/鼠标注入（扫描码方案）与诊断记录。

严格约束：
* 每条事件单独调用 SendInput，记录返回值与 GetLastError；
* 键盘使用 KEYEVENTF_SCANCODE，Shift 用左 Shift 扫描码；
* 字符间隔 40~80 ms 随机抖动（可配置）；
* 诊断记录只保存扫描码/VK/flags，不保存字符，避免密码进入日志；
* 不做任何 hook、驱动、硬件 HID 或规避检测的处理。
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wintypes
import random
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Callable, Deque

from . import winapi
from .keymap import (
    SCAN_DELETE,
    SCAN_ENTER,
    SCAN_LCONTROL,
    SCAN_LSHIFT,
    SCAN_TAB,
    KeyMapper,
    KeyStroke,
    UnsupportedCharacterError,
    first_unsupported_byte,
    describe_unsupported,
)
from ..security.secret import wipe

USER32 = winapi.USER32

KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008

MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004

INPUT_KEYBOARD = 1
INPUT_MOUSE = 0

ULONG_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class _INPUTUNION(ctypes.Union):
    _fields_ = [
        ("ki", KEYBDINPUT),
        ("mi", MOUSEINPUT),
        ("hi", HARDWAREINPUT),
    ]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


USER32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
USER32.SendInput.restype = wintypes.UINT
USER32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
USER32.SetCursorPos.restype = wintypes.BOOL


@dataclass(frozen=True)
class InputEvent:
    seq: int
    kind: str
    vk: int
    scan: int
    flags: int
    ret: int
    error: int
    at: float


@dataclass(frozen=True)
class TypeReport:
    sent_chars: int
    total_chars: int
    aborted: bool


@dataclass(frozen=True)
class MouseReport:
    ok: bool
    x: int
    y: int
    detail: str


class SendInputFailure(RuntimeError):
    def __init__(self, message: str, *, winerror: int, sent_chars: int, kind: str) -> None:
        super().__init__(message)
        self.winerror = winerror
        self.sent_chars = sent_chars
        self.kind = kind


class InputDiagnostics:
    """线程安全的 SendInput 事件环形缓冲（不记录字符内容）。"""

    def __init__(self, maxlen: int = 500) -> None:
        self._lock = threading.Lock()
        self._items: Deque[InputEvent] = deque(maxlen=maxlen)
        self._seq = 0
        self.total_events = 0
        self.failures = 0

    def record(self, kind: str, vk: int, scan: int, flags: int, ret: int, error: int) -> InputEvent:
        with self._lock:
            self._seq += 1
            event = InputEvent(
                seq=self._seq,
                kind=kind,
                vk=vk,
                scan=scan,
                flags=flags,
                ret=ret,
                error=error,
                at=time.monotonic(),
            )
            self._items.append(event)
            self.total_events += 1
            if ret != 1:
                self.failures += 1
            return event

    def snapshot(self) -> list[InputEvent]:
        with self._lock:
            return list(self._items)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()
            self.total_events = 0
            self.failures = 0

    def last_error(self) -> int:
        with self._lock:
            return self._items[-1].error if self._items else 0


class InputSender:
    def __init__(
        self,
        *,
        hkl: int | None = None,
        delay_min_ms: int = 40,
        delay_max_ms: int = 80,
        diagnostics: InputDiagnostics | None = None,
        sleep: Callable[[float], None] = time.sleep,
        rng: random.Random | None = None,
    ) -> None:
        self.hkl = hkl or None
        self.delay_min = max(0, min(delay_min_ms, delay_max_ms)) / 1000.0
        self.delay_max = max(delay_min_ms, delay_max_ms) / 1000.0
        self.diag = diagnostics or InputDiagnostics()
        self.sleep = sleep
        self.rng = rng or random.Random()

    # -- low level ---------------------------------------------------------
    def _send(self, inp: INPUT, kind: str, vk: int, scan: int, flags: int) -> None:
        ctypes.set_last_error(0)
        sent = int(USER32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT)))
        error = ctypes.get_last_error() if sent != 1 else 0
        self.diag.record(kind, vk, scan, flags, sent, error)
        if sent != 1:
            detail = "UIPI/权限不足" if error == 5 else "SendInput 失败"
            raise SendInputFailure(
                f"{detail}（SendInput 返回 {sent}, GetLastError={error}）",
                winerror=error,
                sent_chars=0,
                kind=kind,
            )

    def key_event(self, scan: int, *, keyup: bool, extended: bool = False, vk: int = 0) -> None:
        flags = KEYEVENTF_SCANCODE
        if keyup:
            flags |= KEYEVENTF_KEYUP
        if extended:
            flags |= KEYEVENTF_EXTENDEDKEY
        inp = INPUT(type=INPUT_KEYBOARD)
        inp.u.ki = KEYBDINPUT(wVk=vk, wScan=scan, dwFlags=flags, time=0, dwExtraInfo=0)
        self._send(inp, "key_up" if keyup else "key_down", vk, scan, flags)

    def tap_scan(self, scan: int, *, extended: bool = False, vk: int = 0) -> None:
        self.key_event(scan, keyup=False, extended=extended, vk=vk)
        self.sleep(self.rng.uniform(0.006, 0.014))
        self.key_event(scan, keyup=True, extended=extended, vk=vk)

    def tap_stroke(self, stroke: KeyStroke) -> None:
        if stroke.shift:
            self.key_event(SCAN_LSHIFT, keyup=False, vk=0x10)
            self.sleep(self.rng.uniform(0.006, 0.014))
        self.key_event(stroke.scan, keyup=False, extended=stroke.extended, vk=stroke.vk)
        self.sleep(self.rng.uniform(0.006, 0.014))
        self.key_event(stroke.scan, keyup=True, extended=stroke.extended, vk=stroke.vk)
        if stroke.shift:
            self.sleep(self.rng.uniform(0.006, 0.014))
            self.key_event(SCAN_LSHIFT, keyup=True, vk=0x10)

    def press_combo(
        self,
        modifier_scan: int,
        key_scan: int,
        *,
        modifier_vk: int = 0x11,
        key_vk: int = 0,
        key_extended: bool = False,
    ) -> None:
        self.key_event(modifier_scan, keyup=False, vk=modifier_vk)
        self.sleep(self.rng.uniform(0.008, 0.016))
        self.key_event(key_scan, keyup=False, extended=key_extended, vk=key_vk)
        self.sleep(self.rng.uniform(0.008, 0.016))
        self.key_event(key_scan, keyup=True, extended=key_extended, vk=key_vk)
        self.sleep(self.rng.uniform(0.008, 0.016))
        self.key_event(modifier_scan, keyup=True, vk=modifier_vk)

    def tap_enter(self) -> None:
        self.tap_scan(SCAN_ENTER, vk=0x0D)

    def tap_tab(self) -> None:
        self.tap_scan(SCAN_TAB, vk=0x09)

    def select_all(self) -> None:
        self.press_combo(SCAN_LCONTROL, 0x1E, modifier_vk=0x11, key_vk=0x41)  # Ctrl+A

    def delete_forward(self) -> None:
        self.tap_scan(SCAN_DELETE, extended=True, vk=0x2E)

    def backspace(self) -> None:
        self.tap_scan(0x0E, vk=0x08)

    def clear_field(self) -> None:
        """先全选，再用 Backspace + Delete 双保险清空。"""
        self.select_all()
        self.sleep(self.rng.uniform(0.025, 0.045))
        self.backspace()
        self.sleep(self.rng.uniform(0.015, 0.03))
        self.delete_forward()

    # -- text --------------------------------------------------------------
    def type_bytes(
        self,
        data: bytearray | bytes,
        *,
        cancel: Callable[[], bool] | None = None,
        progress: Callable[[int, int], None] | None = None,
    ) -> TypeReport:
        """逐字节输入 ASCII；完成后尽力覆写 bytearray。"""
        payload = data
        total = len(payload)
        unsupported = first_unsupported_byte(payload)
        if unsupported is not None:
            message = describe_unsupported(payload)
            if isinstance(payload, bytearray):
                wipe(payload)
            raise UnsupportedCharacterError(message)
        mapper = KeyMapper(self.hkl)
        sent = 0
        aborted = False
        try:
            for index, byte in enumerate(payload):
                if cancel is not None and cancel():
                    aborted = True
                    break
                ch = chr(byte)
                try:
                    stroke = mapper.stroke_for(ch)
                except UnsupportedCharacterError:
                    raise
                self.tap_stroke(stroke)
                sent += 1
                if progress is not None:
                    try:
                        progress(sent, total)
                    except Exception:
                        pass
                if index + 1 < total:
                    self.sleep(self.rng.uniform(self.delay_min, self.delay_max))
            return TypeReport(sent_chars=sent, total_chars=total, aborted=aborted)
        except SendInputFailure as exc:
            raise SendInputFailure(
                str(exc),
                winerror=exc.winerror,
                sent_chars=sent,
                kind=exc.kind,
            ) from exc
        finally:
            if isinstance(payload, bytearray):
                wipe(payload)

    # -- mouse -------------------------------------------------------------
    def click_screen(self, x: int, y: int, *, clicks: int = 1) -> MouseReport:
        x, y = int(x), int(y)
        clicks = max(1, min(int(clicks), 3))
        ctypes.set_last_error(0)
        if not USER32.SetCursorPos(x, y):
            error = ctypes.get_last_error()
            self.diag.record("move", 0, 0, 0, 0, error)
            return MouseReport(False, x, y, f"SetCursorPos 失败 (WinError {error})")
        self.sleep(0.03)
        try:
            for index in range(clicks):
                inp = INPUT(type=INPUT_MOUSE)
                inp.u.mi = MOUSEINPUT(0, 0, 0, MOUSEEVENTF_LEFTDOWN, 0, 0)
                self._send(inp, "mouse_down", 0, 0, MOUSEEVENTF_LEFTDOWN)
                self.sleep(self.rng.uniform(0.02, 0.035))
                inp = INPUT(type=INPUT_MOUSE)
                inp.u.mi = MOUSEINPUT(0, 0, 0, MOUSEEVENTF_LEFTUP, 0, 0)
                self._send(inp, "mouse_up", 0, 0, MOUSEEVENTF_LEFTUP)
                if index + 1 < clicks:
                    self.sleep(self.rng.uniform(0.045, 0.075))
        except SendInputFailure as exc:
            return MouseReport(False, x, y, str(exc))
        return MouseReport(True, x, y, f"click x{clicks} sent")
