"""Authorization for the routes that touch vault_entries.

`require_permission` composes with the existing session gate rather than replacing
it: it depends on `current_principal`, so the cookie is still resolved and still
401s on its own terms, and the role check happens on top of an already-authenticated
caller. Routes swap one dependency and the auth flow is otherwise untouched.

Two things have to hold before a request reaches a vault route:

  1. the caller's role grants the action  (owner may write, viewer may only read)
  2. the session carries a passkey assertion from the last step_up_ttl_seconds

Permission is checked first, because it's the one re-verifying can't fix — a viewer
who deletes will be denied however fresh their assertion is, and telling them to
touch the sensor again would be a lie.

Deciding and recording are deliberately the same code path. The guard writes its
AuditLog row — allow or deny — before it returns or raises, so a denial can't reach
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
from app.models import OWNER, VIEWER, AuditLog

#: What each role may do. A dict beats a permissions table while there are two roles
#: and three actions; if either grows, this is the thing to move into the database.
PERMISSIONS: dict[str, frozenset[str]] = {
    OWNER: frozenset({"vault:list", "vault:create", "vault:delete"}),
    VIEWER: frozenset({"vault:list"}),
}

#: Codes in the 403 body, so the client can tell "prove it's still you" (recoverable,
#: offer the passkey prompt) from "you may not do this" (not recoverable by retrying).
REVERIFICATION_REQUIRED = "reverification_required"
PERMISSION_DENIED = "permission_denied"

ALLOW = "allow"
DENY = "deny"
STALE_VERIFICATION = "stale_verification"
MISSING_PERMISSION = "missing_permission"

_MESSAGES = {
    REVERIFICATION_REQUIRED: "Re-verify with your passkey to use the vault.",
    PERMISSION_DENIED: "Your role does not allow this action.",
}


def permitted(role: str, action: str) -> bool:
    """Whether `role` grants `action`. Unknown roles grant nothing."""
    return action in PERMISSIONS.get(role, frozenset())


def _verified_age_seconds(principal: Principal, now: datetime) -> int | None:
    """Seconds since this session's last passkey assertion, or None if it never had one."""
    last_verified = principal.session.last_verified_at
    if last_verified is None:
        return None
    return int((now - as_utc(last_verified)).total_seconds())


def require_permission(action: str) -> Callable:
    """Build a dependency guarding one vault action, e.g. require_permission("vault:delete")."""

    async def guard(
        request: Request,
        principal: Principal = Depends(current_principal),
        db: AsyncSession = Depends(get_session),
    ) -> Principal:
        now = datetime.now(timezone.utc)
        role = principal.user.role
        age = _verified_age_seconds(principal, now)

        if not permitted(role, action):
            reason, code = MISSING_PERMISSION, PERMISSION_DENIED
        elif age is None or age > get_settings().step_up_ttl_seconds:
            reason, code = STALE_VERIFICATION, REVERIFICATION_REQUIRED
        else:
            reason, code = None, None

        db.add(
            AuditLog(
                user_id=principal.user.id,
                session_id=principal.session.id,
                role=role,
                action=action,
                method=request.method,
                path=request.url.path[:255],
                result=ALLOW if reason is None else DENY,
                reason=reason,
                verified_age_seconds=age,
                created_at=now,
            )
        )
        await db.commit()

        if code is not None:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                detail={"code": code, "message": _MESSAGES[code]},
            )
        return principal

    return guard
