"""Authorization for the routes that touch vault_entries.

Being signed in isn't enough to read or change vault contents: the session must also
carry a passkey assertion from within the last `step_up_ttl_seconds`. Allowed requests
run the vault route; denied ones get a 403.

Deciding and recording are deliberately the same code path. The guard writes its
AccessLog row — allow or deny — before it returns or raises, so a denial can't reach
the client without a matching row. There's no separate error-logging branch that a
future route could forget to call.
"""

from collections.abc import Callable
from datetime import datetime, timezone

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import Principal, as_utc, current_principal
from app.config import get_settings
from app.db import get_session
from app.models import AccessLog

#: Sent as the `code` in the 403 body so the client can tell "prove it's still you"
#: apart from any other refusal and start a re-verification ceremony.
REVERIFICATION_REQUIRED = "reverification_required"

ALLOW = "allow"
DENY = "deny"
STALE_VERIFICATION = "stale_verification"


def _verified_age_seconds(principal: Principal, now: datetime) -> int | None:
    """Seconds since this session's last passkey assertion, or None if it never had one."""
    last_verified = principal.session.last_verified_at
    if last_verified is None:
        return None
    return int((now - as_utc(last_verified)).total_seconds())


def require_fresh_verification(action: str) -> Callable:
    """Build a dependency guarding one vault action, e.g. require_fresh_verification("vault:list")."""

    async def guard(
        request: Request,
        principal: Principal = Depends(current_principal),
        db: AsyncSession = Depends(get_session),
    ) -> Principal:
        now = datetime.now(timezone.utc)
        age = _verified_age_seconds(principal, now)
        stale = age is None or age > get_settings().step_up_ttl_seconds

        db.add(
            AccessLog(
                user_id=principal.user.id,
                session_id=principal.session.id,
                action=action,
                method=request.method,
                path=request.url.path[:255],
                decision=DENY if stale else ALLOW,
                reason=STALE_VERIFICATION if stale else None,
                verified_age_seconds=age,
                created_at=now,
            )
        )
        await db.commit()

        if stale:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                detail={
                    "code": REVERIFICATION_REQUIRED,
                    "message": "Re-verify with your passkey to use the vault.",
                },
            )
        return principal

    return guard
