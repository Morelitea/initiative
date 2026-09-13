"""Endpoints for the external billing service.

Machine-to-machine: requests are verified by
``app.services.platform.billing.verify_billing_envelope`` over the raw body
before parsing, run under the ``initiative_billing`` database role scoped to
the request's guild, and share one transaction (jti redemption, event-log
claim, and write commit or roll back together). Not part of the OpenAPI
schema; no user is ever resolved.

Every verb names its guild by the **reference** billing holds for it, never by
a row id of ours. ``_resolve_guild`` is the one place that becomes a guild id,
and everything past it works on the id as before.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import ValidationError
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import SessionDep
from app.core.messages import BillingMessages
from app.db.session import get_admin_session, set_billing_context
from app.schemas.platform.billing import (
    BillingGuildNameRead,
    BillingGuildNameRequest,
    BillingGuildTierApply,
    BillingGuildTierRead,
    BillingUsageRead,
    BillingUsageRequest,
)
from app.services.platform import billing as billing_service
from app.services.platform import identity_refs
from app.services.platform.billing import (
    BillingEnvelopeError,
    BillingGuildNotFoundError,
    BillingReplayError,
    BillingSourceRestrictionError,
)

router = APIRouter(include_in_schema=False)

# The storage read needs the system engine to reach the guild schema (the
# billing role is confined to public); the billing session still owns the
# jti burn.
AdminSessionDep = Annotated[AsyncSession, Depends(get_admin_session)]


def _payload_error_code(exc: ValidationError) -> str:
    """Surface a BILLING_* code raised by a model validator (e.g. the
    support-source restriction) instead of the generic payload code."""
    for error in exc.errors():
        message = str(error.get("msg", ""))
        for code in (
            BillingMessages.SUPPORT_SOURCE_RESTRICTED,
            BillingMessages.ACTOR_REQUIRED,
        ):
            if code in message:
                return code
    return BillingMessages.INVALID_PAYLOAD


async def _verify_and_parse(request: Request, model):
    """Envelope first, parse second (see module docstring)."""
    body = await request.body()
    try:
        claims = billing_service.verify_billing_envelope(
            method=request.method,
            path=request.url.path,
            headers=request.headers,
            body=body,
        )
    except BillingEnvelopeError as exc:
        # Billing absent is the self-host default, not a caller fault, and an
        # unreadable key is this deployment's own misconfiguration: both answer
        # 503 (fail closed, retryable) rather than 403.
        raise HTTPException(
            status_code=(
                status.HTTP_503_SERVICE_UNAVAILABLE
                if exc.code
                in (BillingMessages.NOT_CONFIGURED, BillingMessages.KEY_UNREADABLE)
                else status.HTTP_403_FORBIDDEN
            ),
            detail=exc.code,
        ) from exc
    try:
        payload = model.model_validate_json(body)
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=_payload_error_code(exc),
        ) from exc
    return claims, payload


async def _resolve_guild(guild_ref: str) -> int:
    """The guild billing's reference names.

    Billing names a guild by the reference it was given and never by a row id
    of ours, so this is the edge every verb below crosses first. An unknown
    reference answers 404 with nothing consumed, which is the same retryable
    shape as a guild that does not exist yet.
    """
    guild_id = await identity_refs.resolve_billing_guild(ref=guild_ref)
    if guild_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=BillingMessages.GUILD_NOT_FOUND,
        )
    return guild_id


async def _burn_jti(session, claims) -> None:
    try:
        await billing_service.record_jti(
            session, jti=claims.jti, expires_at=claims.expires_at
        )
    except BillingReplayError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=BillingMessages.REPLAYED_TOKEN,
        ) from exc


@router.post("/guild-tier", response_model=BillingGuildTierRead)
async def apply_guild_tier(
    request: Request, session: SessionDep
) -> BillingGuildTierRead:
    claims, payload = await _verify_and_parse(request, BillingGuildTierApply)
    guild_id = await _resolve_guild(payload.guild_ref)
    await set_billing_context(session, guild_id=guild_id)
    await _burn_jti(session, claims)
    try:
        result = await billing_service.apply_guild_tier(
            session, payload, guild_id=guild_id
        )
    except BillingGuildNotFoundError as exc:
        # Rolls back with the jti unredeemed and the event id unconsumed, so
        # the delivery can be retried once the guild exists.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=BillingMessages.GUILD_NOT_FOUND,
        ) from exc
    except BillingSourceRestrictionError as exc:
        # The restriction is checked before the event-log claim, so the
        # rollback leaves neither the event id nor the jti consumed. Unlike
        # the 404 (a transient "guild not yet created"), this is a
        # deterministic reject: the fix is a corrected payload, not a retry
        # of the same body — that corrected write (even reusing the event id)
        # then applies.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=exc.code
        ) from exc
    await session.commit()
    return result


@router.post("/guild-name", response_model=BillingGuildNameRead)
async def guild_name(request: Request, session: SessionDep) -> BillingGuildNameRead:
    """Signed read: what one guild calls itself.

    For rendering. A reference is unreadable on purpose, so a page about
    somebody's own community would otherwise have nothing to title itself with.

    Envelope-verified and jti-burned like the other reads. A guild that has been
    deleted 404s with the jti unredeemed, so the call stays retryable while it
    is the caller's timing rather than their credential that is wrong.
    """
    claims, payload = await _verify_and_parse(request, BillingGuildNameRequest)
    guild_id = await _resolve_guild(payload.guild_ref)
    await set_billing_context(session, guild_id=guild_id)
    await _burn_jti(session, claims)

    name = await billing_service.guild_display_name(session, guild_id)
    if name is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=BillingMessages.GUILD_NOT_FOUND,
        )
    await session.commit()  # persist the one-shot jti redemption
    return BillingGuildNameRead(guild_ref=payload.guild_ref, name=name)


@router.post("/usage", response_model=BillingUsageRead)
async def guild_usage(
    request: Request, session: SessionDep, admin_session: AdminSessionDep
) -> BillingUsageRead:
    """Signed read: current stored bytes for one guild.

    Envelope-verified and jti-burned on the billing session like the other
    reads; the actual ``SUM(uploads.size_bytes)`` runs on ``admin_session``
    routed into the guild schema (the billing role can't reach it). A missing
    guild 404s with the jti unredeemed (retryable).
    """
    claims, payload = await _verify_and_parse(request, BillingUsageRequest)
    guild_id = await _resolve_guild(payload.guild_ref)
    await set_billing_context(session, guild_id=guild_id)
    await _burn_jti(session, claims)
    try:
        usage_bytes = await billing_service.guild_storage_usage(admin_session, guild_id)
    except BillingGuildNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=BillingMessages.GUILD_NOT_FOUND,
        ) from exc
    await session.commit()  # persist the one-shot jti redemption
    return BillingUsageRead(guild_ref=payload.guild_ref, usage_bytes=usage_bytes)
