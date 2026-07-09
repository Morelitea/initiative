"""Endpoints for the external billing service.

Machine-to-machine: requests are verified by
``app.services.platform.billing.verify_billing_envelope`` over the raw body
before parsing, run under the ``initiative_billing`` database role scoped to
the request's guild, and share one transaction (jti redemption, event-log
claim, and write commit or roll back together). Not part of the OpenAPI
schema; no user is ever resolved.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import ValidationError

from app.api.deps import SessionDep
from app.core.messages import BillingMessages
from app.db.session import set_billing_context
from app.schemas.platform.billing import (
    BillingGuildTierApply,
    BillingGuildTierRead,
    BillingHeadcountRead,
    BillingHeadcountRequest,
)
from app.services.platform import billing as billing_service
from app.services.platform.billing import (
    BillingEnvelopeError,
    BillingGuildNotFoundError,
    BillingReplayError,
    BillingSourceRestrictionError,
)

router = APIRouter(include_in_schema=False)


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
        # Billing absent is the self-host default, not a caller fault: 503
        # (fail closed, retryable) rather than 403.
        raise HTTPException(
            status_code=(
                status.HTTP_503_SERVICE_UNAVAILABLE
                if exc.code == BillingMessages.NOT_CONFIGURED
                else status.HTTP_403_FORBIDDEN
            ),
            detail=exc.code,
        ) from exc
    try:
        payload = model.model_validate_json(body)
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=_payload_error_code(exc),
        ) from exc
    return claims, payload


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
    await set_billing_context(session, guild_id=payload.guild_id)
    await _burn_jti(session, claims)
    try:
        result = await billing_service.apply_guild_tier(session, payload)
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
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=exc.code
        ) from exc
    await session.commit()
    return result


@router.post("/headcount", response_model=BillingHeadcountRead)
async def guild_headcount(
    request: Request, session: SessionDep
) -> BillingHeadcountRead:
    claims, payload = await _verify_and_parse(request, BillingHeadcountRequest)
    await set_billing_context(session, guild_id=payload.guild_id)
    await _burn_jti(session, claims)
    try:
        member_count = await billing_service.guild_member_count(
            session, payload.guild_id
        )
    except BillingGuildNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=BillingMessages.GUILD_NOT_FOUND,
        ) from exc
    await session.commit()  # persist the one-shot jti redemption
    return BillingHeadcountRead(guild_id=payload.guild_id, member_count=member_count)
