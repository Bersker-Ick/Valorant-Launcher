"""安全相关：DPAPI、脱敏、明文缓冲清理。"""

from .dpapi import DPAPIError, decrypt_b64, encrypt_b64, protect, unprotect
from .redact import MASK, RedactingFilter, RedactingFormatter, redact_text
from .secret import to_bytearray, wipe

__all__ = [
    "DPAPIError",
    "MASK",
    "RedactingFilter",
    "RedactingFormatter",
    "decrypt_b64",
    "encrypt_b64",
    "protect",
    "redact_text",
    "to_bytearray",
    "unprotect",
    "wipe",
]
