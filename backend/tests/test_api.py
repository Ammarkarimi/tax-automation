"""End-to-end API tests against an isolated SQLite DB (no network, AI disabled)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.db.session import get_engine
from app.main import create_app
from app.services import rate_limit

PASSWORD = "Sup3rSecretPass!"
SAMPLE_CSV = (Path(__file__).parent.parent / "sample_data" / "bank_statement_2025.csv").read_bytes()

_outbox: list[tuple[str, str]] = []


@pytest.fixture(autouse=True)
def capture_otps(monkeypatch):
    def fake_send(to, code, purpose, ttl):
        _outbox.append((to, code))

    monkeypatch.setattr("app.api.routes.auth.send_otp_email", fake_send)
    monkeypatch.setattr("app.api.routes.auth.send_email", lambda *a, **k: None)
    for limiter in (rate_limit.login_limiter, rate_limit.otp_limiter, rate_limit.register_limiter,
                    rate_limit.ai_limiter):
        limiter.reset()
    yield


@pytest.fixture(scope="module")
def client():
    app = create_app()
    with TestClient(app) as c:
        yield c


def _last_code(email: str) -> str:
    return next(code for to, code in reversed(_outbox) if to == email)


def signup(client: TestClient, email: str, mobile: bool = False) -> dict:
    r = client.post("/api/v1/auth/register", json={"email": email, "password": PASSWORD, "full_name": "Test User"})
    assert r.status_code == 202, r.text
    headers = {"X-Client-Type": "mobile"} if mobile else {}
    r = client.post("/api/v1/auth/verify-otp", json={"mfa_token": r.json()["mfa_token"], "code": _last_code(email)},
                    headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    body["headers"] = {"Authorization": f"Bearer {body['access_token']}"}
    return body


def test_register_verify_login_flow(client):
    s = signup(client, "shop@example.com")
    assert s["user"]["email_verified"] is True
    assert s["refresh_token"] is None  # web client gets an httpOnly cookie instead
    assert "tp_refresh" in client.cookies

    r = client.post("/api/v1/auth/login", json={"email": "shop@example.com", "password": PASSWORD})
    assert r.status_code == 200 and r.json()["mfa_required"]
    assert r.json()["masked_email"] == "s***@example.com"
    bad = client.post("/api/v1/auth/verify-otp", json={"mfa_token": r.json()["mfa_token"], "code": "000000"})
    assert bad.status_code == 401
    ok = client.post("/api/v1/auth/verify-otp",
                     json={"mfa_token": r.json()["mfa_token"], "code": _last_code("shop@example.com")})
    assert ok.status_code == 200
    # OTP is single-use
    again = client.post("/api/v1/auth/verify-otp",
                        json={"mfa_token": r.json()["mfa_token"], "code": _last_code("shop@example.com")})
    assert again.status_code == 401


def test_duplicate_registration_does_not_leak(client):
    signup(client, "dup@example.com")
    r = client.post("/api/v1/auth/register", json={"email": "dup@example.com", "password": PASSWORD})
    assert r.status_code == 202 and "mfa_token" in r.json()  # identical shape to a fresh signup


def test_weak_password_rejected(client):
    r = client.post("/api/v1/auth/register", json={"email": "weak@example.com", "password": "alllowercase1"})
    assert r.status_code == 422


def test_lockout_after_failed_logins(client):
    signup(client, "lock@example.com")
    for _ in range(5):
        r = client.post("/api/v1/auth/login", json={"email": "lock@example.com", "password": "WrongPassword123"})
        assert r.status_code == 401
    r = client.post("/api/v1/auth/login", json={"email": "lock@example.com", "password": PASSWORD})
    assert r.status_code == 423


def test_refresh_rotation_and_reuse_detection(client):
    s = signup(client, "mobile@example.com", mobile=True)
    rt1 = s["refresh_token"]
    assert rt1
    mobile = {"X-Client-Type": "mobile"}
    r = client.post("/api/v1/auth/refresh", json={"refresh_token": rt1}, headers=mobile)
    assert r.status_code == 200
    rt2 = r.json()["refresh_token"]
    # Reusing the old token revokes the whole family, including rt2
    assert rt2 and rt2 != rt1
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": rt1}, headers=mobile).status_code == 401
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": rt2}, headers=mobile).status_code == 401


def test_cookie_refresh_requires_csrf_header(client):
    signup(client, "cookie@example.com")
    assert client.post("/api/v1/auth/refresh").status_code == 403
    r = client.post("/api/v1/auth/refresh", headers={"X-Requested-With": "XMLHttpRequest"})
    assert r.status_code == 200


def test_requires_auth(client):
    assert client.get("/api/v1/tax/annual").status_code == 401
    assert client.get("/api/v1/tax/annual", headers={"Authorization": "Bearer garbage"}).status_code == 401


def test_full_tax_workflow(client, tmp_root):
    s = signup(client, "baker@example.com")
    h = s["headers"]

    r = client.put("/api/v1/profile?year=2025", headers=h, json={
        "filing_status": "single", "business_description": "Neighborhood grocery store",
        "business_code": "445110", "is_cash_intensive": True, "ssn": "123-45-6789",
        "beginning_inventory": 5000, "ending_inventory": 6000, "business_miles": 1200,
        "prior_year_tax": 9000, "prior_year_agi": 70000,
    })
    assert r.status_code == 200, r.text
    assert r.json()["ssn_last4"] == "6789" and "ssn" not in r.json()

    # Upload bank CSV -> parsed + classified
    r = client.post("/api/v1/documents?year=2025", headers=h,
                    files={"file": ("statement.csv", SAMPLE_CSV, "text/csv")})
    assert r.status_code == 201, r.text
    doc = r.json()
    assert doc["status"] == "processed" and doc["extracted_data"]["rows_imported"] > 10

    # Duplicate upload rejected
    r = client.post("/api/v1/documents?year=2025", headers=h, files={"file": ("statement.csv", SAMPLE_CSV, "text/csv")})
    assert r.status_code == 409

    # Spoofed type rejected (claims PDF but isn't)
    r = client.post("/api/v1/documents?year=2025", headers=h, files={"file": ("x.pdf", b"not a pdf", "application/pdf")})
    assert r.status_code == 422

    txns = client.get("/api/v1/transactions?year=2025&page_size=500", headers=h).json()
    cats = {t["category"] for t in txns["items"]}
    assert {"business_income", "inventory_purchases", "rent_property", "estimated_tax_payment"} <= cats

    # Manual correction of one item
    review = client.get("/api/v1/transactions?year=2025&needs_review=true", headers=h).json()
    if review["items"]:
        tid = review["items"][0]["id"]
        r = client.patch(f"/api/v1/transactions/{tid}", headers=h, json={"category": "supplies"})
        assert r.status_code == 200 and r.json()["classified_by"] == "user"

    # Add a 1099-K manually
    r = client.post("/api/v1/income-forms?year=2025", headers=h, json={
        "form_type": "1099_k", "payer_name": "Square", "amounts": {"gross_payments": 1000}})
    assert r.status_code == 201

    annual = client.get("/api/v1/tax/annual?year=2025", headers=h).json()
    assert annual["schedule_c"]["line1_gross_receipts"] > 0
    assert annual["schedule_c"]["line4_cogs"] > 0
    assert annual["form_1040"]["line26_estimated_payments"] > 0
    assert annual["summary"]["total_tax"] > 0

    q = client.get("/api/v1/tax/quarterly?year=2025", headers=h).json()
    assert len(q["quarters"]) == 4

    ded = client.get("/api/v1/tax/deductions?year=2025", headers=h).json()
    assert any(sug["id"] == "sep-ira" for sug in ded["suggestions"])

    risk = client.get("/api/v1/tax/audit-risk?year=2025&explain=true", headers=h).json()
    assert any(f["id"] == "cash-business" for f in risk["factors"])
    assert risk["explanation"]["source"] == "template"

    exp = client.get("/api/v1/tax/explain?year=2025", headers=h).json()
    assert "Self-employment tax" in exp["markdown"]

    ans = client.post("/api/v1/tax/ask?year=2025", headers=h, json={"question": "Why do I owe so much?"}).json()
    assert ans["source"] == "template"

    rep = client.post("/api/v1/tax/reports/return-pdf?year=2025", headers=h)
    assert rep.status_code == 200
    pdf = client.get(f"/api/v1/tax/reports/{rep.json()['id']}/download", headers=h)
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")

    export = client.get("/api/v1/transactions/export.csv?year=2025", headers=h)
    assert export.status_code == 200 and export.text.startswith("date,description")

    # ---- Encryption at rest ----
    with get_engine().connect() as conn:
        raw_desc = conn.execute(text("SELECT description FROM transactions LIMIT 1")).scalar()
        raw_ssn = conn.execute(text("SELECT ssn FROM tax_profiles WHERE ssn IS NOT NULL LIMIT 1")).scalar()
    assert "6789" not in raw_ssn
    assert not re.search(r"[a-z]{4} [a-z]{4}", raw_desc, re.I)  # ciphertext, not prose
    stored = list(Path(tmp_root, "storage").rglob("*.bin"))
    assert stored and all(b"Date" not in p.read_bytes() and not p.read_bytes().startswith(b"%PDF") for p in stored)

    # ---- Data isolation between users ----
    other = signup(client, "other@example.com")
    assert client.get(f"/api/v1/documents/{doc['id']}", headers=other["headers"]).status_code == 404
    assert client.get("/api/v1/transactions?year=2025", headers=other["headers"]).json()["total"] == 0

    # ---- RBAC ----
    assert client.get("/api/v1/admin/stats", headers=h).status_code == 403


def test_admin_endpoints(client):
    s = signup(client, "admin@example.com")
    with get_engine().begin() as conn:
        conn.execute(text("UPDATE users SET role='admin' WHERE email='admin@example.com'"))
    h = s["headers"]
    stats = client.get("/api/v1/admin/stats", headers=h)
    assert stats.status_code == 200 and stats.json()["users"]["total"] >= 1
    users = client.get("/api/v1/admin/users", headers=h).json()
    assert all("@" in u["email_masked"] and "***" in u["email_masked"] for u in users)
    logs = client.get("/api/v1/admin/audit-logs?action=auth.", headers=h).json()
    assert logs and all("password" not in (l["details"] or {}) for l in logs)


def test_change_password_invalidates_tokens(client):
    s = signup(client, "pw@example.com")
    r = client.post("/api/v1/auth/change-password", headers=s["headers"],
                    json={"current_password": PASSWORD, "new_password": "An0therStrongPass"})
    assert r.status_code == 204
    assert client.get("/api/v1/auth/me", headers=s["headers"]).status_code == 401


def test_delete_account(client):
    s = signup(client, "bye@example.com")
    r = client.post("/api/v1/me/delete", headers=s["headers"], json={"password": PASSWORD})
    assert r.status_code == 204
    assert client.get("/api/v1/auth/me", headers=s["headers"]).status_code == 401
