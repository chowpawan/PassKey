"""Smoke test for the vault CRUD path.

We stub the WebAuthn ceremony (since it requires a real authenticator) by
inserting a User + Session row directly, then exercise the protected
endpoints with the signed session cookie.
"""

import base64
import os

# Set required env vars BEFORE importing the app modules.
os.environ.setdefault("VAULT_KEY", base64.b64encode(b"\x00" * 32).decode())
os.environ.setdefault("SESSION_SECRET", "test-secret-test-secret-test-secret-test")

import pytest
from httpx import ASGITransport, AsyncClient
from itsdangerous import URLSafeSerializer

from app.auth import COOKIE_NAME
from app.config import get_settings
from app.db import SessionLocal, init_db
from app.main import app
from app.models import Session as SessionRow
from app.models import User


async def _seed_user_and_session() -> tuple[str, str]:
    """Create a user + valid session row; return (username, cookie_token)."""
    from datetime import datetime, timedelta, timezone

    async with SessionLocal() as db:
        user = User(username="smoketest")
        db.add(user)
        await db.commit()
        await db.refresh(user)

        sess = SessionRow(
            user_id=user.id,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        db.add(sess)
        await db.commit()
        await db.refresh(sess)

    token = URLSafeSerializer(get_settings().session_secret, salt="passkey-session").dumps(sess.id)
    return user.username, token


@pytest.fixture(autouse=True)
async def _db():
    await init_db()
    yield
    # Wipe between tests
    from sqlalchemy import delete

    from app.models import Challenge, Credential, VaultEntry

    async with SessionLocal() as db:
        for table in (VaultEntry, Credential, Challenge, SessionRow, User):
            await db.execute(delete(table))
        await db.commit()


async def test_health():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/api/health")
        assert res.status_code == 200
        assert res.json() == {"status": "ok"}


async def test_vault_requires_auth():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/api/vault")
        assert res.status_code == 401


async def test_vault_crud_roundtrip():
    _, token = await _seed_user_and_session()
    cookies = {COOKIE_NAME: token}
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", cookies=cookies
    ) as client:
        # Create
        res = await client.post(
            "/api/vault",
            json={"label": "github.com", "username": "alice", "password": "hunter2"},
        )
        assert res.status_code == 201, res.text
        entry = res.json()
        assert entry["password"] == "hunter2"

        # List — password decrypted server-side
        res = await client.get("/api/vault")
        assert res.status_code == 200
        items = res.json()
        assert len(items) == 1
        assert items[0]["label"] == "github.com"
        assert items[0]["password"] == "hunter2"

        # Delete
        res = await client.delete(f"/api/vault/{entry['id']}")
        assert res.status_code == 204

        res = await client.get("/api/vault")
        assert res.json() == []


async def test_signout_clears_session():
    _, token = await _seed_user_and_session()
    cookies = {COOKIE_NAME: token}
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", cookies=cookies
    ) as client:
        res = await client.post("/api/vault/signout")
        assert res.status_code == 200

        # Cookie was used, but DB row is now deleted; the same token should now be invalid.
        # httpx persisted the original cookie though, so explicitly reuse it:
        res = await client.get("/api/vault", cookies={COOKIE_NAME: token})
        assert res.status_code == 401
