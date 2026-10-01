# Future Roadmap

Scope today: a complete local system for federal Schedule C filers that
prepares, calculates and explains returns (no e-filing, no IRS integration,
no hosting). Possible next steps:

## Near term (v1.x)

- **Fill the official IRS PDFs** (AcroForm) for Form 1040, Schedules 1/2/C/SE
  and Form 8995 alongside the worksheet, with field maps versioned per tax year.
- **Mileage log**: trip entry and GPS import in the mobile app, feeding Schedule C
  line 9 and Part IV.
- **Receipt matching**: link receipt photos to bank transactions automatically
  (amount, date and merchant similarity).
- **Background processing queue** (RQ/Celery + Redis) for large uploads, plus a
  Redis-backed rate limiter for multi-worker setups.
- **Alembic migrations** generated from the models, with schema drift checks
  against `docs/schema.sql`.
- **Mobile PDF download/share** via expo-file-system + expo-sharing.
- **Push reminders** for quarterly due dates (expo-notifications).
- **TOTP / passkeys** as additional MFA factors; trusted-device remember-me.

## Tax coverage

- Depreciation & Section 179 asset register (Form 4562), vehicle actual-cost
  method with depreciation.
- Itemized deductions (Schedule A) with automatic standard-vs-itemized choice.
- Capital gains (Schedule D / 8949) and qualified-dividend rates; NIIT (8960);
  AMT (6251).
- EITC, Premium Tax Credit reconciliation (8962) for marketplace health plans.
- Multiple Schedule C businesses, spouse businesses (MFJ), Schedule E rentals.
- **State income tax** modules, starting with the largest states; sales-tax
  tracking for shopkeepers.
- Prior-year carryovers: QBI loss, net operating loss, home-office carryover.
- Annualized income installment method (Form 2210 Schedule AI) for seasonal
  businesses.

## AI

- Per-business category learning (few-shot examples from the user's own
  corrections, stored locally).
- Evaluation harness: golden datasets for extraction and classification, with
  accuracy tracked by prompt version (`PROMPT_VERSION`).
- Optional **local model** (e.g. via Ollama) for users who want zero data egress.
- Grounded Q&A over IRS publications (Pub 334, 535, 587, 463) with citations.

## Security & compliance

- Envelope encryption with KMS/HSM-held master keys and an automated key-rotation
  job (using the ciphertext version byte).
- Hash-chained audit log with periodic signed checkpoints.
- Field-level access logging for SSNs; automatic data-retention policies
  (e.g. purge documents after 7 years).
- Third-party penetration test; SOC 2 / IRS Pub 4557 safeguards review before
  any multi-tenant hosting.
- Content Security Policy and Trusted Types for the web build.

## Product

- Guided interview mode ("Did you buy any equipment this year?").
- Accountant-share links (time-limited, read-only) for users who want a review.
- Multi-language UI (Spanish first) for small-business owners.
- Offline-first mobile mode with encrypted local cache and sync.
- Hand-off exports to filing software (e.g. TXF / CSV mappings), while still not
  e-filing ourselves.
