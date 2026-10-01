"""Encrypted local file storage.

Files are encrypted with AES-256-GCM before touching disk and stored under a
random key (no user names or original filenames in paths). The storage key is
bound into the ciphertext as associated data, so swapping two files on disk is
detected on decrypt.
"""

from __future__ import annotations

import os
import secrets
from pathlib import Path

from app.core.config import get_settings
from app.core.crypto import decrypt_bytes, encrypt_bytes


def _root() -> Path:
    root = Path(get_settings().storage_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _path_for(key: str) -> Path:
    if not key or not all(c.isalnum() or c in "-_" for c in key):
        raise ValueError("invalid storage key")  # blocks path traversal
    return _root() / key[:2] / f"{key}.bin"


def save(data: bytes) -> str:
    key = secrets.token_urlsafe(24).replace("-", "a").replace("_", "b")
    path = _path_for(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "wb") as fh:
        fh.write(encrypt_bytes(data, associated_data=key.encode()))
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)
    return key


def load(key: str) -> bytes:
    with open(_path_for(key), "rb") as fh:
        return decrypt_bytes(fh.read(), associated_data=key.encode())


def delete(key: str) -> None:
    try:
        _path_for(key).unlink()
    except FileNotFoundError:
        pass
