"""Trading a delegate's token for one the app it names can read.

A delegate holds references minted at its own install. The app it wants to act
at holds different ones for the same guild and the same member, because that is
what a sector is for — so neither can name anybody to the other, and only this
deployment holds both mappings.

The delegate presents what it holds, as it would on any other delegated call,
and names the app it is addressing. What comes back names the same two in that
app's terms, signed with the app-platform key so the app verifies it against the
key set it already fetches for context tokens.

Authenticated by the ordinary delegation path — this route is reached with a
delegate's own token, so every rule that governs a delegated call governs this
one: the registration is live and holds ``delegation``, the guild has it
installed, the member authorized it, and the token is one-shot.

See ``history/opaque-identity-design.md`` §12.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from typing import Annotated

from app.api.deps import SessionDep, get_current_active_user
from app.core.messages import AppServiceMessages, DelegationExchangeMessages
from app.core.security import (
    AppPlatformSigningNotConfiguredError,
    app_platform_signing_enabled,
)
from app.db.session import set_rls_context
from app.models.platform.user import User
from app.schemas.marketplace.delegation_exchange import (
    DelegationExchangeRequest,
    DelegationExchangeResponse,
)
from app.services.marketplace import delegation_exchange as exchange_service
from app.services.marketplace.delegation_exchange import DelegationExchangeError

#: Not part of the OpenAPI schema: this is a service-to-service route, reached
#: with a delegate's own credential, and no browser calls it.
router = APIRouter(include_in_schema=False)

CurrentUserDep = Annotated[User, Depends(get_current_active_user)]


@router.post("/delegation/exchange", response_model=DelegationExchangeResponse)
async def exchange_delegation(
    request: Request,
    payload: DelegationExchangeRequest,
    session: SessionDep,
    current_user: CurrentUserDep,
) -> DelegationExchangeResponse:
    """Re-issue this call's delegation for one app, in that app's own terms.

    Answers 404 for an audience this deployment does not run, and for a guild
    that has not installed it — one refusal, because a delegate is entitled to
    distinguish neither.
    """
    delegate = getattr(request.state, "delegating_app", None)
    guild_id = getattr(request.state, "delegated_guild_id", None)
    if not delegate or guild_id is None:
        # Reached with something other than a delegation token. There is
        # nothing to exchange: the whole operation is "re-address what the
        # caller already holds".
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=DelegationExchangeMessages.NOT_DELEGATED,
        )
    if not app_platform_signing_enabled():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=AppServiceMessages.SIGNING_NOT_CONFIGURED,
        )

    # The install lives in the guild's own schema, so the session is routed
    # into it — as the member the delegate is carrying, under RLS, rather than
    # on the system engine. An install is guild-level, so reading one needs no
    # standing beyond being in the guild, which the delegation already
    # established.
    await set_rls_context(session, user_id=current_user.id, guild_id=guild_id)
    try:
        token, expires_in = await exchange_service.exchange_for_app(
            session,
            target_public_id=payload.audience,
            delegate_public_id=delegate,
            guild_id=guild_id,
            user_id=current_user.id,
        )
    except DelegationExchangeError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.code) from exc
    except AppPlatformSigningNotConfiguredError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=AppServiceMessages.SIGNING_NOT_CONFIGURED,
        ) from exc

    return DelegationExchangeResponse(token=token, expires_in_seconds=expires_in)
