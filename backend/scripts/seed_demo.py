"""Create a demo shopkeeper account pre-loaded with the sample bank statement.

Usage (from backend/, with .env configured and the DB running):
    python scripts/seed_demo.py
Then sign in at http://localhost:5173 with the printed credentials; the OTP is
printed in the backend console (EMAIL_BACKEND=console) or shown in Mailpit.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from app.core.crypto import sha256_hex  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.db.session import session_factory  # noqa: E402
from app.main import init_db  # noqa: E402
from app.models import Document, User  # noqa: E402
from app.services import storage  # noqa: E402
from app.services.document_service import process_document  # noqa: E402
from app.services.tax_service import get_or_create_profile  # noqa: E402

EMAIL = "demo@example.com"
PASSWORD = "DemoShop2025!"
YEAR = 2025


def main() -> None:
    init_db()
    db = session_factory()()
    if db.scalar(select(User).where(User.email == EMAIL)):
        print(f"Demo user already exists: {EMAIL} / {PASSWORD}")
        return
    user = User(email=EMAIL, password_hash=hash_password(PASSWORD), full_name="Demo Shopkeeper", email_verified=True)
    db.add(user)
    db.commit()
    profile = get_or_create_profile(db, user, YEAR)
    profile.business_name = "Corner Market (Demo)"
    profile.business_description = "Neighborhood convenience & grocery store"
    profile.business_code = "445131"
    profile.is_cash_intensive = True
    profile.beginning_inventory = 8000
    profile.ending_inventory = 9500
    profile.business_miles = 1800
    profile.prior_year_tax = 7200
    profile.prior_year_agi = 61000
    db.commit()

    raw = (Path(__file__).resolve().parent.parent / "sample_data" / "bank_statement_2025.csv").read_bytes()
    doc = Document(user_id=user.id, tax_year=YEAR, original_filename="bank_statement_2025.csv",
                   content_type="text/csv", size_bytes=len(raw), sha256=sha256_hex(raw), storage_key=storage.save(raw))
    db.add(doc)
    db.commit()
    process_document(db, user, doc, "csv", None)
    print(f"Demo user created: {EMAIL} / {PASSWORD}  (tax year {YEAR})")


if __name__ == "__main__":
    main()
