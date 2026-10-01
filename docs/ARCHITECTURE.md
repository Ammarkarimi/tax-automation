# System Architecture

## 1. High-level view

```
 ┌──────────────────────────┐      ┌──────────────────────────┐
 │  Web app (React+Tailwind)│      │ Mobile app (Expo / RN)   │
 │  Vite dev server :5173   │      │ iOS / Android            │
 │  access token: memory    │      │ access token: memory     │
 │  refresh: httpOnly cookie│      │ refresh: SecureStore     │
 └────────────┬─────────────┘      └────────────┬─────────────┘
              │ HTTPS (local cert) / proxy /api │ HTTPS / HTTP(LAN dev)
              └───────────────┬─────────────────┘
                              ▼
 ┌──────────────────────────────────────────────────────────────────┐
 │                    FastAPI backend  (:8000)                      │
 │                                                                  │
 │  Middleware: request-id · security headers · CORS · JSON logs    │
 │  ┌──────────┐ ┌───────────┐ ┌────────────┐ ┌────────┐ ┌───────┐  │
 │  │ auth     │ │ documents │ │ bookkeeping│ │ tax    │ │ admin │  │
 │  │ JWT+OTP  │ │ upload    │ │ txns/forms │ │ calc/AI│ │ RBAC  │  │
 │  └────┬─────┘ └─────┬─────┘ └─────┬──────┘ └───┬────┘ └───┬───┘  │
 │       │      ┌──────▼──────────────▼───────────▼──┐       │      │
 │       │      │            Services                │       │      │
 │       │      │ storage(AES-GCM) · parsing · pdf   │       │      │
 │       │      │ document_service · tax_service     │       │      │
 │       │      │ audit · email · rate_limit         │       │      │
 │       │      └──────┬───────────────┬─────────────┘       │      │
 │       │   ┌─────────▼─────┐   ┌─────▼──────────────────┐  │      │
 │       │   │ Tax engine    │   │ AI pipeline            │  │      │
 │       │   │ (pure Decimal)│   │ redact → OpenAI JSON   │  │      │
 │       │   │ 1040/SchC/SE  │   │ schema → validate →    │  │      │
 │       │   │ QBI/CTC/1040ES│   │ fallback to rules      │  │      │
 │       │   │ deductions    │   └─────────┬──────────────┘  │      │
 │       │   │ audit risk    │             │                 │      │
 │       │   └───────────────┘             │                 │      │
 └───────┼─────────────────────────────────┼─────────────────┼──────┘
         ▼                                 ▼                 ▼
 ┌───────────────┐  ┌───────────────────┐  ┌──────────────────────┐
 │ PostgreSQL    │  │ Encrypted file    │  │ OpenAI API           │
 │ (PII columns  │  │ store ./storage   │  │ (opt-in, redacted,   │
 │  AES-GCM)     │  │ *.bin AES-256-GCM │  │  store=false)        │
 └───────────────┘  └───────────────────┘  └──────────────────────┘
         ▲
 ┌───────┴───────┐
 │ SMTP / Mailpit│  ← OTP emails (console backend in dev)
 └───────────────┘
```

**Guiding principle: AI explains, the engine calculates.** Every number on a
return comes from the deterministic, unit-tested tax engine. OpenAI is used for
reading documents, suggesting categories and writing explanations — and every AI
path has a rule-based fallback so the product works fully offline.

## 2. Repository layout

```
tax-automation/
├── backend/                 FastAPI service
│   ├── app/
│   │   ├── main.py          app factory, middleware, routers, startup
│   │   ├── core/            config, crypto (AES-GCM/HMAC), security (Argon2/JWT),
│   │   │                    logging (JSON + PII redaction), redaction
│   │   ├── db/              SQLAlchemy base, encrypted column types, sessions
│   │   ├── models/          ORM models + enums (categories → Schedule C lines)
│   │   ├── schemas/         Pydantic request/response contracts
│   │   ├── api/             deps (auth/RBAC) + routes/{auth,account,documents,
│   │   │                    bookkeeping,tax,admin}.py
│   │   ├── services/        storage, parsing, document pipeline, tax_service,
│   │   │                    pdf, email, audit, rate limiting
│   │   ├── ai/              OpenAI client, prompts, classifier, document
│   │   │                    extractor, explainer
│   │   └── tax/             tables (per-year params), engine, quarterly,
│   │                        deductions, audit_risk, context
│   ├── tests/               engine, API (end-to-end), AI (fake OpenAI client)
│   ├── scripts/             secrets generator, demo seed, sample-data generator
│   └── sample_data/         fictional corner-shop bank CSV, 1099-NEC, invoice
├── frontend/                React 19 + Tailwind v4 (Vite)
├── mobile/                  Expo SDK 57 + Expo Router (React Native)
├── docs/                    this documentation, schema.sql, openapi.json
├── scripts/gen-dev-cert.sh  local TLS certificates
└── docker-compose.yml       local Postgres + Mailpit only
```

## 3. Key flows

### 3.1 Sign-in with MFA

