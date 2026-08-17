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

The smoke tests don't drive the WebAuthn ceremony itself — there's no real authenticator inside pytest. They insert a user + session row directly and exercise the vault CRUD and signout paths, which is the part I actually wrote. The authorization tests work the same way: seeding a user with `role="viewer"`, or a session with a backdated `last_verified_at`, is enough to make the guard deny — so I can assert on the 403 *and* on the `audit_log` row without a fingerprint anywhere.

## How the pieces fit

```
React (5173) ──fetch──►  FastAPI (8000) ──►  SQLite / Postgres
              ◄────────  HttpOnly cookie
```

Registration and login each have a `/begin` and `/complete` endpoint. `/begin` generates a WebAuthn challenge, stashes it in a `challenges` row with a 5-minute TTL, and returns the options blob the browser needs. The browser hands that to `navigator.credentials.create` (register) or `.get` (login), the authenticator does its thing, and the result comes back to `/complete`. The server verifies it via `py_webauthn` — for registration it stores the public key, for login it bumps the sign counter — and sets a signed HttpOnly session cookie. From then on the vault routes are gated on that cookie.

The vault is plain CRUD with one wrinkle: `POST /api/vault` AES-GCM-encrypts the password before saving, `GET /api/vault` decrypts on the way out. The key lives in the `VAULT_KEY` env var on the server. That's a deliberate shortcut — see below.

### Signed in ≠ allowed

Being signed in is one question. Whether you may do a particular thing is two more, and `app/authz.py` asks both before any route touches `vault_entries`:

1. **Does your role grant the action?** Two roles. `owner` may list, create, and delete; `viewer` may only list. That's a `role` column on `users` and a dict in code, not a permissions table — with two roles and three actions, a table would be ceremony.
2. **Is your passkey assertion recent enough?** The session cookie lasts 24 hours, which is fine for knowing *who* you are and terrible as standing permission to read every password you own. Sessions carry `last_verified_at` alongside `expires_at`, and the vault wants one from the last `STEP_UP_TTL_SECONDS` (5 minutes by default).

`require_permission("vault:delete")` composes with the existing cookie check rather than replacing it — it depends on the same `current_principal`, so the session still resolves and still 401s on its own terms, and the role check sits on top. Routes swapped one dependency; the auth flow didn't change.

Permission is checked first, deliberately. A viewer can't delete however fresh their assertion is, so answering "re-verify with your passkey" would be a lie. Two codes come back so the client can tell them apart: `permission_denied` (don't offer a retry) and `reverification_required` (do — the frontend swaps the entry list for an *Unlock with passkey* button, which runs `/api/webauthn/reverify/{begin,complete}`: an ordinary assertion that refreshes the existing session instead of minting a new one, same cookie, same row, new clock).

The part I care about is that deciding and recording are the same code path. The guard writes an `audit_log` row — allow *and* deny, with the role as it was at decision time, the action, the result, the reason, and how stale the session was — before it either returns or raises. There's no separate "oh and log the failure too" branch sitting next to the `raise`, because that's exactly the branch that rots the first time someone adds a route and forgets it.

There's no migration tool here, so `init_db()` does a small additive-column pass after `create_all()`. It handles a new column only when existing rows can be given a value — nullable, or carrying a `server_default`. `role` has `server_default="owner"`, so accounts that predate it keep working. `last_verified_at` deliberately has neither, so a session that never completed a ceremony reads `NULL` and is denied rather than treated as fresh. Fail closed. (I had that backwards at first — the model default was quietly making never-verified sessions look brand new, and a test caught it.)

What this doesn't do: roles are assigned in the database by hand, since there's no admin UI and no invite flow. `audit_log` has no retention policy and grows one row per vault request. It's append-only by convention, not enforcement — no hash chaining, nothing that would survive someone with write access to the database. And it covers authorization decisions on the vault routes only, not logins, registrations, or session lifecycle.

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
