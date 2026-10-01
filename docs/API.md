# API Specification

* Base URL: `http://localhost:8000/api/v1`
* Machine-readable spec: [`openapi.json`](openapi.json) (OpenAPI 3.1). With the
  server running, interactive docs are at `http://localhost:8000/docs`.
* Auth: `Authorization: Bearer <access_token>` on every endpoint except
  `/auth/*` (pre-login), `/meta` and `/health`.
* Tax year: most endpoints take `?year=2025` (supported years: 2024, 2025, 2026).
  If it's left out, the server picks the year currently being filed.
* Errors: `{"detail": "message"}` or, for validation errors,
  `{"detail": [{"loc": [...], "msg": "...", "type": "..."}]}`. Submitted values are
  never echoed back.
* Mobile clients send `X-Client-Type: mobile` to receive refresh tokens in JSON.

```yaml
openapi: 3.1.0
info: { title: TaxPilot API, version: 1.0.0 }
security: [ { bearerAuth: [] } ]
components:
  securitySchemes:
    bearerAuth: { type: http, scheme: bearer, bearerFormat: JWT }
```

## Authentication

| Method | Path | Body | Response | Notes |
| --- | --- | --- | --- | --- |
| POST | `/auth/register` | `{email, password, full_name?}` | `202 MFAChallenge` | Sends an email-verification OTP. Duplicate emails get a decoy challenge. |
| POST | `/auth/login` | `{email, password}` | `200 MFAChallenge` | 401 generic error; 423 when locked; 429 when rate-limited. |
| POST | `/auth/verify-otp` | `{mfa_token, code}` | `200 TokenResponse` | Sets the `tp_refresh` cookie (web) or returns `refresh_token` (mobile). |
| POST | `/auth/resend-otp` | `{mfa_token}` | `200 MFAChallenge` | Invalidates the previous code. |
| POST | `/auth/refresh` | `{refresh_token?}` | `200 TokenResponse` | Uses the cookie if there's no body; cookie mode requires `X-Requested-With: XMLHttpRequest`. Rotates the token. |
| POST | `/auth/logout` | `{refresh_token?}` | `204` | Revokes the token family. |
| GET | `/auth/me` | – | `UserOut` | |
| POST | `/auth/change-password` | `{current_password, new_password}` | `204` | Revokes all sessions. |

```jsonc
// MFAChallenge
{ "mfa_required": true, "mfa_token": "eyJ…", "delivery": "email",
  "masked_email": "s***@example.com", "expires_in": 600 }

// TokenResponse
{ "access_token": "eyJ…", "token_type": "bearer", "expires_in": 900,
  "refresh_token": null,            // string for X-Client-Type: mobile
  "user": { "id": "…", "email": "…", "full_name": "…", "role": "user",
            "email_verified": true, "ai_consent": false, "created_at": "…" } }
```

## Account, profile & privacy

| Method | Path | Description |
| --- | --- | --- |
| GET | `/meta` | Supported years and the category list (with Schedule C line). Public. |
| PATCH | `/me/settings` | `{full_name?, ai_consent?}` |
| GET | `/profile?year=` | Tax profile (SSN returned only as `ssn_last4`). Created on first access, carrying facts forward from the prior year. |
| PUT | `/profile?year=` | Partial update: filing status, identity (encrypted), business info, dependents, inventory, miles, home office, tips, prior-year tax/AGI. |
| GET | `/me/export` | All of the user's data as JSON. |
| POST | `/me/delete` | `{password}` — permanent erasure of rows and files. |

## Documents

| Method | Path | Description |
| --- | --- | --- |
| POST | `/documents?year=` | `multipart/form-data`: `file`, `doc_type?` (`w2`, `1099_nec`, `1099_k`, `1099_misc`, `1099_int`, `1099_div`, `invoice`, `receipt`, `bank_csv`), `process?=true`. 201 → `DocumentOut`. 409 duplicate, 422 rejected file. |
| GET | `/documents?year=` | List |
| GET | `/documents/{id}` | Detail, including `extracted_data` |
| POST | `/documents/{id}/process` | Re-run extraction (e.g. after enabling AI) |
| GET | `/documents/{id}/download` | Decrypted original (`Cache-Control: no-store`) |
| DELETE | `/documents/{id}?delete_transactions=true` | Deletes the file plus the transactions and forms derived from it |

```jsonc
// DocumentOut (bank CSV)
{ "id": "…", "tax_year": 2025, "original_filename": "statement.csv",
  "doc_type": "bank_csv", "status": "processed",
  "extracted_data": { "method": "csv", "rows_in_file": 255, "rows_imported": 255,
                      "skipped_other_years": 0 } }
// extracted_data (1099-NEC via AI)
{ "doc_type": "1099_nec", "method": "ai", "payer_name": "Sunrise Catering LLC",
  "amounts": { "nonemployee_compensation": 8450.0 }, "confidence": 0.95 }
```

