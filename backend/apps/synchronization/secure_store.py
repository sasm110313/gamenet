"""Credential storage for the edge's cloud identity.

Windows: DPAPI (user-scoped) via ctypes, so the JSON on disk is useless to a
different Windows account or a copied file. Non-Windows dev: 0600 file, which is
explicitly a development-only fallback and is logged as such.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger("gamenet.secure_store")

_IS_WINDOWS = sys.platform == "win32"


def _dpapi_available() -> bool:
    return _IS_WINDOWS


def _dpapi_encrypt(data: bytes) -> bytes:
    import ctypes
    from ctypes import wintypes

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    def blob(payload: bytes) -> DATA_BLOB:
        buf = ctypes.create_string_buffer(payload, len(payload))
        return DATA_BLOB(len(payload), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))

    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    out = DATA_BLOB()
    if not crypt32.CryptProtectData(
        ctypes.byref(blob(data)), None, None, None, None, 0, ctypes.byref(out)
    ):
        raise OSError("CryptProtectData failed")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        kernel32.LocalFree(out.pbData)


def _dpapi_decrypt(data: bytes) -> bytes:
    import ctypes
    from ctypes import wintypes

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    def blob(payload: bytes) -> DATA_BLOB:
        buf = ctypes.create_string_buffer(payload, len(payload))
        return DATA_BLOB(len(payload), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))

    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    out = DATA_BLOB()
    if not crypt32.CryptUnprotectData(
        ctypes.byref(blob(data)), None, None, None, None, 0, ctypes.byref(out)
    ):
        raise OSError("CryptUnprotectData failed")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        kernel32.LocalFree(out.pbData)


class SecureStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def exists(self) -> bool:
        return self.path.exists()

    def save(self, payload: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        raw = json.dumps(payload, indent=2, sort_keys=True).encode()
        if _dpapi_available():
            raw = b"DPAPI1:" + _dpapi_encrypt(raw)
        else:
            logger.warning(
                "secure_store: DPAPI unavailable, writing 0600 plaintext (dev only) to %s",
                self.path,
            )
        tmp = self.path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as fh:
            fh.write(raw)
        os.replace(tmp, self.path)

    def load(self) -> dict:
        raw = self.path.read_bytes()
        if raw.startswith(b"DPAPI1:"):
            if not _dpapi_available():
                raise RuntimeError("credentials were DPAPI-protected on another platform")
            raw = _dpapi_decrypt(raw[len(b"DPAPI1:"):])
        return json.loads(raw)

    def delete(self) -> None:
        self.path.unlink(missing_ok=True)
