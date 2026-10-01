-- =============================================================================
-- TaxPilot — PostgreSQL schema (PostgreSQL 14+)
--
-- Apply with:   psql "$DATABASE_URL_PSQL" -f docs/schema.sql
-- The backend can also create these tables itself on first start (SQLAlchemy
-- create_all), but this file is the reference DDL: it adds CHECK constraints,
-- comments and the append-only trigger on audit_logs.
--
-- Encryption: columns marked [ENC] hold application-level AES-256-GCM
-- ciphertext (base64). The database never sees those values in plaintext.
-- =============================================================================

BEGIN;

-- ---------------------------------------------------------------------------
-- Users & authentication
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
    id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email                 VARCHAR(320) NOT NULL UNIQUE,         -- stored lower-case
    password_hash         VARCHAR(255) NOT NULL,                -- Argon2id
    full_name             TEXT,                                 -- [ENC]
    role                  VARCHAR(16)  NOT NULL DEFAULT 'user'
                          CHECK (role IN ('user', 'support', 'admin')),
    is_active             BOOLEAN      NOT NULL DEFAULT TRUE,
    email_verified        BOOLEAN      NOT NULL DEFAULT FALSE,
    failed_login_attempts INTEGER      NOT NULL DEFAULT 0,
    locked_until          TIMESTAMPTZ,
    last_login_at         TIMESTAMPTZ,
    ai_consent            BOOLEAN      NOT NULL DEFAULT FALSE,  -- opt-in before data goes to OpenAI
    created_at            TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at            TIMESTAMPTZ  NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_users_email ON users (email);

