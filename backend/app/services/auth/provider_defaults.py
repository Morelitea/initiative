"""The deployment's own answer for a provider, for communities that have none.

One organisation running its own deployment has one identity provider and one
tenant, and its communities are its teams. Asking two hundred teams to repeat
the same two facts makes the operator their queue. So an operator answers once
per provider here, and a community inherits that until it says otherwise.

What a default is allowed to carry is the same arrangement a community would
have written: which claim narrows the provider, and which values count. It
carries no ``auto_join`` — a default names a provider, never a community, so
joining on one would place an arrival in every community that had not spoken.

Overriding is not a merge. A community's own connection to the provider
replaces this row outright, including one written with the button off, which is
how a community declines a default.
"""

import logging

from fastapi import HTTPException, status
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.audit_events import AuditEventType
from app.core.messages import AuthProviderMessages
from app.models.platform.auth_provider import AuthProvider
from app.models.platform.platform_provider_default import PlatformProviderDefault
from app.schemas.platform.settings import (
    PlatformProviderDefaultRead,
    PlatformProviderDefaultUpdate,
)
from app.services import audit as audit_service
from app.services.auth.guild_provider_connections import clean_claim

logger = logging.getLogger(__name__)

#: What the deployment's answer for a provider consists of, for the record.
AUDITED_FIELDS: tuple[str, ...] = ("claim", "claim_values", "enabled")


def default_read(row: PlatformProviderDefault) -> PlatformProviderDefaultRead:
    return PlatformProviderDefaultRead(
        provider_id=row.provider_id,
        claim=row.claim,
        claim_values=list(row.claim_values or []),
        enabled=row.enabled,
    )


async def _require_provider(session: AsyncSession, provider_id: int) -> AuthProvider:
    provider = await session.get(AuthProvider, provider_id)
    if provider is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=AuthProviderMessages.NOT_FOUND,
        )
    return provider


async def get_default(
    session: AsyncSession, provider_id: int
) -> PlatformProviderDefaultRead | None:
    await _require_provider(session, provider_id)
    row = await session.get(PlatformProviderDefault, provider_id)
    return default_read(row) if row else None


async def set_default(
    session: AsyncSession,
    provider_id: int,
    payload: PlatformProviderDefaultUpdate,
    *,
    actor_user_id: int | None = None,
) -> PlatformProviderDefaultRead:
    """Answer for this provider, or change the answer.

    Nobody is signed out and no community's own connection moves. What changes
    is what a community that has said nothing inherits, and it applies to the
    next request rather than the next sign-in — the gate reads the arrangement
    in force when it is asked.
    """
    await _require_provider(session, provider_id)
    claim, claim_values = clean_claim(payload.claim, payload.claim_values)

    row = await session.get(PlatformProviderDefault, provider_id)
    created = row is None
    if row is None:
        # In force from the moment it is written, unless the same request says
        # otherwise — an operator answering is answering, not drafting.
        row = PlatformProviderDefault(provider_id=provider_id, enabled=True)
    before = {} if created else audit_service.snapshot(row, AUDITED_FIELDS)
    row.claim = claim
    row.claim_values = claim_values
    if payload.enabled is not None:
        row.enabled = payload.enabled
    session.add(row)
    changed = audit_service.changed_fields(
        before, audit_service.snapshot(row, AUDITED_FIELDS)
    )
    if created or changed["changed"]:
        await audit_service.record(
            session,
            event_type=AuditEventType.AUTH_PROVIDER_DEFAULT_SET,
            actor_user_id=actor_user_id,
            target_type="auth_provider",
            target_id=provider_id,
            detail=changed,
        )
    await session.commit()
    await session.refresh(row)
    return default_read(row)


async def clear_default(
    session: AsyncSession, provider_id: int, *, actor_user_id: int | None = None
) -> None:
    """Withdraw the answer. Communities that wrote their own keep them; the
    rest stop counting this provider as theirs."""
    await _require_provider(session, provider_id)
    row = await session.get(PlatformProviderDefault, provider_id)
    if row is None:
        return
    await session.delete(row)
    await audit_service.record(
        session,
        event_type=AuditEventType.AUTH_PROVIDER_DEFAULT_CLEARED,
        actor_user_id=actor_user_id,
        target_type="auth_provider",
        target_id=provider_id,
        detail={},
    )
    await session.commit()
