"""Protect persisted AI API keys with the current Windows user account."""

from __future__ import annotations

import base64
import binascii
import ctypes
import sys
from ctypes import wintypes
from typing import Any

DPAPI_PREFIX = "dpapi:v1:"
_CRYPTPROTECT_UI_FORBIDDEN = 0x01


class _DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
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
