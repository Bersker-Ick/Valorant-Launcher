"""字符 -> (VK, Shift) -> 扫描码 映射。

实现依据（Windows Win32）：
* ``VkKeyScanExW(ch, hkl)``：返回低字节 VK，高字节 shift 状态
  （bit0 Shift，bit1 Ctrl，bit2 Alt）。
* ``MapVirtualKeyExW(vk, MAPVK_VK_TO_VSC, hkl)``：VK -> 扫描码。
* 发送时使用 ``KEYEVENTF_SCANCODE``，Shift 用左 Shift 的扫描码 0x2A。

扫描码方案对键盘布局敏感：同一物理键在不同布局下会打出不同字符。
因此调用方应传入**目标窗口线程的键盘布局 HKL**；未传时退回当前线程布局
（等价于 ``VkKeyScanW`` / ``MapVirtualKeyW``）。
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wintypes
from dataclasses import dataclass
from functools import lru_cache

_USER32 = ctypes.WinDLL("user32", use_last_error=True)

MAPVK_VK_TO_VSC = 0
KLF_NOTELLSHELL = 0x00000080

VK_SHIFT = 0x10
VK_CONTROL = 0x11
VK_MENU = 0x12

SCAN_LSHIFT = 0x2A
SCAN_LCONTROL = 0x1D
SCAN_LALT = 0x38
SCAN_TAB = 0x0F
SCAN_ENTER = 0x1C
SCAN_ESCAPE = 0x01
SCAN_BACKSPACE = 0x0E
SCAN_DELETE = 0x53

_USER32.VkKeyScanW.argtypes = [wintypes.WCHAR]
_USER32.VkKeyScanW.restype = ctypes.c_short
_USER32.VkKeyScanExW.argtypes = [wintypes.WCHAR, wintypes.HKL]
_USER32.VkKeyScanExW.restype = ctypes.c_short
_USER32.MapVirtualKeyW.argtypes = [wintypes.UINT, wintypes.UINT]
_USER32.MapVirtualKeyW.restype = wintypes.UINT
_USER32.MapVirtualKeyExW.argtypes = [wintypes.UINT, wintypes.UINT, wintypes.HKL]
_USER32.MapVirtualKeyExW.restype = wintypes.UINT
_USER32.LoadKeyboardLayoutW.argtypes = [wintypes.LPCWSTR, wintypes.UINT]
_USER32.LoadKeyboardLayoutW.restype = wintypes.HKL
_USER32.GetKeyboardLayout.argtypes = [wintypes.DWORD]
_USER32.GetKeyboardLayout.restype = wintypes.HKL

# 这些扫描码对应的键是扩展键，需要 KEYEVENTF_EXTENDEDKEY
EXTENDED_SCANCODES = {
    0x1C,  # Numpad Enter
    0x35,  # Numpad /
    0x37,  # PrintScreen
    0x38,  # Right Alt
    0x46,  # Break
    0x47,  # Home
    0x48,  # Up
    0x49,  # PageUp
    0x4B,  # Left
    0x4D,  # Right
    0x4F,  # End
    0x50,  # Down
    0x51,  # PageDown
    0x52,  # Insert
    0x53,  # Delete
    0x5B,  # Left Win
    0x5C,  # Right Win
    0x5D,  # Menu
    0x6F,  # Numpad /
}

EXTENDED_VKS = {
    0x21,  # PageUp
    0x22,  # PageDown
    0x23,  # End
    0x24,  # Home
    0x25,  # Left
    0x26,  # Up
    0x27,  # Right
    0x28,  # Down
    0x2D,  # Insert
    0x2E,  # Delete
    0x5B,  # LWin
    0x5C,  # RWin
    0x5D,  # Apps
    0x6F,  # Divide
}

# 0x20..0x7E 全部可打印 ASCII
_PRINTABLE_ASCII = frozenset(range(0x20, 0x7F))


class UnsupportedCharacterError(ValueError):
    """字符在当前键盘布局下无法用扫描码输入（如中文、控制字符）。"""


@dataclass(frozen=True)
class KeyStroke:
    vk: int
    scan: int
    shift: bool = False
    extended: bool = False

    @property
    def needs_ctrl(self) -> bool:
        return False

    @property
    def needs_alt(self) -> bool:
        return False


@lru_cache(maxsize=8)
def load_layout(langid: str = "00000409") -> int:
    """加载（但不激活）指定键盘布局，返回 HKL；失败返回 0。"""
    hkl = _USER32.LoadKeyboardLayoutW(langid, KLF_NOTELLSHELL)
    return int(hkl or 0)


def current_layout() -> int:
    return int(_USER32.GetKeyboardLayout(0) or 0)


def char_to_stroke(ch: str, hkl: int | None = None) -> KeyStroke:
    if len(ch) != 1:
        raise UnsupportedCharacterError("char_to_stroke 只接受单个字符")
    code = ord(ch)
    if code not in _PRINTABLE_ASCII:
        raise UnsupportedCharacterError(f"字符 U+{code:04X} 不是可打印 ASCII")
    if hkl:
        raw = _USER32.VkKeyScanExW(ch, hkl)
    else:
        raw = _USER32.VkKeyScanW(ch)
    if raw == -1 or (raw & 0xFFFF) == 0xFFFF:
        raise UnsupportedCharacterError(f"字符 U+{code:04X} 无法映射到键位")
    vk = raw & 0xFF
    state = (raw >> 8) & 0xFF
    if state & 0x06:
        raise UnsupportedCharacterError(
            f"字符 U+{code:04X} 需要 Ctrl/Alt 组合，本工具不支持"
        )
    if hkl:
        scan = _USER32.MapVirtualKeyExW(vk, MAPVK_VK_TO_VSC, hkl)
    else:
        scan = _USER32.MapVirtualKeyW(vk, MAPVK_VK_TO_VSC)
    if not scan:
        raise UnsupportedCharacterError(f"字符 U+{code:04X} 无法取得扫描码")
    return KeyStroke(
        vk=vk,
        scan=scan,
        shift=bool(state & 0x01),
        # 扩展键必须按 VK 判断：例如主键盘 '/' 和数字键盘 '/' 共用扫描码
        # 0x35，但只有后者是扩展键；按扫描码判断会把 '?' 打成别的键。
        extended=vk in EXTENDED_VKS,
    )


class KeyMapper:
    """绑定到某个键盘布局的字符映射器。"""

    def __init__(self, hkl: int | None = None) -> None:
        self.hkl = int(hkl) if hkl else None

    def stroke_for(self, ch: str) -> KeyStroke:
        return char_to_stroke(ch, self.hkl)

    def is_supported(self, ch: str) -> bool:
        try:
            self.stroke_for(ch)
            return True
        except UnsupportedCharacterError:
            return False

    def unsupported_chars(self, text: str) -> list[str]:
        return [ch for ch in text if not self.is_supported(ch)]


def is_typeable_bytes(data: bytes | bytearray) -> bool:
    return all(byte in _PRINTABLE_ASCII for byte in data)


def first_unsupported_byte(data: bytes | bytearray) -> int | None:
    for index, byte in enumerate(data):
        if byte not in _PRINTABLE_ASCII:
            return index
    return None


def describe_unsupported(data: bytes | bytearray) -> str:
    index = first_unsupported_byte(data)
    if index is None:
        return ""
    return (
        "包含无法用扫描码模拟的字符（仅支持 ASCII 可打印字符，"
        "中文/Emoji 等需手动输入）"
    )