## Bookkeeping

| Method | Path | Description |
| --- | --- | --- |
| GET | `/transactions?year=&category=&direction=&needs_review=&search=&page=&page_size=` | Paginated `{items, total, page, page_size}` |
| POST | `/transactions?year=` | `{txn_date, description, amount>0, direction, category?, business_use_pct, notes?}` — auto-classified when there's no category |
| PATCH | `/transactions/{id}` | Partial update; changing the category marks it `classified_by=user` |
| DELETE | `/transactions/{id}` | |
| POST | `/transactions/bulk-categorize` | `{ids[], category, business_use_pct?}` |
| POST | `/transactions/reclassify?year=` | `{only_needs_review}` — re-runs rules + AI, never overwrites user edits |
| GET | `/transactions/export.csv?year=` | CSV including a deductible-amount column |
| GET/POST | `/income-forms?year=` | W-2/1099 data: `{form_type, payer_name, amounts:{field: number}, confirmed}` |
| PUT/DELETE | `/income-forms/{id}` | |
| GET/POST | `/estimated-payments?year=` | `{quarter 1-4, amount, paid_on}` |
| DELETE | `/estimated-payments/{id}` | |

Allowed `amounts` fields: `wages`, `federal_withholding`, `social_security_wages`,
`medicare_wages`, `nonemployee_compensation`, `gross_payments`, `rents`,
`royalties`, `other_income`, `interest_income`, `ordinary_dividends`,
`qualified_dividends`.

## Tax

| Method | Path | Description |
| --- | --- | --- |
| GET | `/tax/annual?year=` | Full computation (see below). Saves an encrypted snapshot. |
| GET | `/tax/quarterly?year=&as_of=` | 1040-ES plan: projection, safe harbor, 4 installments with status (`paid`, `underpaid`, `upcoming`, `covered`), `next_payment` |
| GET | `/tax/deductions?year=&include_ai=` | `{suggestions[], potential_savings, ai_used}` |
| GET | `/tax/audit-risk?year=&explain=` | `{score 0-100, level, factors[], disclaimer, explanation?}` |
| GET | `/tax/explain?year=` | `{source: "ai"|"template", markdown}` |
| POST | `/tax/ask?year=` | `{question}` → `{source, markdown}` |
| POST | `/tax/reports/return-pdf?year=` | Generates the Form 1040 + Schedules PDF → `{id, sha256, created_at}` |
| GET | `/tax/reports?year=` | List of generated PDFs |
| GET | `/tax/reports/{id}/download` | `application/pdf` |

```jsonc
// GET /tax/annual (abridged)
{
  "engine_version": "1.0.0", "tax_year": 2025, "filing_status": "single",
  "schedule_c": { "line1_gross_receipts": 173582.1, "line4_cogs": 65783.8,
                  "expenses_by_line": { "8": 651.14, "9": 1260.0, "20b": 28800.0 },
                  "line28_total_expenses": 38614.52, "line31_net_profit": 69183.78 },
  "schedule_se": { "line4a_net_earnings": 63891.22, "line12_se_tax": 9775.36,
                   "line13_deductible_half": 4887.68 },
  "form_1040": { "line11_agi": 64296.1, "line12_standard_deduction": 15750.0,
                 "line13a_qbi_deduction": 9709.22, "line15_taxable_income": 38836.88,
                 "line24_total_tax": 14197.29, "line26_estimated_payments": 7200.0,
                 "line37_amount_owed": 6997.29 },
  "summary": { "total_tax": 14197.29, "effective_rate": 0.2052,
               "marginal_income_rate": 0.12, "marginal_se_rate": 0.1413 },
  "warnings": ["…"],
  "data_quality": { "transactions": 255, "needs_review": 27,
                    "reported_1099_income": 8450.0, "recorded_receipts": 173582.1 }
}
```

## Admin (role `admin` or `support`)

| Method | Path | Description |
| --- | --- | --- |
| GET | `/admin/stats` | User/document/transaction counts, classifier mix, 24-hour security events (logins, failures, refresh-reuse alerts), AI status |
| GET | `/admin/users?limit=&offset=` | Masked emails, role, status, counts — never tax data |
| PATCH | `/admin/users/{id}` | **admin only:** `{role?, is_active?, unlock?}` |
| GET | `/admin/audit-logs?action=&actor_id=&success=&limit=&offset=` | Audit trail (prefix filter on `action`) |

## System

| Method | Path | Description |
| --- | --- | --- |
| GET | `/health` | `{status, database, ai_enabled}` |
