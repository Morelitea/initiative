"""An installed app's calls about its own installation.

Every route here takes an **installation token** and reaches the install the
token names — no ``guild_ref`` in the path, and no scope, because these are
the install's own configuration rather than community content. A token
narrowed to one initiative reaches them too. A member token acts for somebody
and is refused.

* ``GET /installation/config`` — the decrypted configuration: the guild-wide
  values an admin supplied, and the per-member values the app wrote back. The
  one place stored plaintext leaves.
* ``GET /installation/connections`` — the app's per-member connections, by
  opaque reference, with status only. ``/resolve`` turns a delegate's subject
  into the caller's own handle for that member.
* ``PUT /installation/connections/{connection_ref}`` — what a vendor flow
  produced, written back into the platform's custody.
* ``POST /installation/config-status`` — the app's verdict on the
  configuration it was handed.
* ``POST /installation/events`` — a third-party event, re-emitted through the
  dispatcher.

The token is checked by the install seam (``establish_install_access``),
whose standing statement admits the install only while it may act: the
community is in use, the install is on, and its registration is live. The
work itself runs on the system engine, routed into the community one install
at a time (:mod:`app.services.tenant.app_channels`).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import (
    CREDENTIAL_INSTALL,
    InstallAccessError,
    SessionDep,
    VerifiedInstall,
    establish_install_access,
    oauth2_scheme,
)
from app.core import audit_context
from app.core.app_access_token import (
    AccessTokenError,
    InstallAccessToken,
    is_access_token,
    unseal_access_token,
)
from app.core.messages import AppChannelMessages, AuthMessages
from app.db.session import clear_rls_context, get_system_session
from app.models.platform.app_service_registration import MAX_APP_ID_LENGTH
from app.models.tenant.guild_app import GuildApp
from app.models.tenant.guild_app_user_connection import CONNECTION_ID_LENGTH
from app.schemas.tenant.app_channel import (
    AppConnectionRead,
    AppConnectionsResponse,
    AppConnectionWrite,
    AppInstallConfigRead,
    AppInstallationEvent,
    AppStatusRead,
    AppStatusReport,
)
from app.services.marketplace import registration_lookup
from app.services.marketplace.app_refs import REF_MAX_LENGTH
from app.services.marketplace.registration_lookup import RegistrationSnapshot
from app.services.tenant import app_channels as channels_service
from app.services.tenant.app_channels import AppChannelError

# Not part of the OpenAPI document: only app containers call these, never the
# SPA, so the generated frontend client carries none of them.
router = APIRouter(prefix="/installation", include_in_schema=False)

SystemSessionDep = Annotated[AsyncSession, Depends(get_system_session)]


def _refuse() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=AuthMessages.COULD_NOT_VALIDATE_CREDENTIALS,
        headers={"WWW-Authenticate": "Bearer"},
    )


def _to_http(exc: AppChannelError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.code)


@dataclass(frozen=True)
class Installation:
    """The install an installation token names, admitted by the seam."""

    guild_id: int
    install_id: int
    registration: RegistrationSnapshot


async def installation_caller(
    request: Request,
    session: SessionDep,
    bearer: Annotated[Optional[str], Depends(oauth2_scheme)] = None,
) -> Installation:
    """The install the request's installation token names, or 401.

    The token is unsealed locally, then the seam computes the install's
    standing, which is what says it may act now. The request's own session is
    left unrouted afterwards: the work runs on the system engine.
    """
    if not bearer or not is_access_token(bearer):
        raise _refuse()
    try:
        token = unseal_access_token(bearer)
    except AccessTokenError as exc:
        raise _refuse() from exc
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
    return Installation(
        guild_id=context.guild_id,
        install_id=context.install_id,
        registration=registration,
    )


InstallationDep = Annotated[Installation, Depends(installation_caller)]


async def _load(
    session: AsyncSession, installation: Installation, *, for_write: bool = False
) -> GuildApp:
    return await channels_service.load_install(
        session,
        installation.registration,
        installation.guild_id,
        app_install_id=installation.install_id,
        for_write=for_write,
    )


@router.get("/config", response_model=AppInstallConfigRead)
async def read_installation_config(
    installation: InstallationDep, session: SystemSessionDep
) -> AppInstallConfigRead:
    """The decrypted configuration for this install.

    The guild-wide values an admin supplied, plus the per-member ones the app
    wrote back itself, each keyed by the opaque reference it knows that member
    by. Refused when the community has turned the app off.
    """
    try:
        app = await _load(session, installation)
        payload = await channels_service.config_payload(session, app)
    except AppChannelError as exc:
        raise _to_http(exc) from exc
    return AppInstallConfigRead(**payload)


@router.get("/connections", response_model=AppConnectionsResponse)
async def list_installation_connections(
    installation: InstallationDep, session: SystemSessionDep
) -> AppConnectionsResponse:
    """The app's per-member connections for this install, by opaque reference
    and with status only."""
    try:
        app = await _load(session, installation)
        rows = await channels_service.connection_payload(session, app)
    except AppChannelError as exc:
        raise _to_http(exc) from exc
    return AppConnectionsResponse(items=[AppConnectionRead(**row) for row in rows])


#: Which app minted the subject, by the public id its registration carries.
DelegateParam = Annotated[str, Query(min_length=1, max_length=MAX_APP_ID_LENGTH)]
#: The pairwise subject itself, bounded to the width the column stores.
SubjectParam = Annotated[str, Query(min_length=1, max_length=REF_MAX_LENGTH)]
#: Which of the install's connections is meant, by manifest id.
ConnectionParam = Annotated[Optional[str], Query(max_length=CONNECTION_ID_LENGTH)]


async def _delegated_member(guild_id: int, delegate: str, subject: str) -> int:
    """The member a delegate's subject names, in this community.

    Three questions, and the answer to any of them being no is the same
    refusal — see :func:`resolve_installation_connection`.
    """
    miss = AppChannelError(AppChannelMessages.CONNECTION_NOT_FOUND, status_code=404)
    if await registration_lookup.live_delegate(delegate) is None:
        raise miss
    user_id = await registration_lookup.resolve_delegated_member(
        guild_id, delegate, subject
    )
    if user_id is None:
        raise miss
    # Read at the moment it is used: a member who has withdrawn is no longer
    # someone this delegate may name.
    if not await registration_lookup.delegation_allowed(
        guild_id, delegate, user_id, need_write=False
    ):
        raise miss
    return user_id


# Declared ahead of the ``{connection_ref}`` route below, so a literal segment
# is matched before a parameterized one.
@router.get("/connections/resolve", response_model=AppConnectionRead)
async def resolve_installation_connection(
    installation: InstallationDep,
    delegate: DelegateParam,
    subject: SubjectParam,
    session: SystemSessionDep,
    connection: ConnectionParam = None,
) -> AppConnectionRead:
    """Turn a delegate's subject into the caller's own handle for that member.

    A delegation token names the member by a subject minted for the delegate,
    and the app it is presented to knows them by its own opaque reference. Only
    Initiative holds both, so this is where the two meet, and what comes back
    is a reference the caller already had.

    Three parties have to still be saying yes, all read now: the delegate is
    live and allowed to delegate; the subject was minted for that delegate's
    install in this community; and the member authorized that delegate to
    carry their name. Every miss answers ``404``.
    """
    try:
        app = await _load(session, installation)
        user_id = await _delegated_member(installation.guild_id, delegate, subject)
        row = await channels_service.connection_for_member(
            session, app, user_id=user_id, connection_id=connection
        )
    except AppChannelError as exc:
        raise _to_http(exc) from exc
    return AppConnectionRead(**row)


@router.put("/connections/{connection_ref}", response_model=AppConnectionRead)
async def write_installation_connection(
    connection_ref: str,
    payload: AppConnectionWrite,
    installation: InstallationDep,
    session: SystemSessionDep,
) -> AppConnectionRead:
    """Store what a vendor flow produced for one member's connection, or for
    the community-wide one.

    Refresh and first connect are the same call. Bounded to the fields the
    pinned manifest marked ``managed``; a connection a guild admin blocked is
    refused.
    """
    try:
        app = await _load(session, installation, for_write=True)
        row = await channels_service.write_connection_values(
            session,
            app,
            connection_ref=connection_ref,
            values=payload.values,
            status=payload.status,
            account_label=payload.account_label,
        )
    except AppChannelError as exc:
        raise _to_http(exc) from exc
    return AppConnectionRead(**row)


@router.post("/config-status", response_model=AppStatusRead)
async def report_installation_config_status(
    payload: AppStatusReport,
    installation: InstallationDep,
    session: SystemSessionDep,
) -> AppStatusRead:
    """Record whether the configuration this community supplied works.

    Only the vendor can confirm a credential carries the permissions it needs;
    this is how that answer reaches the admin who supplied it. An install
    nothing reports on stays ``unverified``.
    """
    try:
        app = await _load(session, installation, for_write=True)
        result = await channels_service.report_config_state(
            session, app, state=payload.state, detail=payload.detail
        )
    except AppChannelError as exc:
        raise _to_http(exc) from exc
    return AppStatusRead(**result)


@router.post("/events", status_code=status.HTTP_202_ACCEPTED)
async def ingest_installation_event(
    payload: AppInstallationEvent,
    installation: InstallationDep,
    session: SystemSessionDep,
) -> dict[str, str]:
    """Re-emit one third-party event into the community this install is in.

    The event type must be one the pinned definition declares, namespaced
    under the calling app. Answers ``202``: the event was handed to the
    dispatcher, and what subscribers do with it is not the emitting app's to
    know.
    """
    try:
        app = await _load(session, installation)
        await channels_service.emit_event(
            session,
            app,
            installation.registration,
            event_type=payload.event_type,
            payload=payload.payload,
        )
    except AppChannelError as exc:
        raise _to_http(exc) from exc
    return {"status": "accepted"}