CREATE TABLE IF NOT EXISTS otp_codes (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id      UUID        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    code_hash    VARCHAR(64) NOT NULL,                -- HMAC-SHA256(challenge_id:code)
    purpose      VARCHAR(16) NOT NULL CHECK (purpose IN ('login', 'verify_email')),
    challenge_id VARCHAR(64) NOT NULL,                -- ties the code to one MFA token
    attempts     INTEGER     NOT NULL DEFAULT 0,
    expires_at   TIMESTAMPTZ NOT NULL,
    consumed_at  TIMESTAMPTZ,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_otp_codes_user_id ON otp_codes (user_id);
CREATE INDEX IF NOT EXISTS ix_otp_codes_challenge_id ON otp_codes (challenge_id);

CREATE TABLE IF NOT EXISTS refresh_tokens (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash  VARCHAR(64) NOT NULL UNIQUE,          -- HMAC-SHA256 of the opaque token
    family_id   UUID        NOT NULL,                 -- rotation family (reuse => revoke all)
    expires_at  TIMESTAMPTZ NOT NULL,
    revoked_at  TIMESTAMPTZ,
    replaced_by UUID,
    user_agent  VARCHAR(255),
    ip_address  VARCHAR(64),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_refresh_tokens_user_id ON refresh_tokens (user_id);
CREATE INDEX IF NOT EXISTS ix_refresh_tokens_family_id ON refresh_tokens (family_id);

-- ---------------------------------------------------------------------------
-- Tax profile (one per user per tax year)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS tax_profiles (
    id                     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id                UUID    NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    tax_year               INTEGER NOT NULL CHECK (tax_year BETWEEN 2020 AND 2100),
    filing_status          VARCHAR(24) NOT NULL DEFAULT 'single'
                           CHECK (filing_status IN ('single', 'married_joint', 'married_separate', 'head_of_household')),
    taxpayer_name          TEXT,                       -- [ENC]
    ssn                    TEXT,                       -- [ENC]
    address                TEXT,                       -- [ENC]
    business_name          VARCHAR(200),
    business_description   VARCHAR(200),
    business_code          VARCHAR(6),                 -- NAICS principal business code
    is_cash_intensive      BOOLEAN NOT NULL DEFAULT FALSE,
    is_sstb                BOOLEAN NOT NULL DEFAULT FALSE,
    age_65_or_older        BOOLEAN NOT NULL DEFAULT FALSE,
    spouse_age_65_or_older BOOLEAN NOT NULL DEFAULT FALSE,
    qualifying_children    INTEGER NOT NULL DEFAULT 0 CHECK (qualifying_children >= 0),
    other_dependents       INTEGER NOT NULL DEFAULT 0 CHECK (other_dependents >= 0),
    home_office_sqft       INTEGER NOT NULL DEFAULT 0 CHECK (home_office_sqft >= 0),
    business_miles         INTEGER NOT NULL DEFAULT 0 CHECK (business_miles >= 0),
    beginning_inventory    NUMERIC(14,2) NOT NULL DEFAULT 0,
    ending_inventory       NUMERIC(14,2) NOT NULL DEFAULT 0,
    qualified_tips         NUMERIC(14,2) NOT NULL DEFAULT 0,
    other_income           NUMERIC(14,2) NOT NULL DEFAULT 0,
    prior_year_tax         NUMERIC(14,2),
    prior_year_agi         NUMERIC(14,2),
    created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_profile_user_year UNIQUE (user_id, tax_year)
);
CREATE INDEX IF NOT EXISTS ix_tax_profiles_user_id ON tax_profiles (user_id);

-- ---------------------------------------------------------------------------
-- Documents (file bytes live encrypted on disk under storage_key)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS documents (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id           UUID         NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    tax_year          INTEGER      NOT NULL,
    original_filename TEXT         NOT NULL,          -- [ENC]
    content_type      VARCHAR(100) NOT NULL,
    size_bytes        INTEGER      NOT NULL CHECK (size_bytes > 0),
    sha256            VARCHAR(64)  NOT NULL,          -- plaintext hash, for de-duplication
    storage_key       VARCHAR(128) NOT NULL,          -- random; no PII in paths
    doc_type          VARCHAR(24)  NOT NULL DEFAULT 'other'
                      CHECK (doc_type IN ('w2','1099_nec','1099_misc','1099_k','1099_int','1099_div',
                                          'invoice','receipt','bank_csv','other')),
    status            VARCHAR(16)  NOT NULL DEFAULT 'uploaded'
                      CHECK (status IN ('uploaded', 'processing', 'processed', 'failed')),
    extracted_data    TEXT,                           -- [ENC] JSON
    error             VARCHAR(500),
    processed_at      TIMESTAMPTZ,
    created_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ  NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_documents_user_id ON documents (user_id);
CREATE INDEX IF NOT EXISTS ix_documents_user_sha ON documents (user_id, sha256);

-- ---------------------------------------------------------------------------
-- W-2 / 1099 data (AI-extracted or entered manually)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS income_forms (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    document_id UUID        REFERENCES documents(id) ON DELETE SET NULL,
    tax_year    INTEGER     NOT NULL,
    form_type   VARCHAR(24) NOT NULL
                CHECK (form_type IN ('w2','1099_nec','1099_misc','1099_k','1099_int','1099_div')),
    payer_name  VARCHAR(200),
    amounts     JSON        NOT NULL DEFAULT '{}',   -- {"nonemployee_compensation": 8450.0, ...}
    confirmed   BOOLEAN     NOT NULL DEFAULT FALSE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_income_forms_user_id ON income_forms (user_id);

-- ---------------------------------------------------------------------------
-- Transactions (income & expenses)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS transactions (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id          UUID          NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    document_id      UUID          REFERENCES documents(id) ON DELETE SET NULL,
    tax_year         INTEGER       NOT NULL,
    txn_date         DATE          NOT NULL,
    description      TEXT          NOT NULL,          -- [ENC]
    merchant         VARCHAR(200),
    amount           NUMERIC(14,2) NOT NULL CHECK (amount > 0),
    direction        VARCHAR(8)    NOT NULL DEFAULT 'expense' CHECK (direction IN ('income', 'expense')),
    category         VARCHAR(32)   NOT NULL DEFAULT 'uncategorized',   -- see app/models/enums.py
    business_use_pct INTEGER       NOT NULL DEFAULT 100 CHECK (business_use_pct BETWEEN 0 AND 100),
    confidence       DOUBLE PRECISION CHECK (confidence IS NULL OR confidence BETWEEN 0 AND 1),
    classified_by    VARCHAR(8)    NOT NULL DEFAULT 'import' CHECK (classified_by IN ('ai','rules','user','import')),
    ai_rationale     VARCHAR(500),
    needs_review     BOOLEAN       NOT NULL DEFAULT TRUE,
    notes            TEXT,                            -- [ENC]
    created_at       TIMESTAMPTZ   NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ   NOT NULL DEFAULT now(),
    CONSTRAINT ck_txn_year CHECK (EXTRACT(YEAR FROM txn_date) = tax_year)
);
CREATE INDEX IF NOT EXISTS ix_tx_user_year ON transactions (user_id, tax_year);
CREATE INDEX IF NOT EXISTS ix_tx_user_review ON transactions (user_id, tax_year) WHERE needs_review;

CREATE TABLE IF NOT EXISTS estimated_payments (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id    UUID          NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    tax_year   INTEGER       NOT NULL,
    quarter    INTEGER       NOT NULL CHECK (quarter BETWEEN 1 AND 4),
    amount     NUMERIC(14,2) NOT NULL CHECK (amount > 0),
    paid_on    DATE          NOT NULL,
    created_at TIMESTAMPTZ   NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ   NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_estimated_payments_user_id ON estimated_payments (user_id);

-- ---------------------------------------------------------------------------
-- Calculation snapshots & generated reports
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS tax_calculations (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id        UUID        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    tax_year       INTEGER     NOT NULL,
    kind           VARCHAR(16) NOT NULL CHECK (kind IN ('annual', 'quarterly')),
    engine_version VARCHAR(16) NOT NULL,
    result         TEXT        NOT NULL,              -- [ENC] JSON
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_tax_calculations_user_id ON tax_calculations (user_id);

CREATE TABLE IF NOT EXISTS generated_reports (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID         NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    tax_year    INTEGER      NOT NULL,
    kind        VARCHAR(32)  NOT NULL,
    storage_key VARCHAR(128) NOT NULL,
    sha256      VARCHAR(64)  NOT NULL,                -- integrity check of the generated PDF
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_generated_reports_user_id ON generated_reports (user_id);

-- ---------------------------------------------------------------------------
-- Audit trail (append-only; no PII — ids and safe metadata only)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS audit_logs (
    id            SERIAL PRIMARY KEY,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    actor_id      UUID,                 -- no FK: entries must survive account deletion
    actor_role    VARCHAR(16),
    action        VARCHAR(64) NOT NULL, -- e.g. auth.login, document.uploaded, admin.user_updated
    resource_type VARCHAR(32),
    resource_id   VARCHAR(64),
    success       BOOLEAN     NOT NULL DEFAULT TRUE,
    ip_address    VARCHAR(64),
    user_agent    VARCHAR(255),
    request_id    VARCHAR(64),
    details       JSON
);
CREATE INDEX IF NOT EXISTS ix_audit_logs_created_at ON audit_logs (created_at);
CREATE INDEX IF NOT EXISTS ix_audit_logs_actor_id ON audit_logs (actor_id);
CREATE INDEX IF NOT EXISTS ix_audit_logs_action ON audit_logs (action);

-- Make the audit log tamper-resistant from the application role.
CREATE OR REPLACE FUNCTION audit_logs_block_changes() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'audit_logs is append-only';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_audit_logs_append_only ON audit_logs;
CREATE TRIGGER trg_audit_logs_append_only
    BEFORE UPDATE OR DELETE ON audit_logs
    FOR EACH ROW EXECUTE FUNCTION audit_logs_block_changes();

COMMENT ON TABLE audit_logs IS 'Append-only security/audit trail. Contains no raw PII.';
COMMENT ON COLUMN transactions.description IS 'AES-256-GCM ciphertext (application-level encryption)';
COMMENT ON COLUMN tax_profiles.ssn IS 'AES-256-GCM ciphertext (application-level encryption)';

COMMIT;
