"""Test configuration: isolated SQLite DB, generated secrets, no network calls."""

from __future__ import annotations

import base64
import os
import secrets
import tempfile

# Settings must be in the environment before the app is imported.
_tmp = tempfile.mkdtemp(prefix="taxpilot-test-")
os.environ.update(
    {
        "ENVIRONMENT": "test",
        "DATABASE_URL": f"sqlite:///{_tmp}/test.db",
        "JWT_SECRET": secrets.token_urlsafe(48),
        "HMAC_SECRET": secrets.token_urlsafe(48),
        "DATA_ENCRYPTION_KEY": base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(),
        "OPENAI_API_KEY": "",  # force rule-based fallbacks: tests never hit the network
        "EMAIL_BACKEND": "console",
        "STORAGE_DIR": f"{_tmp}/storage",
        "BOOTSTRAP_ADMIN_EMAIL": "",
    }
)

import pytest  # noqa: E402


@pytest.fixture(scope="session")
def tmp_root() -> str:
    return _tmp
