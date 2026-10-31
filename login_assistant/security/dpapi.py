"""Windows DPAPI (CryptProtectData / CryptUnprotectData) 封装。

约束：
* 作用域为 CurrentUser（不传 CRYPTPROTECT_LOCAL_MACHINE）；
* 传 CRYPTPROTECT_UI_FORBIDDEN，绝不弹系统对话框；
* 附加本应用专用 entropy，降低同用户下其它程序直接解密的机会；
* 任何失败只抛出不包含明文的 ``DPAPIError``。
"""

from __future__ import annotations

import base64
import ctypes
import ctypes.wintypes as wintypes
from typing import Final

CRYPTPROTECT_UI_FORBIDDEN: Final = 0x01
ENTROPY: Final = b"LoginAssistant:v1:dpapi:7c1f2a9e"

_CRYPT32 = ctypes.WinDLL("crypt32", use_last_error=True)
_KERNEL32 = ctypes.WinDLL("kernel32", use_last_error=True)


class DPAPIError(RuntimeError):
    """DPAPI 调用失败（消息中不含任何明文/密文内容）。"""


class _DATA_BLOB(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_byte)),
    ]


_CRYPT32.CryptProtectData.argtypes = [
    ctypes.POINTER(_DATA_BLOB),
    wintypes.LPCWSTR,
    ctypes.POINTER(_DATA_BLOB),
    ctypes.c_void_p,
    ctypes.c_void_p,
    wintypes.DWORD,
    ctypes.POINTER(_DATA_BLOB),
]
_CRYPT32.CryptProtectData.restype = wintypes.BOOL

_CRYPT32.CryptUnprotectData.argtypes = [
    ctypes.POINTER(_DATA_BLOB),
    ctypes.POINTER(wintypes.LPWSTR),
    ctypes.POINTER(_DATA_BLOB),
    ctypes.c_void_p,
    ctypes.c_void_p,
    wintypes.DWORD,
    ctypes.POINTER(_DATA_BLOB),
]
_CRYPT32.CryptUnprotectData.restype = wintypes.BOOL

_KERNEL32.LocalFree.argtypes = [ctypes.c_void_p]
_KERNEL32.LocalFree.restype = ctypes.c_void_p


def _blob(data: bytes) -> tuple[_DATA_BLOB, ctypes.Array]:
    size = max(1, len(data))
    buf = ctypes.create_string_buffer(data, size)
    blob = _DATA_BLOB(
        cbData=len(data),
        pbData=ctypes.cast(buf, ctypes.POINTER(ctypes.c_byte)),
    )
    return blob, buf


def _free_blob(blob: _DATA_BLOB) -> None:
    if blob.pbData:
        _KERNEL32.LocalFree(ctypes.cast(blob.pbData, ctypes.c_void_p))
    blob.pbData = None
    blob.cbData = 0


def protect(data: bytes, entropy: bytes | None = ENTROPY) -> bytes:
    """用当前用户主密钥加密 ``data``，返回密文字节。"""
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise TypeError("data 必须是 bytes")
    payload = bytes(data)
    in_blob, _keep_in = _blob(payload)
    ent_blob = None
    keep_ent = None
    ent_ptr = None
    if entropy:
        ent_blob, keep_ent = _blob(entropy)
        ent_ptr = ctypes.byref(ent_blob)
    out = _DATA_BLOB()
    ok = _CRYPT32.CryptProtectData(
        ctypes.byref(in_blob),
        "LoginAssistant credential",
        ent_ptr,
        None,
        None,
        CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(out),
    )
    if not ok:
        err = ctypes.get_last_error()
        raise DPAPIError(f"CryptProtectData 失败 (WinError {err})")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        _free_blob(out)


def unprotect(ciphertext: bytes, entropy: bytes | None = ENTROPY) -> bytes:
    """解密 DPAPI 密文，返回明文字节。调用方负责尽快覆写。"""
    if not isinstance(ciphertext, (bytes, bytearray, memoryview)):
        raise TypeError("ciphertext 必须是 bytes")
    payload = bytes(ciphertext)
    if not payload:
        raise DPAPIError("密文为空")
    in_blob, _keep_in = _blob(payload)
    ent_blob = None
    ent_ptr = None
    if entropy:
        ent_blob, _keep_ent = _blob(entropy)
        ent_ptr = ctypes.byref(ent_blob)
    out = _DATA_BLOB()
    ok = _CRYPT32.CryptUnprotectData(
        ctypes.byref(in_blob),
        None,
        ent_ptr,
        None,
        None,
        CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(out),
    )
    if not ok:
        err = ctypes.get_last_error()
        raise DPAPIError(
            f"CryptUnprotectData 失败 (WinError {err})；"
            "密文可能属于其他 Windows 用户/计算机，或文件已损坏"
        )
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        _free_blob(out)


def encrypt_b64(data: bytes) -> str:
    return base64.b64encode(protect(data)).decode("ascii")


def decrypt_b64(value: str) -> bytes:
    try:
        raw = base64.b64decode(value.encode("ascii"), validate=True)
    except (ValueError, UnicodeEncodeError) as exc:
        raise DPAPIError("密文不是合法的 base64") from exc
    return unprotect(raw)
