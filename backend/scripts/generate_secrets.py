"""Print freshly generated secrets for backend/.env.

Usage (from backend/):  python scripts/generate_secrets.py >> .env   (then remove the placeholders)
"""

import base64
import secrets

print(f"JWT_SECRET={secrets.token_urlsafe(48)}")
print(f"HMAC_SECRET={secrets.token_urlsafe(48)}")
print(f"DATA_ENCRYPTION_KEY={base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()}")
