from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import Cookie, Depends, HTTPException, Response, status
from itsdangerous import BadSignature, URLSafeSerializer
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_session
from app.models import Session as SessionRow
from app.models import User

COOKIE_NAME = "passkey_session"


@dataclass(frozen=True)
class Principal:
    """Who is calling, and the session they're calling with.

    The vault guard needs both: the user to scope rows, and the session to judge how
    recently that user proved possession of their passkey.
    """

    user: User
    session: SessionRow


def as_utc(value: datetime) -> datetime:
    """SQLite drops tzinfo on round-trip; treat what comes back as UTC."""
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _serializer() -> URLSafeSerializer:
    return URLSafeSerializer(get_settings().session_secret, salt="passkey-session")


async def create_session(user_id: str, response: Response, db: AsyncSession) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(seconds=settings.session_ttl_seconds)
    # A fresh session was just created by a passkey ceremony, so it starts verified.
    row = SessionRow(user_id=user_id, expires_at=expires_at, last_verified_at=now)
    db.add(row)
    await db.commit()
    await db.refresh(row)

    token = _serializer().dumps(row.id)
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=settings.session_ttl_seconds,
        httponly=True,
        samesite=settings.cookie_samesite,
        secure=settings.secure_cookies,
        path="/",
    )
    return row.id


async def destroy_session(token: str | None, response: Response, db: AsyncSession) -> None:
    response.delete_cookie(COOKIE_NAME, path="/")
    if not token:
        return
    try:
        session_id = _serializer().loads(token)
    except BadSignature:
        return
    await db.execute(delete(SessionRow).where(SessionRow.id == session_id))
    await db.commit()


async def mark_verified(session_id: str, db: AsyncSession) -> None:
    """Record a fresh passkey assertion against an existing session (step-up)."""
    await db.execute(
        update(SessionRow)
        .where(SessionRow.id == session_id)
        .values(last_verified_at=datetime.now(timezone.utc))
    )
    await db.commit()


async def current_principal(
    passkey_session: str | None = Cookie(default=None, alias=COOKIE_NAME),
    db: AsyncSession = Depends(get_session),
) -> Principal:
    if not passkey_session:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "not signed in")
    try:
        session_id = _serializer().loads(passkey_session)
    except BadSignature as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "bad session") from exc

    row = (await db.execute(select(SessionRow).where(SessionRow.id == session_id))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "session expired")
    if as_utc(row.expires_at) < datetime.now(timezone.utc):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "session expired")

    user = (await db.execute(select(User).where(User.id == row.user_id))).scalar_one_or_none()
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "user gone")
    return Principal(user=user, session=row)


async def current_user(principal: Principal = Depends(current_principal)) -> User:
    return principal.user