```
Client                         API                                   DB / Email
  │ POST /auth/login {email,pw} │                                       │
  │────────────────────────────►│ rate-limit · lockout check            │
  │                             │ Argon2id verify (dummy hash if no user)│
  │                             │ create OTP: HMAC(challenge:code) ─────►│ otp_codes
  │                             │ send 6-digit code ────────────────────►│ email
  │◄── {mfa_token (JWT, 10 min, cid=challenge)} ────────────────────────│
  │ POST /auth/verify-otp {mfa_token, code}                             │
  │────────────────────────────►│ decode mfa JWT → challenge            │
  │                             │ attempts<5, not expired, constant-time│
  │                             │ compare, mark consumed                │
  │                             │ issue access JWT (15 min, ver=pw hash)│
  │                             │ issue refresh (opaque, HMAC stored) ─►│ refresh_tokens
  │◄── access_token + refresh (cookie for web / body for mobile) ───────│
```

Refresh tokens rotate on every use and belong to a *family*; presenting an
already-rotated token revokes the entire family (stolen-token detection).
Changing the password changes the `ver` claim, invalidating all access tokens.

### 3.2 Document → transactions

```
upload ─► validate size / MIME / magic bytes ─► sha256 de-dup
       ─► AES-256-GCM encrypt (AAD = storage key) ─► ./storage/xx/<key>.bin
       ─► process:
            CSV  ─► parse_bank_csv (sniff dialect, find header, Amount or Debit/Credit)
            PDF  ─► pypdf text ─► [AI consented?] redact ─► OpenAI (strict JSON schema)
                                   └─ else / on failure ─► regex extraction
            IMG  ─► [AI consented?] OpenAI vision ─► else "enter manually"
       ─► W-2/1099 ─► income_forms (unconfirmed until user confirms)
          invoice/receipt/CSV rows ─► classify ─► transactions
```

### 3.3 Classification pipeline

```
transactions ─► keyword rules (≈30 patterns, confidence 0.5–0.95)
                 │ confidence ≥ 0.8 → done (no AI cost, no data sent)
                 ▼
              OpenAI batch of 40 (redacted descriptions + business context)
                 │ strict JSON schema: category ∈ enum, business_use_pct, confidence
                 │ hallucinated refs dropped; AI only wins if more confident
                 ▼
              confidence < 0.7 or uncategorized → needs_review = true
              user edits → classified_by = "user" (never overwritten by re-runs)
```

### 3.4 Tax computation

```
tax_service.aggregate()
  transactions × business_use_pct  ─┐
  income forms (W-2, 1099-NEC/K/MISC/INT/DIV)
  tax profile (filing status, inventory, miles, home office, dependents…)
  estimated payments                ─┴─► TaxInput ─► engine.compute_tax()
                                                       │
  Schedule C (incl. Part III COGS, 50% meals, mileage, simplified home office)
  Schedule SE (92.35%, SS wage base minus W-2 SS wages, $400 floor)
  Form 8959 Additional Medicare Tax
  Schedule 1 adjustments (½ SE tax, SEP, SE health insurance, with limits)
  Standard deduction (+65 add-on) · OBBBA Schedule 1-A (tips, seniors)
  QBI (20%, taxable-income cap, phase-out w/o W-2 wages, SSTB, 2026 $400 min)
  Bracket tax · CTC/ODC with phase-out · ACTC (Schedule 8812)
  Payments → refund / amount owed
                                                       │
            ┌──────────────────┬───────────────────────┼───────────────────┐
            ▼                  ▼                       ▼                   ▼
     quarterly.py         deductions.py          audit_risk.py         pdf.py
  annualize YTD,        rule-based ideas w/    11 weighted red       1040, Sch 1,
  safe harbor 90% /     $ savings at marginal  flags → score/level   2, C, SE,
  100% / 110%, due      income + SE rate                             8995 worksheet
  dates (weekend roll)
```

Year-specific parameters (brackets, standard deduction, SS wage base, mileage
rate, QBI thresholds, CTC amounts, SEP limit, OBBBA deductions) for TY2024–2026
live in one file, `backend/app/tax/tables.py`, so the annual update is one diff.

Results are stored as encrypted, immutable snapshots in `tax_calculations`
together with the engine version for auditability.

## 4. Data model (summary)

See [`schema.sql`](schema.sql) for the full DDL.

```
users 1──* otp_codes
      1──* refresh_tokens (family_id)
      1──* tax_profiles (unique per year)
      1──* documents 1──* transactions
                     1──* income_forms
      1──* estimated_payments
      1──* tax_calculations (encrypted snapshots)
      1──* generated_reports (PDF sha256)
audit_logs (append-only, actor_id without FK so history survives deletion)
```

## 5. Why these choices

| Decision | Reason |
| --- | --- |
| Synchronous SQLAlchemy 2.0 | Simple, testable; FastAPI runs sync endpoints in a threadpool. |
| App-level AES-GCM for PII | DB dumps/backups contain ciphertext only; key lives outside the DB. |
| Deterministic engine, AI only for language | Tax math must be reproducible and testable; LLMs can't be trusted with arithmetic. |
| Structured Outputs (strict JSON Schema) | Model output is validated against enums; no free-text parsing. |
| Rules before AI | Most transactions are obvious; cheaper, faster, and nothing leaves the server. |
| Worksheet PDF instead of filled IRS PDFs | IRS PDF field names change yearly; a line-numbered worksheet is stable and transcribable (filling official PDFs is on the roadmap). |
| SQLite in tests, Postgres in dev | Fast hermetic tests; the suite also passes on PostgreSQL 16 with `schema.sql` (`TEST_DATABASE_URL`). |
