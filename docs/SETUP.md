# Local Setup

Everything runs on your own machine. You need:

* Python 3.11+
* Node.js 20+ (22 recommended)
* PostgreSQL 14+ — either Docker (`docker compose`) or a local install
* *(optional)* an OpenAI API key; without one, every AI feature falls back to
  built-in rules
* *(mobile, optional)* Xcode / Android Studio emulators, or the Expo Go app

## 1. Database and mail inbox

**Option A — Docker (recommended)**

```bash
docker compose up -d          # Postgres on 127.0.0.1:5432 (schema auto-applied) + Mailpit on :8025
```

**Option B — local PostgreSQL**

```bash
createuser -P taxpilot        # password: taxpilot (or your own)
createdb -O taxpilot taxpilot
psql -U taxpilot -d taxpilot -f docs/schema.sql
```

(The backend also creates any missing tables on startup, but `schema.sql` adds
CHECK constraints and the append-only audit-log trigger.)

## 2. Backend (FastAPI)

```bash
cd backend
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt

cp .env.example .env
python scripts/generate_secrets.py                       # paste the 3 values into .env
# Optional AI:   OPENAI_API_KEY=sk-...   (OPENAI_MODEL defaults to gpt-4o-mini)
# Optional mail: EMAIL_BACKEND=smtp  (Mailpit: SMTP_HOST=localhost SMTP_PORT=1025)

uvicorn app.main:app --reload --port 8000
```

* API docs: <http://localhost:8000/docs>
* Health: <http://localhost:8000/health>
* With `EMAIL_BACKEND=console`, sign-in codes are printed in this terminal.
  With Mailpit, open <http://localhost:8025>.

Create a demo shopkeeper with a year of sample bank data:

```bash
python scripts/seed_demo.py      # demo@example.com / DemoShop2025!
```

Create an admin: set `BOOTSTRAP_ADMIN_EMAIL` / `BOOTSTRAP_ADMIN_PASSWORD` in
`.env` and restart (or promote a user in the Admin panel).

### Tests

```bash
pytest -q                                                   # SQLite, no network
TEST_DATABASE_URL=postgresql+psycopg://taxpilot:taxpilot@localhost:5432/taxpilot_test pytest -q
```

## 3. Web app (React + Tailwind)

```bash
cd frontend
npm install
npm run dev                      # http://localhost:5173 (proxies /api to :8000)
```

Set `VITE_API_TARGET` if the API isn't on `http://localhost:8000`.

## 4. Mobile app (Expo)

```bash
cd mobile
npm install
cp .env.example .env.local       # EXPO_PUBLIC_API_URL — see mobile/README.md
npx expo start                   # i = iOS simulator, a = Android emulator, or scan the QR in Expo Go
```

For a physical phone, start the API with `--host 0.0.0.0`, use your computer's
LAN IP, and add the app's origin to `CORS_ORIGINS` if you test the web build.

## 5. HTTPS locally (encryption in transit)

```bash
./scripts/gen-dev-cert.sh        # writes certs/dev-key.pem + dev-cert.pem (git-ignored)

cd backend
uvicorn app.main:app --port 8000 \
  --ssl-keyfile ../certs/dev-key.pem --ssl-certfile ../certs/dev-cert.pem
# in .env: COOKIE_SECURE=true, CORS_ORIGINS=https://localhost:5173

cd ../frontend
VITE_API_TARGET=https://localhost:8000 npm run dev      # Vite serves https automatically when certs exist
```

## 6. Using the app (shopkeeper walkthrough)

1. **Register** → enter the emailed code.
2. **Tax Profile** → filing status, what the shop sells, the 6-digit NAICS code,
   stock value on Jan 1 / Dec 31, business miles, and whether you take a lot of cash.
3. **Documents** → upload the bank statement CSV (and card-processor 1099-K, any
   1099-NEC, W-2). Confirm the extracted amounts.
4. **Transactions** → clear the "Needs review" queue; set business-use % for
   mixed items such as your phone.
5. **Settings** → optionally turn on AI processing for photo receipts and smarter categories.
6. **Deductions / Audit Risk** → act on the suggestions and fix any red flags.
7. **Annual Return** → *Explain my taxes*, then **Download return PDF** and
   transcribe it into the official forms or filing software.
8. **Quarterly Estimates** → pay the suggested installment by each due date
   (IRS Direct Pay / EFTPS) and record it.

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `secret still has its placeholder value` on startup | Run `scripts/generate_secrets.py` and update `.env`. |
| `DATA_ENCRYPTION_KEY must decode to exactly 32 bytes` | Use the generated value as-is (urlsafe base64). |
| Login works but no code arrives | `EMAIL_BACKEND=console` prints it in the backend terminal; for SMTP check Mailpit. |
| 429 Too Many Requests | Auth rate limit — wait 5 minutes (or restart the dev server). |
| Mobile: "Can't reach the server" | Check `EXPO_PUBLIC_API_URL` for your emulator/device (see `mobile/README.md`). |
| AI buttons say "standard explanation" | Set `OPENAI_API_KEY` **and** turn on AI processing in Settings. |
| Losing the encryption key | Encrypted data can't be recovered — back up `.env` secrets securely. |
