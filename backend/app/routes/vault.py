from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import COOKIE_NAME, current_user, destroy_session
from app.crypto import decrypt, encrypt
from app.db import get_session
from app.models import User, VaultEntry
from app.schemas import VaultEntryCreate, VaultEntryOut, WhoAmIResponse

router = APIRouter()


@router.get("/whoami", response_model=WhoAmIResponse)
async def whoami(user: User = Depends(current_user)) -> WhoAmIResponse:
    return WhoAmIResponse(username=user.username)


@router.post("/signout")
async def signout(
    response: Response,
    passkey_session: str | None = Cookie(default=None, alias=COOKIE_NAME),
    db: AsyncSession = Depends(get_session),
) -> dict[str, bool]:
    await destroy_session(passkey_session, response, db)
    return {"ok": True}


@router.get("", response_model=list[VaultEntryOut])
async def list_entries(
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_session),
) -> list[VaultEntryOut]:
    rows = (
        await db.execute(
            select(VaultEntry).where(VaultEntry.user_id == user.id).order_by(VaultEntry.created_at.desc())
        )
    ).scalars().all()

    return [
        VaultEntryOut(
            id=row.id,
            label=row.label,
            username=row.username,
            password=decrypt(row.ciphertext, row.nonce),
            created_at=row.created_at.isoformat(),
        )
        for row in rows
    ]


@router.post("", response_model=VaultEntryOut, status_code=status.HTTP_201_CREATED)
async def create_entry(
    body: VaultEntryCreate,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_session),
) -> VaultEntryOut:
    ciphertext, nonce = encrypt(body.password)
    row = VaultEntry(
        user_id=user.id,
        label=body.label,
        username=body.username,
        ciphertext=ciphertext,
        nonce=nonce,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return VaultEntryOut(
        id=row.id,
        label=row.label,
        username=row.username,
        password=body.password,
        created_at=row.created_at.isoformat(),
    )


@router.delete("/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_entry(
    entry_id: str,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_session),
) -> Response:
    row = (
        await db.execute(
            select(VaultEntry).where(VaultEntry.id == entry_id, VaultEntry.user_id == user.id)
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "entry not found")
    await db.delete(row)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
