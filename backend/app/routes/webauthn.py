from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import webauthn_helpers
from app.auth import create_session
from app.db import get_session
from app.models import Challenge, Credential, User
from app.schemas import (
    CeremonyResponse,
    LoginCompleteRequest,
    RegisterCompleteRequest,
    UsernameRequest,
)

router = APIRouter()

CHALLENGE_TTL_SECONDS = 300


async def _stash_challenge(
    db: AsyncSession, user_id: str | None, challenge: bytes, kind: str
) -> None:
    # Single-use: clear prior challenges of the same kind for this user before inserting.
    await db.execute(
        delete(Challenge).where(Challenge.user_id == user_id, Challenge.kind == kind)
    )
    expires = datetime.now(timezone.utc) + timedelta(seconds=CHALLENGE_TTL_SECONDS)
    db.add(Challenge(user_id=user_id, challenge=challenge, kind=kind, expires_at=expires))
    await db.commit()


async def _consume_challenge(db: AsyncSession, user_id: str | None, kind: str) -> bytes:
    row = (
        await db.execute(
            select(Challenge).where(Challenge.user_id == user_id, Challenge.kind == kind)
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "challenge missing or expired")
    expires = row.expires_at if row.expires_at.tzinfo else row.expires_at.replace(tzinfo=timezone.utc)
    if expires < datetime.now(timezone.utc):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "challenge missing or expired")
    challenge = row.challenge
    await db.delete(row)
    await db.commit()
    return challenge


@router.post("/register/begin", response_model=CeremonyResponse)
async def register_begin(
    body: UsernameRequest, db: AsyncSession = Depends(get_session)
) -> CeremonyResponse:
    user = (
        await db.execute(select(User).where(User.username == body.username))
    ).scalar_one_or_none()
    if user is None:
        user = User(username=body.username)
        db.add(user)
        await db.commit()
        await db.refresh(user)

    existing_rows = (
        await db.execute(select(Credential.credential_id).where(Credential.user_id == user.id))
    ).scalars().all()
    options, challenge = webauthn_helpers.build_registration_options(
        user_id=user.id.encode("utf-8"),
        username=user.username,
        existing_credential_ids=list(existing_rows),
    )
    await _stash_challenge(db, user.id, challenge, "register")
    return CeremonyResponse(options=options)


@router.post("/register/complete")
async def register_complete(
    body: RegisterCompleteRequest,
    response: Response,
    db: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    user = (
        await db.execute(select(User).where(User.username == body.username))
    ).scalar_one_or_none()
    if user is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "unknown user")

    challenge = await _consume_challenge(db, user.id, "register")

    try:
        cred_id, pub_key, sign_count = webauthn_helpers.verify_registration(
            body.attestation, challenge
        )
    except Exception as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"registration failed: {exc}") from exc

    transports = body.attestation.get("response", {}).get("transports")
    db.add(
        Credential(
            user_id=user.id,
            credential_id=cred_id,
            public_key=pub_key,
            sign_count=sign_count,
            transports=transports,
        )
    )
    await db.commit()

    await create_session(user.id, response, db)
    return {"username": user.username}


@router.post("/login/begin", response_model=CeremonyResponse)
async def login_begin(
    body: UsernameRequest, db: AsyncSession = Depends(get_session)
) -> CeremonyResponse:
    user = (
        await db.execute(select(User).where(User.username == body.username))
    ).scalar_one_or_none()
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown user")

    creds = (
        await db.execute(select(Credential).where(Credential.user_id == user.id))
    ).scalars().all()
    if not creds:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "user has no passkey")

    options, challenge = webauthn_helpers.build_authentication_options(
        [c.credential_id for c in creds]
    )
    await _stash_challenge(db, user.id, challenge, "authenticate")
    return CeremonyResponse(options=options)


@router.post("/login/complete")
async def login_complete(
    body: LoginCompleteRequest,
    response: Response,
    db: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    user = (
        await db.execute(select(User).where(User.username == body.username))
    ).scalar_one_or_none()
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown user")

    challenge = await _consume_challenge(db, user.id, "authenticate")

    # Look up which stored credential matches the assertion.
    raw_id_b64url = body.assertion.get("rawId") or body.assertion.get("id")
    if not raw_id_b64url:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "assertion missing rawId")
    from webauthn.helpers import base64url_to_bytes

    cred_id_bytes = base64url_to_bytes(raw_id_b64url)
    cred = (
        await db.execute(
            select(Credential).where(
                Credential.user_id == user.id, Credential.credential_id == cred_id_bytes
            )
        )
    ).scalar_one_or_none()
    if cred is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "unknown credential")

    try:
        new_count = webauthn_helpers.verify_authentication(
            body.assertion, challenge, cred.public_key, cred.sign_count
        )
    except Exception as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"login failed: {exc}") from exc

    cred.sign_count = new_count
    await db.commit()

    await create_session(user.id, response, db)
    return {"username": user.username}
