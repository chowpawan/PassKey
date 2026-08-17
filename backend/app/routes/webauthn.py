from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from webauthn.helpers import base64url_to_bytes

from app import webauthn_helpers
from app.auth import Principal, create_session, current_principal, mark_verified
from app.db import get_session
from app.models import Challenge, Credential, User
from app.schemas import (
    CeremonyResponse,
    LoginCompleteRequest,
    RegisterCompleteRequest,
    ReverifyCompleteRequest,
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


async def _begin_assertion(db: AsyncSession, user: User, kind: str) -> CeremonyResponse:
    """Build authentication options over a user's passkeys and stash the challenge."""
    creds = (
        await db.execute(select(Credential).where(Credential.user_id == user.id))
    ).scalars().all()
    if not creds:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "user has no passkey")

    options, challenge = webauthn_helpers.build_authentication_options(
        [c.credential_id for c in creds]
    )
    await _stash_challenge(db, user.id, challenge, kind)
    return CeremonyResponse(options=options)


async def _verify_assertion(
    db: AsyncSession, user: User, assertion: dict, challenge: bytes
) -> None:
    """Check an assertion against the user's stored credential and bump its sign count."""
    raw_id_b64url = assertion.get("rawId") or assertion.get("id")
    if not raw_id_b64url:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "assertion missing rawId")

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
            assertion, challenge, cred.public_key, cred.sign_count
        )
    except Exception as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"verification failed: {exc}") from exc

    cred.sign_count = new_count
    await db.commit()


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

    return await _begin_assertion(db, user, "authenticate")


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
    await _verify_assertion(db, user, body.assertion, challenge)

    await create_session(user.id, response, db)
    return {"username": user.username}


@router.post("/reverify/begin", response_model=CeremonyResponse)
async def reverify_begin(
    principal: Principal = Depends(current_principal),
    db: AsyncSession = Depends(get_session),
) -> CeremonyResponse:
    """Start a step-up ceremony for the session that's already signed in."""
    return await _begin_assertion(db, principal.user, "reverify")


@router.post("/reverify/complete")
async def reverify_complete(
    body: ReverifyCompleteRequest,
    principal: Principal = Depends(current_principal),
    db: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    """Refresh the current session's clock — no new session, no new cookie."""
    challenge = await _consume_challenge(db, principal.user.id, "reverify")
    await _verify_assertion(db, principal.user, body.assertion, challenge)

    await mark_verified(principal.session.id, db)
    return {"username": principal.user.username}
