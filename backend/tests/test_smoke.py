"""Smoke test for the vault CRUD path.

We stub the WebAuthn ceremony (since it requires a real authenticator) by
inserting a User + Session row directly, then exercise the protected
endpoints with the signed session cookie.

Env setup (including the throwaway DB_URL these fixtures truncate) lives in
conftest.py, which pytest loads before this module is imported.
"""

import pytest
from httpx import ASGITransport, AsyncClient
from itsdangerous import URLSafeSerializer

from app.auth import COOKIE_NAME
from app.config import get_settings
from app.db import SessionLocal, init_db
from app.main import app
from app.models import Session as SessionRow
from app.models import User


async def _seed_user_and_session(verified_ago_seconds: int = 0) -> tuple[str, str]:
    """Create a user + valid session row; return (username, cookie_token).

    `verified_ago_seconds` backdates the last passkey assertion so the step-up guard
    in app.authz can be exercised without a real authenticator. Pass None to model a
    session row written before last_verified_at existed.
    """
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    async with SessionLocal() as db:
        user = User(username="smoketest")
        db.add(user)
        await db.commit()
        await db.refresh(user)

        sess = SessionRow(
            user_id=user.id,
            expires_at=now + timedelta(hours=1),
            last_verified_at=(
                None if verified_ago_seconds is None
                else now - timedelta(seconds=verified_ago_seconds)
            ),
        )
        db.add(sess)
        await db.commit()
        await db.refresh(sess)

    token = URLSafeSerializer(get_settings().session_secret, salt="passkey-session").dumps(sess.id)
    return user.username, token


async def _access_log() -> list[tuple[str, str, str | None]]:
    """Every recorded decision, oldest first, as (action, decision, reason)."""
    from sqlalchemy import select

    from app.models import AccessLog

    async with SessionLocal() as db:
        rows = (
            await db.execute(select(AccessLog).order_by(AccessLog.created_at))
        ).scalars().all()
    return [(r.action, r.decision, r.reason) for r in rows]


@pytest.fixture(autouse=True)
async def _db():
    await init_db()
    yield
    # Wipe between tests
    from sqlalchemy import delete

    from app.models import AccessLog, Challenge, Credential, VaultEntry

    async with SessionLocal() as db:
        for table in (AccessLog, VaultEntry, Credential, Challenge, SessionRow, User):
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


# --- Step-up verification (app.authz) -------------------------------------------------

STALE = get_settings().step_up_ttl_seconds + 60


async def test_fresh_session_is_allowed_and_recorded():
    _, token = await _seed_user_and_session(verified_ago_seconds=0)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", cookies={COOKIE_NAME: token}
    ) as client:
        res = await client.get("/api/vault")
        assert res.status_code == 200

    # Allows are recorded too, not just denials.
    assert await _access_log() == [("vault:list", "allow", None)]


async def test_stale_session_gets_403_with_reverification_code():
    _, token = await _seed_user_and_session(verified_ago_seconds=STALE)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", cookies={COOKIE_NAME: token}
    ) as client:
        res = await client.get("/api/vault")

    assert res.status_code == 403
    assert res.json()["detail"]["code"] == "reverification_required"


async def test_denial_is_recorded_without_a_separate_logging_call():
    """The 403 and its access_log row come from the same code path in the guard."""
    _, token = await _seed_user_and_session(verified_ago_seconds=STALE)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", cookies={COOKIE_NAME: token}
    ) as client:
        assert (await client.get("/api/vault")).status_code == 403
        assert (await client.delete("/api/vault/does-not-matter")).status_code == 403

    assert await _access_log() == [
        ("vault:list", "deny", "stale_verification"),
        ("vault:delete", "deny", "stale_verification"),
    ]


async def test_denied_write_never_touches_vault_entries():
    from sqlalchemy import func, select

    from app.models import VaultEntry

    _, token = await _seed_user_and_session(verified_ago_seconds=STALE)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", cookies={COOKIE_NAME: token}
    ) as client:
        res = await client.post(
            "/api/vault",
            json={"label": "github.com", "username": "alice", "password": "hunter2"},
        )
        assert res.status_code == 403

    async with SessionLocal() as db:
        count = (await db.execute(select(func.count()).select_from(VaultEntry))).scalar_one()
    assert count == 0


async def test_session_predating_the_column_is_denied():
    """A session row with no last_verified_at reads as never verified, not as fresh."""
    _, token = await _seed_user_and_session(verified_ago_seconds=None)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", cookies={COOKIE_NAME: token}
    ) as client:
        res = await client.get("/api/vault")

    assert res.status_code == 403
    assert await _access_log() == [("vault:list", "deny", "stale_verification")]


async def test_whoami_and_signout_are_not_step_up_gated():
    """Identity and sign-out must work while the vault itself is locked."""
    username, token = await _seed_user_and_session(verified_ago_seconds=STALE)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", cookies={COOKIE_NAME: token}
    ) as client:
        res = await client.get("/api/vault/whoami")
        assert res.status_code == 200
        assert res.json()["username"] == username

        assert (await client.post("/api/vault/signout")).status_code == 200

    assert await _access_log() == []


async def test_unauthenticated_request_is_401_and_logs_nothing():
    """No session means no principal to attribute a decision to — 401 before the guard."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get("/api/vault")).status_code == 401
    assert await _access_log() == []


async def test_marking_verified_unlocks_the_same_session():
    """What reverify/complete does on a successful assertion, without an authenticator."""
    from itsdangerous import URLSafeSerializer as _S

    from app.auth import mark_verified

    _, token = await _seed_user_and_session(verified_ago_seconds=STALE)
    session_id = _S(get_settings().session_secret, salt="passkey-session").loads(token)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", cookies={COOKIE_NAME: token}
    ) as client:
        assert (await client.get("/api/vault")).status_code == 403

        async with SessionLocal() as db:
            await mark_verified(session_id, db)

        # Same cookie, same session row — no re-login required.
        assert (await client.get("/api/vault")).status_code == 200

    assert await _access_log() == [
        ("vault:list", "deny", "stale_verification"),
        ("vault:list", "allow", None),
    ]


async def test_reverify_begin_requires_a_session():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.post("/api/webauthn/reverify/begin")).status_code == 401
