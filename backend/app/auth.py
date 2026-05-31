from datetime import datetime, timedelta, timezone

from fastapi import Cookie, Depends, HTTPException, Response, status
from itsdangerous import BadSignature, URLSafeSerializer
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_session
from app.models import Session as SessionRow
from app.models import User

COOKIE_NAME = "passkey_session"


def _serializer() -> URLSafeSerializer:
    return URLSafeSerializer(get_settings().session_secret, salt="passkey-session")


async def create_session(user_id: str, response: Response, db: AsyncSession) -> str:
    settings = get_settings()
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=settings.session_ttl_seconds)
    row = SessionRow(user_id=user_id, expires_at=expires_at)
    db.add(row)
    await db.commit()
    await db.refresh(row)

    token = _serializer().dumps(row.id)
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=settings.session_ttl_seconds,
        httponly=True,
        samesite="lax",
        secure=False,  # localhost dev; flip to True behind HTTPS
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


async def current_user(
    passkey_session: str | None = Cookie(default=None, alias=COOKIE_NAME),
    db: AsyncSession = Depends(get_session),
) -> User:
    if not passkey_session:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "not signed in")
    try:
        session_id = _serializer().loads(passkey_session)
    except BadSignature as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "bad session") from exc

    row = (await db.execute(select(SessionRow).where(SessionRow.id == session_id))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "session expired")
    # SQLite doesn't preserve tz; treat naive timestamps as UTC.
    expires = row.expires_at if row.expires_at.tzinfo else row.expires_at.replace(tzinfo=timezone.utc)
    if expires < datetime.now(timezone.utc):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "session expired")

    user = (await db.execute(select(User).where(User.id == row.user_id))).scalar_one_or_none()
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "user gone")
    return user
