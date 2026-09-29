"""An installed app calling another app through Initiative.

``POST /app-platform/apps/{public_id}/endpoints/{endpoint_id}`` takes the
caller's installation token, or a member token to call on a member's behalf.
The install seam admits the token (``establish_install_access``); the rest of
the checks, and the call itself, are :mod:`app.services.marketplace.app_hub`'s.
The answer is the app's own, passed back as it sent it.

Limited per calling install, and per calling install and app called. Every
call the seam admits is written to the audit stream as ``app_hub.call``, with
how it ended and none of its parameters.
"""

from __future__ import annotations

from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse

from app.api.deps import (
    CREDENTIAL_INSTALL,
    InstallAccessError,
    SessionDep,
    VerifiedInstall,
    establish_install_access,
    oauth2_scheme,
    SystemSessionDep,
)
from app.core import audit_context
from app.core.app_access_token import (
    AccessTokenError,
    InstallAccessToken,
    is_access_token,
    unseal_access_token,
)
from app.core.audit_events import AuditEventType
from app.core.messages import AppDataMessages, AuthMessages
from app.core.rate_limit import (
    APP_HUB_CALLS_PER_INSTALL,
    APP_HUB_CALLS_PER_TARGET,
    take_allowance,
)
from app.db.session import clear_rls_context
from app.schemas.platform.app_hub import AppHubCall
from app.services import audit as audit_service
from app.services.marketplace import app_hub as hub_service
from app.services.marketplace.app_data import AppDataError

# Not part of the OpenAPI document: only app services call it, never the SPA.
router = APIRouter(include_in_schema=False)


#: The counter namespace for this route's allowances.
_LIMIT_NAMESPACE = "app-hub"

#: How a call ended, in the audit line, when it was answered.
OUTCOME_OK = "ok"


def _refuse() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=AuthMessages.COULD_NOT_VALIDATE_CREDENTIALS,
        headers={"WWW-Authenticate": "Bearer"},
    )


async def hub_caller(
    request: Request,
    session: SessionDep,
    bearer: Annotated[Optional[str], Depends(oauth2_scheme)] = None,
) -> hub_service.HubCaller:
    """The app the request's installation or member token names, or 401.

    The seam computes the install's standing: the community is in use, the
    install and its registration are live, and for a member token the member
    still belongs and still consents. The request's own session is left
    unrouted afterwards; the call runs on the system engine.
    """
    if not bearer or not is_access_token(bearer):
        raise _refuse()
    try:
        token = unseal_access_token(bearer)
    except AccessTokenError as exc:
        raise _refuse() from exc
    if not isinstance(token, InstallAccessToken):
        raise _refuse()
    try:
        context = await establish_install_access(
            session,
            VerifiedInstall(
                guild_id=token.guild_id,
                install_id=token.install_id,
                client_id=token.client_id,
                scopes=token.scopes,
                initiative_id=token.initiative_id,
                user_id=token.user_id,
                purpose=token.purpose,
            ),
        )
    except InstallAccessError as exc:
        raise _refuse() from exc
    clear_rls_context(session)
    await session.rollback()

    request.state.credential = CREDENTIAL_INSTALL
    audit_context.note_install(
        app=context.client_id,
        guild_id=context.guild_id,
        install_id=context.install_id,
    )
    # Whose request this is, for the rate limiter's key.
    request.state.app_install = (
        context.client_id,
        context.guild_id,
        context.install_id,
    )
    return hub_service.HubCaller(
        guild_id=context.guild_id,
        install_id=context.install_id,
        client_id=context.client_id,
        token_scopes=context.token_scopes,
        initiative_id=context.scope_initiative_id,
        member_user_id=context.member_user_id,
        purpose=context.purpose,
    )


HubCallerDep = Annotated[hub_service.HubCaller, Depends(hub_caller)]


def _audit(
    caller: hub_service.HubCaller,
    *,
    target: str,
    endpoint_id: str,
    outcome: str,
    direction: Optional[str] = None,
) -> None:
    detail: dict[str, Any] = {
        "caller": caller.client_id,
        "target": target,
        "endpoint": endpoint_id,
        "actor": caller.actor,
        "outcome": outcome,
    }
    if direction is not None:
        detail["direction"] = direction
    if caller.initiative_id is not None:
        detail["initiative_id"] = caller.initiative_id
    audit_service.emit(
        event_type=AuditEventType.APP_HUB_CALL,
        actor_user_id=caller.member_user_id,
        guild_id=caller.guild_id,
        detail=detail,
    )


@router.post("/apps/{public_id}/endpoints/{endpoint_id}")
async def call_app_endpoint(
    public_id: str,
    endpoint_id: str,
    payload: AppHubCall,
    caller: HubCallerDep,
    session: SystemSessionDep,
) -> JSONResponse:
    """Call one of another app's public endpoints, as the community or as the
    member the token acts for.

    Refusals answer with an OAuth-style ``detail``: ``insufficient_scope``,
    ``target_not_installed``, ``endpoint_not_public``,
    ``actor_not_supported`` or ``target_not_placed``, or the data proxy's code
    for a missing endpoint, bad parameters, a missing connection or an app
    that did not answer. Past either allowance the answer is 429.
    """
    install_key = f"{caller.client_id}:{caller.guild_id}:{caller.install_id}"
    if not await take_allowance(
        APP_HUB_CALLS_PER_INSTALL, _LIMIT_NAMESPACE, f"install:{install_key}"
    ) or not await take_allowance(
        APP_HUB_CALLS_PER_TARGET,
        _LIMIT_NAMESPACE,
        f"target:{install_key}:{public_id}",
    ):
        _audit(
            caller,
            target=public_id,
            endpoint_id=endpoint_id,
            outcome=AppDataMessages.RATE_LIMITED,
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=AppDataMessages.RATE_LIMITED,
        )

    try:
        answer = await hub_service.call_app(
            session,
            caller,
            target_public_id=public_id,
            endpoint_id=endpoint_id,
            params=payload.params,
        )
    except AppDataError as exc:
        _audit(caller, target=public_id, endpoint_id=endpoint_id, outcome=exc.code)
        raise HTTPException(status_code=exc.status_code, detail=exc.code) from exc

    _audit(
        caller,
        target=public_id,
        endpoint_id=endpoint_id,
        outcome=OUTCOME_OK,
        direction=answer.direction,
    )
    return JSONResponse(content=answer.body)
