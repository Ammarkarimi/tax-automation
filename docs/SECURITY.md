# Security & Privacy Model

TaxPilot stores some of the most sensitive data a person has: income, SSNs,
bank statements. The design goal is that a leak of any single component — the
database, the file store, a log file, or a stolen phone — does not expose
usable PII.

## 1. Threat model (summary)

| Threat | Mitigations |
| --- | --- |
| Database dump / backup leak | AES-256-GCM application-level encryption of names, SSNs, addresses, transaction descriptions, notes, filenames, extraction results and calculation snapshots. OTPs and refresh tokens stored only as HMAC-SHA256. Passwords as Argon2id. |
| File-store leak | Every upload/PDF encrypted with AES-256-GCM; storage key used as AAD (files can't be swapped); random names with no PII; files `0600`. |
| Credential stuffing / brute force | Argon2id, 12+ char complexity policy, per-IP rate limits on login/OTP/register, account lockout (5 failures → 15 min), generic error messages, timing equalization with a dummy hash. |
| Account enumeration | Login returns the same error for unknown users; registering an existing email returns an indistinguishable decoy challenge and notifies the real owner by email. |
| Stolen password | Mandatory email OTP (MFA) on every sign-in; OTP bound to one challenge, 5-minute TTL, 5 attempts, single-use, constant-time comparison. |
| Stolen session token | 15-minute access tokens; refresh tokens rotate on every use; reuse of a rotated token revokes the whole family and raises an admin alert; password change invalidates all tokens (`ver` claim). |
| XSS (web) | Access token only in memory; refresh token is an `httpOnly`, `SameSite=Strict` cookie scoped to `/api/v1/auth`; React escapes output; Markdown rendered with `react-markdown` (no raw HTML); API sends CSP `default-src 'none'`. |
| CSRF | Bearer tokens for all data endpoints; cookie-based refresh additionally requires `X-Requested-With`; strict SameSite. |
| IDOR (accessing another user's data) | Every query filters by `user_id`; "not found" and "not yours" return the same 404. Covered by tests. |
| Privilege escalation | Server-side RBAC (`user`, `support`, `admin`) via `require_roles`; admins can't demote/deactivate themselves; client guards are UX only. |
| Malicious uploads | Size limit, MIME allow-list, magic-byte verification, no execution, stored encrypted outside any web root, download with `Content-Disposition: attachment`; CSV export neutralizes formula injection. |
| PII in logs | All log records pass a redaction filter (SSN, EIN, emails, card/account numbers, phones); validation errors never echo submitted values; audit logs store ids and safe metadata only. |
| Data sent to third parties (OpenAI) | Opt-in per user (`ai_consent`, default off). Text is PII-redacted before sending; only computed numbers (no names/SSNs/descriptions) go to explanation prompts; `store=false`; images only with consent (they can't be redacted, and the UI says so). |
| Stolen phone | Refresh token in iOS Keychain / Android Keystore via SecureStore with `WHEN_UNLOCKED_THIS_DEVICE_ONLY`; Android backups disabled; no data cached on disk by the app. |
| Prompt injection via documents | Model output is constrained to a strict JSON schema with enums; amounts are user-confirmed; the model has no tools and can't take actions; the engine — not the model — computes tax. |
| Tampering with the audit trail | `audit_logs` has a trigger that rejects UPDATE/DELETE (see `schema.sql`). |

## 2. Encryption

**At rest**

* Algorithm: AES-256-GCM (authenticated), 96-bit random nonce per value,
  versioned envelope `0x01 | nonce | ciphertext+tag`.
* Key: `DATA_ENCRYPTION_KEY` (32 random bytes, env var) — never stored in the DB.
* Columns: see `[ENC]` markers in [`schema.sql`](schema.sql).
* Keyed hashes: `HMAC_SECRET` for OTPs and refresh tokens.
* Rotation (roadmap): the version byte allows a re-encryption job to move data
  to a new key; until then rotate by exporting/re-importing.

**In transit**

* `scripts/gen-dev-cert.sh` creates a local certificate (mkcert or openssl).
  Run uvicorn with `--ssl-keyfile/--ssl-certfile`, and Vite picks the same certs
  up automatically; set `COOKIE_SECURE=true`.
* HSTS is sent whenever the request scheme is HTTPS.
* PostgreSQL: add `?sslmode=require` to `DATABASE_URL` when the DB isn't on localhost.
* OpenAI and SMTP (with `SMTP_USE_TLS=true`) use TLS.

## 3. Authentication & authorization

* JWT HS256 with a pinned algorithm, required `exp/iat/sub/type`, issuer check,
  and separate token types (`access`, `mfa`) that can't be swapped.
* Roles:
  * `user` — only their own data.
  * `support` — admin dashboard, masked user list, audit logs. No tax data,
    no documents, no edits.
  * `admin` — support + change roles, disable/unlock accounts.
* Even admins can't read another user's tax data through the API: there's no
  endpoint for it (least privilege by construction).

## 4. Privacy features

* **Consent:** AI processing is off until the user turns it on.
* **Minimization:** SSN optional; masked to last 4 in API responses and PDFs.
* **Access:** `GET /api/v1/me/export` returns all of a user's data as JSON.
* **Erasure:** `POST /api/v1/me/delete` deletes the account, all rows (FK
  cascade) and all encrypted files; the audit log keeps only an opaque id.
* **No tracking:** no analytics or third-party scripts in the web or mobile apps.

## 5. Audit trail

Recorded events include: register, login success/failure, lockout, OTP
failures, refresh-token reuse, logout, password change, profile changes,
document upload/process/download/delete, transaction CRUD and bulk edits,
form and payment changes, tax calculations, report generation/download, AI
questions, admin changes, data export and account deletion. Each entry has a
timestamp, actor id and role, action, resource, success flag, IP, user agent
and request id.

## 6. Secrets handling

* All secrets come from environment variables / `.env` (git-ignored); the app
  refuses to start with placeholder values or a malformed encryption key.
* `python scripts/generate_secrets.py` creates strong values.
* `OPENAI_API_KEY` is only read from the environment.
* Mobile `EXPO_PUBLIC_*` variables are public by definition — only the API URL
  goes there.

## 7. Known limitations (local-dev scope)

* The rate limiter is in-process memory (use Redis with multiple workers).
* Document processing is synchronous within the request.
* Key rotation is manual.
* The console email backend prints OTPs to stdout and is refused when
  `ENVIRONMENT=production`.
