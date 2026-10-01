"""Encryption-at-rest and keyed hashing helpers.

* Files and sensitive DB columns are encrypted with AES-256-GCM (authenticated
  encryption: tampering is detected on decrypt).
* One-time passwords and refresh tokens are never stored in plaintext; we store
  an HMAC-SHA256 of them keyed with a server secret, so a DB leak alone does not
  allow replaying them.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import get_settings

_VERSION = b"\x01"  # lets us rotate the scheme/key later without ambiguity
_NONCE_BYTES = 12


def _aesgcm() -> AESGCM:
    return AESGCM(get_settings().encryption_key_bytes)


def encrypt_bytes(plaintext: bytes, associated_data: bytes | None = None) -> bytes:
    """Encrypt bytes. Output layout: version(1) | nonce(12) | ciphertext+tag."""
    nonce = os.urandom(_NONCE_BYTES)
    return _VERSION + nonce + _aesgcm().encrypt(nonce, plaintext, associated_data)


def decrypt_bytes(blob: bytes, associated_data: bytes | None = None) -> bytes:
    if not blob or blob[:1] != _VERSION:
        raise ValueError("unsupported ciphertext version")
    nonce, ct = blob[1 : 1 + _NONCE_BYTES], blob[1 + _NONCE_BYTES :]
    return _aesgcm().decrypt(nonce, ct, associated_data)


def encrypt_str(value: str) -> str:
    return base64.urlsafe_b64encode(encrypt_bytes(value.encode("utf-8"))).decode("ascii")


def decrypt_str(value: str) -> str:
    return decrypt_bytes(base64.urlsafe_b64decode(value.encode("ascii"))).decode("utf-8")


def keyed_hash(value: str) -> str:
    """HMAC-SHA256 hex digest used for OTPs, refresh tokens and blind indexes."""
    key = get_settings().hmac_secret.encode("utf-8")
    return hmac.new(key, value.encode("utf-8"), hashlib.sha256).hexdigest()


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def generate_otp(digits: int = 6) -> str:
    """Cryptographically secure numeric one-time password."""
    return "".join(secrets.choice("0123456789") for _ in range(digits))


def generate_token(nbytes: int = 48) -> str:
    return secrets.token_urlsafe(nbytes)
