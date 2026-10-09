"""An installed plug-in's calls about its own installation.

Every route here takes an **installation token** and reaches the install the
token names — no ``community_ref`` in the path, and no scope, because these are
the install's own configuration rather than community content. A token
narrowed to one initiative reaches them too. A member token acts for somebody
and is refused.

* ``GET /installation/config`` — the decrypted configuration: the guild-wide
  values, and each member's managed values. Never a flow's tokens.
* ``GET /installation/connections`` — the plug-in's per-member connections, by
  opaque reference, with status only.
* ``POST /installation/connections/{connection_ref}/token`` — a usable access
  token for one connection, refreshed or minted first.
* ``POST /installation/config-status`` — the plug-in's verdict on the
  configuration it was handed.
* ``POST /installation/events`` — an event the plug-in emits, kept for the outbox
  poller to deliver to the community's subscriptions.
* ``POST /installation/blocks/stale`` — one of the plug-in's blocks changed on
  some tasks; the browsers showing them read it again. Nothing is kept.

The token is checked by the install seam (``establish_install_access``),
whose standing statement admits the install only while it may act: the
community is in use, the install is on, and its registration is live. The
work itself runs on the system engine, routed into the community one install
at a time (:mod:`app.services.tenant.plugin_channels`).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlmodel.ext.asyncio.session import AsyncSession

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
from app.core.body_limit import max_body
from app.core.plugin_access_token import InstallAccessToken
from app.core.identify import bearer_plugin_token
from app.core.messages import AuthMessages, PluginChannelMessages
from app.db.session import clear_rls_context
from app.models.tenant.guild_plugin import GuildPlugin
from app.schemas.tenant.plugin_channel import (
    PluginBlockStale,
    PluginConnectionRead,
    PluginConnectionsResponse,
    PluginConnectionToken,
    PluginInstallConfigRead,
    PluginInstallationEvent,
    PluginStatusRead,
    PluginStatusReport,
)
from app.services.marketplace import plugin_blocks, registration_lookup
from app.services.marketplace.registration_lookup import RegistrationSnapshot
from app.services.tenant import plugin_channels as channels_service

# Not part of the OpenAPI document: only plug-in containers call these, never the
# SPA, so the generated frontend client carries none of them.
router = APIRouter(prefix="/installation", include_in_schema=False)

#: The most one installation call may carry. Every write here is a
#: configuration report or an event, none larger than an event: its payload
#: and its envelope. The handler's exact cap still applies after.
MAX_REQUEST_BYTES = channels_service.MAX_EVENT_PAYLOAD_BYTES + 8 * 1024

_bounded = max_body(lambda: MAX_REQUEST_BYTES, PluginChannelMessages.EVENT_TOO_LARGE)


def _refuse() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=AuthMessages.COULD_NOT_VALIDATE_CREDENTIALS,
        headers={"WWW-Authenticate": "Bearer"},
    )


@dataclass(frozen=True)
class Installation:
    """The install an installation token names, admitted by the seam."""

    guild_id: int
    install_id: int
    registration: RegistrationSnapshot
    #: The initiative the token is narrowed to, when it is.
    initiative_id: Optional[int] = None


async def installation_caller(
    request: Request,
    session: SessionDep,
    # Declares the scheme for the API description; read by ``bearer_plugin_token``.
    bearer: Annotated[Optional[str], Depends(oauth2_scheme)] = None,
) -> Installation:
    """The install the request's installation token names, or 401.

    The token is unsealed locally, then the seam computes the install's
    standing, which is what says it may act now. The request's own session is
    left unrouted afterwards: the work runs on the system engine.
    """
    token = bearer_plugin_token(request)
    if not isinstance(token, InstallAccessToken) or token.user_id is not None:
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
            ),
        )
    except InstallAccessError as exc:
        raise _refuse() from exc
    clear_rls_context(session)
    await session.rollback()

    registration = (await registration_lookup.load_registrations()).get(
        context.client_id
    )
    if registration is None or not registration.live:
        raise _refuse()

    request.state.credential = CREDENTIAL_INSTALL
    audit_context.note_install(
        plugin=context.client_id,
        guild_id=context.guild_id,
        install_id=context.install_id,
    )
    # Whose request this is, for the rate limiter's key.
    request.state.plugin_install = (
        context.client_id,
        context.guild_id,
        context.install_id,
    )
    return Installation(
        guild_id=context.guild_id,
        install_id=context.install_id,
        registration=registration,
        initiative_id=context.scope_initiative_id,
    )


InstallationDep = Annotated[Installation, Depends(installation_caller)]


async def _load(
    session: AsyncSession, installation: Installation, *, for_write: bool = False
) -> GuildPlugin:
    return await channels_service.load_install(
        session,
        installation.registration,
        installation.guild_id,
        plugin_install_id=installation.install_id,
        for_write=for_write,
    )


@router.get("/config", response_model=PluginInstallConfigRead)
async def read_installation_config(
    installation: InstallationDep, session: SystemSessionDep
) -> PluginInstallConfigRead:
    """The decrypted configuration for this install.

    The guild-wide values an admin supplied, plus the per-member ones the plug-in
    wrote back itself, each keyed by the opaque reference it knows that member
    by. Refused when the community has turned the plug-in off.
    """
    plugin = await _load(session, installation)
    payload = await channels_service.config_payload(session, plugin)
    return PluginInstallConfigRead(**payload)


@router.get("/connections", response_model=PluginConnectionsResponse)
async def list_installation_connections(
    installation: InstallationDep, session: SystemSessionDep
) -> PluginConnectionsResponse:
    """The plug-in's per-member connections for this install, by opaque reference
    and with status only."""
    plugin = await _load(session, installation)
    rows = await channels_service.connection_payload(session, plugin)
    return PluginConnectionsResponse(
        items=[PluginConnectionRead(**row) for row in rows]
    )


@router.post(
    "/connections/{connection_ref}/token", response_model=PluginConnectionToken
)
@_bounded
async def read_installation_connection_token(
    connection_ref: str,
    installation: InstallationDep,
    session: SystemSessionDep,
) -> PluginConnectionToken:
    """A usable access token for one of this install's connections.

    A member's connection must be connected and not blocked; its token is
    refreshed first when it is within two minutes of expiring, and one the
    vendor will not refresh leaves the connection ``expired`` (409). A
    guild-wide connection answers its ``jwt_bearer`` token, minted and reused
    until shortly before it expires, or its own stored token.
    """
    plugin = await _load(session, installation, for_write=True)
    token = await channels_service.connection_token(
        session,
        plugin,
        installation.registration,
        connection_ref=connection_ref,
    )
    return PluginConnectionToken(**token)


@router.post("/config-status", response_model=PluginStatusRead)
@_bounded
async def report_installation_config_status(
    payload: PluginStatusReport,
    installation: InstallationDep,
    session: SystemSessionDep,
) -> PluginStatusRead:
    """Record whether the configuration this community supplied works.

    Only the vendor can confirm a credential carries the permissions it needs;
    this is how that answer reaches the admin who supplied it. An install
    nothing reports on stays ``unverified``.
    """
    plugin = await _load(session, installation, for_write=True)
    result = await channels_service.report_config_state(
        session, plugin, state=payload.state, detail=payload.detail
    )
    return PluginStatusRead(**result)


@router.post("/events", status_code=status.HTTP_202_ACCEPTED)
@_bounded
async def ingest_installation_event(
    payload: PluginInstallationEvent,
    installation: InstallationDep,
    session: SystemSessionDep,
) -> dict[str, str]:
    """Emit one event in the community this install is in.

    The event type must be one the pinned definition declares, namespaced
    under the calling plug-in, and the payload at most 8 KiB. An event about an
    initiative names one the install is placed in (403 otherwise). Answers
    ``202``: the event is kept and delivered to the community's subscriptions,
    and what subscribers do with it is not the emitting plug-in's to know.
    """
    plugin = await _load(session, installation, for_write=True)
    await channels_service.emit_event(
        session,
        plugin,
        installation.registration,
        event_type=payload.event_type,
        payload=payload.payload,
        initiative_id=payload.initiative_id,
        token_initiative_id=installation.initiative_id,
    )
    return {"status": "accepted"}


@router.post("/blocks/stale", status_code=status.HTTP_202_ACCEPTED)
@_bounded
async def mark_installation_block_stale(
    payload: PluginBlockStale,
    installation: InstallationDep,
    session: SystemSessionDep,
) -> dict[str, str]:
    """Say one of this plug-in's blocks changed on these tasks.

    The block must be one the pinned definition declares
    (``PLUGIN_BLOCK_NOT_FOUND`` otherwise). Of the tasks, only those this
    install can read count, and the browsers showing them in their
    initiatives read the block again. Answers ``202`` whatever that reached.
    """
    plugin = await _load(session, installation)
    await plugin_blocks.mark_stale(
        plugin,
        installation.registration,
        guild_id=installation.guild_id,
        block_id=payload.block,
        task_ids=payload.task_ids,
        token_initiative_id=installation.initiative_id,
    )
    return {"status": "accepted"}
