"""Protect persisted AI API keys with the current Windows user account."""

from __future__ import annotations

import base64
import binascii
import ctypes
import sys
from typing import Any

# ctypes.wintypes 仅 Windows 存在，非 Windows 顶层导入会炸；DPAPI 调用都在
# dpapi_available() 守卫内，非 Windows 走明文回落。
if sys.platform == "win32":
    from ctypes import wintypes  # noqa: F401

DPAPI_PREFIX = "dpapi:v1:"
_CRYPTPROTECT_UI_FORBIDDEN = 0x01


class _DataBlob(ctypes.Structure):
    # wintypes.DWORD 即 c_uint32（Windows unsigned long），布局一致且跨平台可定义
    _fields_ = [
        ("cbData", ctypes.c_uint32),
        ("pbData", ctypes.POINTER(ctypes.c_ubyte)),
    ]


def dpapi_available() -> bool:
    return sys.platform == "win32"


def is_encrypted(value: Any) -> bool:
    return isinstance(value, str) and value.startswith(DPAPI_PREFIX)


def _input_blob(data: bytes) -> tuple[_DataBlob, ctypes.Array[ctypes.c_char]]:
    buffer = ctypes.create_string_buffer(data)
    blob = _DataBlob(
        len(data),
        ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)),
    )
    return blob, buffer


def protect_api_key(plaintext: str) -> str:
    """Return a DPAPI envelope on Windows; keep plaintext on other platforms."""
    value = str(plaintext or "")
    if not value or not dpapi_available():
        return value

    raw = value.encode("utf-8")
    input_blob, input_buffer = _input_blob(raw)
    output_blob = _DataBlob()
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    crypt32.CryptProtectData.argtypes = [
        ctypes.POINTER(_DataBlob),
        wintypes.LPCWSTR,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(_DataBlob),
    ]
    crypt32.CryptProtectData.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p

    if not crypt32.CryptProtectData(
        ctypes.byref(input_blob),
        "Nexuz AI API key",
        None,
        None,
        None,
        _CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(output_blob),
    ):
        raise OSError(ctypes.get_last_error(), "Windows DPAPI encryption failed")
    del input_buffer

    try:
        encrypted = ctypes.string_at(output_blob.pbData, output_blob.cbData)
        return DPAPI_PREFIX + base64.b64encode(encrypted).decode("ascii")
    finally:
        kernel32.LocalFree(output_blob.pbData)


def unprotect_api_key(stored: Any) -> tuple[str, bool]:
    """
    Return ``(plaintext, is_legacy_plaintext)``.

    A malformed or non-decryptable DPAPI envelope raises ValueError so callers
    can avoid overwriting data that may belong to another Windows account.
    """
    value = str(stored or "")
    if not value:
        return "", False
    if not is_encrypted(value):
        return value, True
    if not dpapi_available():
        raise ValueError("Windows DPAPI is unavailable")

    try:
        encrypted = base64.b64decode(value[len(DPAPI_PREFIX) :], validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError("Invalid DPAPI API key envelope") from exc

    input_blob, input_buffer = _input_blob(encrypted)
    output_blob = _DataBlob()
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    crypt32.CryptUnprotectData.argtypes = [
        ctypes.POINTER(_DataBlob),
        ctypes.POINTER(wintypes.LPWSTR),
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(_DataBlob),
    ]
    crypt32.CryptUnprotectData.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p

    if not crypt32.CryptUnprotectData(
        ctypes.byref(input_blob),
        None,
        None,
        None,
        None,
        _CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(output_blob),
    ):
        raise ValueError(
            f"Windows DPAPI decryption failed (error {ctypes.get_last_error()})"
        )
    del input_buffer

    try:
        plaintext = ctypes.string_at(output_blob.pbData, output_blob.cbData)
        return plaintext.decode("utf-8"), False
    except UnicodeDecodeError as exc:
        raise ValueError("DPAPI API key is not valid UTF-8") from exc
    finally:
        kernel32.LocalFree(output_blob.pbData)
