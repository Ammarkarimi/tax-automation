# TaxPilot Mobile (Expo / React Native)

The pocket companion to the TaxPilot web app: snap receipts, review
auto-categorized transactions, check what you owe, and ask the assistant —
all against the same local FastAPI backend.

| Tab | What it does |
| --- | --- |
| **Home** | Profit, total tax, amount still due, next quarterly payment, audit-risk score, top deduction ideas |
| **Scan** | Camera / photo / PDF / CSV upload (encrypted server-side, read by AI or rules) |
| **Transactions** | "Needs review" queue — tap to recategorize or confirm |
| **Taxes** | Schedule C + Form 1040 summary, plain-English explanation, quarterly schedule |
| **Ask** | Assistant grounded in your own numbers |
| ⚙️ **Settings** | AI consent toggle, basic tax profile, sign out, delete account |

## Run it locally

```bash
cd mobile
npm install
cp .env.example .env.local      # set EXPO_PUBLIC_API_URL (see below)
npx expo start                  # press i (iOS simulator) / a (Android emulator), or scan the QR with Expo Go
```

`EXPO_PUBLIC_API_URL` must be reachable **from the device**:

| Where the app runs | URL |
| --- | --- |
| iOS simulator | `http://localhost:8000` |
| Android emulator | `http://10.0.2.2:8000` |
| Physical phone (same Wi-Fi) | `http://<your-computer-LAN-IP>:8000` — start the API with `uvicorn app.main:app --host 0.0.0.0` |

For encryption in transit on a real phone, serve the API over HTTPS using
`../scripts/gen-dev-cert.sh` (mkcert installs a CA you can trust on the device).

## Security notes

- Sign-in is password + 6-digit email code (same MFA as the web app).
- The refresh token is stored with **expo-secure-store** (Keychain / Keystore),
  `WHEN_UNLOCKED_THIS_DEVICE_ONLY`, so it is never synced to iCloud/backups;
  Android `allowBackup` is disabled. The access token only lives in memory.
- The client sends `X-Client-Type: mobile`; refresh tokens rotate on each use and
  reuse of an old token revokes the whole session family.
- `EXPO_PUBLIC_*` values are bundled into the app — never put secrets there.

## Checks

```bash
npx expo-doctor                                         # config & dependency health
npx expo export --platform android --output-dir /tmp/x  # verifies the JS bundle compiles
```

Project layout: routes live in `src/app/` (Expo Router), shared code in
`src/lib/` (API client, auth context) and `src/components/` (UI kit).
