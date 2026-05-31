# PassKey

[![Live demo](https://img.shields.io/badge/live%20demo-pass--key--self.vercel.app-2ea44f?logo=vercel&logoColor=white)](https://pass-key-self.vercel.app)

A tiny password vault that you unlock with a passkey instead of a master password.

I built this to figure out how WebAuthn actually works. Reading the spec is one thing — getting Touch ID to talk to a FastAPI server and have everything line up is another. The pun is intentional: your *passkey* unlocks your *pass*words.

Live at https://pass-key-self.vercel.app if you just want to poke at it. Fair warning: the Render free tier sleeps the backend after 15 minutes of no traffic, so the first request after a quiet stretch takes ~30 seconds while it boots back up.

## What's in it

- FastAPI + SQLAlchemy (async) on the backend
- React + TypeScript + Vite on the frontend
- SQLite locally, Postgres in production
- `py_webauthn` for the server-side ceremony, `@simplewebauthn/browser` for the client
- AES-GCM for the actual password encryption

## Running it locally

You need Python 3.11+, Node 18+, and a device with some kind of authenticator (Mac Touch ID, Windows Hello, a phone, or a USB security key — anything the OS recognises as a passkey provider works).

Backend:

```
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env
# the .env file has the openssl one-liners for VAULT_KEY and SESSION_SECRET
uvicorn app.main:app --reload --port 8000
```

Frontend, in another terminal:

```
cd frontend
npm install
npm run dev
```

Open http://localhost:5173, pick a username, and your OS will pop the passkey prompt. After that you're in the vault.

Tests:

```
cd backend && pytest
```

The smoke tests don't drive the WebAuthn ceremony itself — there's no real authenticator inside pytest. They insert a user + session row directly and exercise the vault CRUD and signout paths, which is the part I actually wrote.

## How the pieces fit

```
React (5173) ──fetch──►  FastAPI (8000) ──►  SQLite / Postgres
              ◄────────  HttpOnly cookie
```

Registration and login each have a `/begin` and `/complete` endpoint. `/begin` generates a WebAuthn challenge, stashes it in a `challenges` row with a 5-minute TTL, and returns the options blob the browser needs. The browser hands that to `navigator.credentials.create` (register) or `.get` (login), the authenticator does its thing, and the result comes back to `/complete`. The server verifies it via `py_webauthn` — for registration it stores the public key, for login it bumps the sign counter — and sets a signed HttpOnly session cookie. From then on the vault routes are gated on that cookie.

The vault is plain CRUD with one wrinkle: `POST /api/vault` AES-GCM-encrypts the password before saving, `GET /api/vault` decrypts on the way out. The key lives in the `VAULT_KEY` env var on the server. That's a deliberate shortcut — see below.

## What I cut

The biggest one: the server holds the vault encryption key. That works, but it means anyone with server access can read every vault. The proper fix is the **WebAuthn PRF extension**, where the authenticator derives a per-user secret inside its secure enclave and the server never sees the plaintext key. That's the most interesting thing I'd add next and I left it for v2.

The rest:

- one passkey per account; no UI to add a second device or revoke a lost one
- no discoverable credentials, so you still type a username before authenticating
- no recovery — if you lose the passkey, the vault is gone
- the vault list endpoint decrypts every row server-side, which is fine for a demo but obviously not what you'd ship

## Deploying it yourself

Frontend on Vercel, backend on Render with a managed Postgres. The repo's `render.yaml` is a Render Blueprint, so the web service and the database get created together.

The order matters because WebAuthn binds credentials to a specific domain:

1. **Render → New Blueprint** → pick this repo. It'll ask for `RP_ID` and `EXPECTED_ORIGIN` — leave both as placeholders (literally anything) for now, you can't know them yet. The first deploy will fail health checks. That's fine. Note the URL Render assigns the API.
2. **Vercel → import this repo** → set root directory to `frontend` → add an env var `VITE_API_URL` pointing at the Render API URL. Deploy. Note the Vercel URL.
3. **Back to Render** → set `RP_ID` to the Vercel hostname (no `https://`) and `EXPECTED_ORIGIN` to the full URL with `https://`. Redeploy.

A passkey you registered on `localhost` will not work on `*.vercel.app` and vice versa — the RP ID is part of the credential, so they live in separate namespaces. You re-register on each environment.

If anything weird happens, it's almost always one of:

- `RP_ID` doesn't exactly match the frontend hostname
- `EXPECTED_ORIGIN` has a trailing slash or is `http://` instead of `https://`
- the browser is holding onto an old JS bundle (hard refresh: ⌘⇧R)

## Why bother

Mostly I wanted to stop hand-waving about WebAuthn. The material online tends to be either "install this npm package and you're done" or a 4000-word breakdown of CBOR encoding, with not a lot in between. Wiring up the full ceremony end-to-end was the only way I was going to actually understand what the browser, the authenticator, and the server each do during a registration or login.

The vault on top is mostly so the passkey has something to *protect*. It'd feel weird to demo "log in with Touch ID!" and dump you on an empty page.
