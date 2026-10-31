from __future__ import annotations

import unittest

from login_assistant.core.keymap import (
    KeyMapper,
    UnsupportedCharacterError,
    describe_unsupported,
    first_unsupported_byte,
    is_typeable_bytes,
    load_layout,
)

# US 布局：字符 -> (VK, 需要 Shift, 扫描码)
EXPECTED = {
    "a": (0x41, False, 0x1E),
    "A": (0x41, True, 0x1E),
    "z": (0x5A, False, 0x2C),
    "Z": (0x5A, True, 0x2C),
    "0": (0x30, False, 0x0B),
    "1": (0x31, False, 0x02),
    "9": (0x39, False, 0x0A),
    " ": (0x20, False, 0x39),
    "!": (0x31, True, 0x02),
    "@": (0x32, True, 0x03),
    "#": (0x33, True, 0x04),
    "$": (0x34, True, 0x05),
    "%": (0x35, True, 0x06),
    "^": (0x36, True, 0x07),
    "&": (0x37, True, 0x08),
    "*": (0x38, True, 0x09),
    "(": (0x39, True, 0x0A),
    ")": (0x30, True, 0x0B),
    "-": (0xBD, False, 0x0C),
    "_": (0xBD, True, 0x0C),
    "=": (0xBB, False, 0x0D),
    "+": (0xBB, True, 0x0D),
    "[": (0xDB, False, 0x1A),
    "{": (0xDB, True, 0x1A),
    "]": (0xDD, False, 0x1B),
    "}": (0xDD, True, 0x1B),
    "\\": (0xDC, False, 0x2B),
    "|": (0xDC, True, 0x2B),
    ";": (0xBA, False, 0x27),
    ":": (0xBA, True, 0x27),
    "'": (0xDE, False, 0x28),
    '"': (0xDE, True, 0x28),
    ",": (0xBC, False, 0x33),
    "<": (0xBC, True, 0x33),
    ".": (0xBE, False, 0x34),
    ">": (0xBE, True, 0x34),
    "/": (0xBF, False, 0x35),
    "?": (0xBF, True, 0x35),
    "`": (0xC0, False, 0x29),
    "~": (0xC0, True, 0x29),
}


class KeyMapTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.hkl = load_layout("00000409")
        if not cls.hkl:
            raise unittest.SkipTest("无法加载 en-US 键盘布局 00000409")

    def test_letters_digits_symbols(self) -> None:
        mapper = KeyMapper(self.hkl)
        for ch, (vk, shift, scan) in EXPECTED.items():
            with self.subTest(ch=ch):
                stroke = mapper.stroke_for(ch)
                self.assertEqual(stroke.vk, vk)
                self.assertEqual(stroke.shift, shift)
                self.assertEqual(stroke.scan, scan)
                self.assertFalse(stroke.extended, f"{ch} 不应该是扩展键")

    def test_question_mark_is_not_extended(self) -> None:
        # 回归：主键盘 '/' 与数字键盘 '/' 共用扫描码 0x35，
        # 不能因为 0x35 在扩展键集合里就把 '?' 标记为 extended。
        stroke = KeyMapper(self.hkl).stroke_for("?")
        self.assertEqual(stroke.scan, 0x35)
        self.assertFalse(stroke.extended)

    def test_all_printable_ascii_supported(self) -> None:
        mapper = KeyMapper(self.hkl)
        for code in range(0x20, 0x7F):
            ch = chr(code)
            with self.subTest(code=code):
                stroke = mapper.stroke_for(ch)
                self.assertGreater(stroke.vk, 0)
                self.assertGreater(stroke.scan, 0)

    def test_unsupported(self) -> None:
        mapper = KeyMapper(self.hkl)
        for ch in ("中", "\n", "\t", "🔐", "é"):
            with self.subTest(ch=ch):
                with self.assertRaises(UnsupportedCharacterError):
                    mapper.stroke_for(ch)

    def test_byte_helpers(self) -> None:
        self.assertTrue(is_typeable_bytes(b"Abc123!@#"))
        self.assertFalse(is_typeable_bytes("中".encode("utf-8")))
        self.assertEqual(first_unsupported_byte(b"abc\xe4"), 3)
        self.assertIn("ASCII", describe_unsupported(b"\xe4"))


if __name__ == "__main__":
    unittest.main()
