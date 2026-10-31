from __future__ import annotations

import unittest

from login_assistant.security.dpapi import (
    DPAPIError,
    decrypt_b64,
    encrypt_b64,
    protect,
    unprotect,
)


class DPAPITest(unittest.TestCase):
    def test_roundtrip_ascii(self) -> None:
        secret = b"Abc123!@#"
        cipher = protect(secret)
        self.assertNotEqual(cipher, secret)
        self.assertEqual(unprotect(cipher), secret)

    def test_roundtrip_utf8(self) -> None:
        secret = "密码-测试-🔐".encode("utf-8")
        self.assertEqual(unprotect(protect(secret)), secret)

    def test_roundtrip_long(self) -> None:
        secret = (b"x" * 4096) + b"end"
        self.assertEqual(unprotect(protect(secret)), secret)

    def test_base64_helpers(self) -> None:
        value = encrypt_b64(b"hello world")
        self.assertNotIn("hello", value)
        self.assertEqual(decrypt_b64(value), b"hello world")

    def test_tampered_ciphertext_fails(self) -> None:
        cipher = bytearray(protect(b"topsecret"))
        cipher[-8] ^= 0xFF
        with self.assertRaises(DPAPIError):
            unprotect(bytes(cipher))

    def test_wrong_entropy_fails(self) -> None:
        cipher = protect(b"topsecret", entropy=b"entropy-a")
        with self.assertRaises(DPAPIError):
            unprotect(cipher, entropy=b"entropy-b")

    def test_invalid_base64(self) -> None:
        with self.assertRaises(DPAPIError):
            decrypt_b64("not base64!!!")

    def test_error_does_not_leak_plaintext(self) -> None:
        try:
            decrypt_b64("AAAA")
        except DPAPIError as exc:
            self.assertNotIn("topsecret", str(exc))
        else:
            self.fail("应当抛出 DPAPIError")


if __name__ == "__main__":
    unittest.main()
