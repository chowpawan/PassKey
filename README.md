# PassKey

A small password manager that unlocks with a WebAuthn passkey (Touch ID, Face ID,
Windows Hello, or a security key) instead of a master password.

Built as a learning project to explore two pieces of tech end-to-end:

1. **WebAuthn / FIDO2** — the browser API behind "Sign in with passkey"
2. **Encrypted vault storage** — AES-GCM on top of SQLite

Stack: **FastAPI** (Python 3.11+), **React + TypeScript** (Vite), **SQLite**.

---

## Running locally

You need Python ≥ 3.11, Node ≥ 18, and a device with a platform authenticator
(macOS / iOS / Windows Hello / Android) or a USB security key.

### Backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

cp .env.example .env
# fill VAULT_KEY  (openssl rand -base64 32)
# fill SESSION_SECRET  (openssl rand -hex 32)

uvicorn app.main:app --reload --port 8000
```

### Frontend

In another terminal:

```bash
cd frontend
npm install
npm run dev          # http://localhost:5173
```

The Vite dev server proxies `/api` → `http://localhost:8000` so the browser sees
one origin (important — WebAuthn binds credentials to the origin and RP ID).

---

## Manual verification

The WebAuthn ceremony can only be exercised end-to-end with a real
authenticator, so the happy path is a manual test:

1. Open `http://localhost:5173/register`, type a username, click
   **Create passkey** → your OS prompts for Touch ID / Face ID / etc.
2. You should land on `/vault`.
3. Add a vault entry (e.g. `github.com / alice / hunter2`) → it appears in the list.
4. Click **Sign out** to clear the session cookie.
5. Go to `/login`, enter the same username, authenticate → you're back at the vault
   and the entry persists.
6. Reload the page — entry still there.
7. Delete the entry → gone after refresh.

### Automated tests

Server-side smoke tests (vault CRUD + session handling) bypass the WebAuthn
ceremony by inserting a User + Session row directly, since `navigator.credentials`
can't run inside pytest:

```bash
cd backend && pytest
```

---

## Project layout

```
PassKey/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI app entry
│   │   ├── config.py            # pydantic-settings
│   │   ├── db.py                # SQLAlchemy async engine
│   │   ├── models.py            # User, Credential, VaultEntry, Challenge, Session
│   │   ├── schemas.py           # Pydantic request/response models
│   │   ├── auth.py              # signed-cookie sessions + current_user dep
│   │   ├── crypto.py            # AES-GCM wrapper
│   │   ├── webauthn_helpers.py  # wraps py_webauthn
│   │   └── routes/
│   │       ├── webauthn.py      # /api/webauthn/{register,login}/{begin,complete}
│   │       └── vault.py         # /api/vault GET/POST/DELETE + /whoami /signout
│   └── tests/test_smoke.py
└── frontend/
    └── src/
        ├── api.ts               # fetch wrappers
        ├── webauthn.ts          # @simplewebauthn/browser glue
        ├── App.tsx              # routing + auth bootstrap
        ├── pages/{Register,Login,Vault}.tsx
        └── components/VaultEntryForm.tsx
```

---

## Architecture notes

```
┌───────────────────────┐    HTTPS (proxied)    ┌────────────────────────┐
│  React + Vite (5173)  │ ─────────────────────►│  FastAPI (8000)        │
│  @simplewebauthn/     │                       │  py_webauthn (verify)  │
│   browser             │                       │  AES-GCM (cryptography)│
│  vault UI             │ ◄─────────────────────│  signed-cookie session │
└───────────────────────┘   HttpOnly cookie     └───────────┬────────────┘
                                                            │ SQLAlchemy
                                                            ▼
                                                ┌──────────────────────┐
                                                │  SQLite (passkey.db) │
                                                └──────────────────────┘
```

- **RP ID** = `localhost`, **expected origin** = `http://localhost:5173`.
- **WebAuthn challenges** are stored in the `challenges` table and consumed on
  completion — single-use, 5-minute TTL.
- **Sessions** are server-side rows; the cookie holds only a signed session ID
  (using `itsdangerous`). Cookie is `HttpOnly`, `SameSite=Lax`, 24h TTL.
- **Vault encryption (MVP):** AES-GCM with a server-held key from `VAULT_KEY`.
  Passwords are encrypted on insert and decrypted on read. The passkey controls
  *access* via the session cookie; the encryption key sits server-side.

### Known MVP simplifications (intentional)

| Today | Intended next step |
|---|---|
| Server-held vault key | WebAuthn **PRF extension** — the authenticator derives a per-user secret inside the secure enclave; server never sees plaintext keys. True end-to-end encryption. |
| One passkey per user | Multi-device passkeys + a management UI to list/revoke |
| Username field on login | Discoverable credentials / username-less login (`allowCredentials: []`) |
| No recovery | Recovery codes or a second factor |
| HTTP localhost only | HTTPS + proper RP ID for a public deployment |

---

## Deploying (Vercel + Render)

The two halves go to different providers because WebAuthn + SQLite + a static
SPA each prefer a different runtime.

### 1. Push to GitHub (already done if you cloned this repo)

### 2. Backend → Render (Blueprint)

1. In the Render dashboard: **New + → Blueprint** → select this repo.
2. Render reads `render.yaml` in the repo root and proposes a `passkey-api`
   web service + a free `passkey-db` Postgres database. Apply.
3. The first deploy will fail health-check because `RP_ID` and
   `EXPECTED_ORIGIN` are blank — they depend on the frontend URL, which
   doesn't exist yet. Continue to step 3 and come back to fill them in.
4. Note the backend URL Render assigns you (e.g.
   `https://passkey-api.onrender.com`).

### 3. Frontend → Vercel

1. In Vercel: **Add New → Project** → import this repo.
2. **Root directory:** `frontend`.
3. Vercel auto-detects Vite. Leave build/output settings as-is
   (`vercel.json` already specifies them).
4. **Environment Variables** → add:
   - `VITE_API_URL` = your Render backend URL from step 2.4 (no trailing slash).
5. Deploy. Note the URL Vercel assigns (e.g.
   `https://passkey-xyz.vercel.app`).

### 4. Back to Render — fill in the WebAuthn vars

In the Render `passkey-api` service → **Environment** → set:

| Key | Value |
|---|---|
| `RP_ID` | `passkey-xyz.vercel.app` *(hostname only, no scheme)* |
| `EXPECTED_ORIGIN` | `https://passkey-xyz.vercel.app` |

Trigger a redeploy. Once it's healthy you can register a passkey from the
Vercel URL.

### Caveats

- **WebAuthn credentials are domain-bound.** A passkey you registered on
  `localhost` will not work on `*.vercel.app`, and vice versa. Each domain
  needs its own registration.
- **Render free tier sleeps after 15 min idle.** First request after sleep
  takes ~30s. Upgrade or use Fly.io if you need always-on.
- **Custom domain:** if you put both halves behind one domain
  (`app.example.com` + `app.example.com/api/*` via a reverse proxy), you can
  set `COOKIE_SAMESITE=lax` and `SECURE_COOKIES=true` and skip the
  cross-origin cookie dance entirely.

---
