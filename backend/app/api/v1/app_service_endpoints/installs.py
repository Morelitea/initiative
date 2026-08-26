"""An app service reading and reporting on its own installs.

Four channels, and the split between them is the point:

* **``/installs``** says where the app is installed and nothing else. It is what
  an app reconciles against — an install that has disappeared from this list is
  one whose credentials the app must let go of.
* **``/installs/{guild_id}/config``** is the custody channel. Initiative holds
  the credentials; the app that uses them pulls them here, over its own
  authenticated connection, and caches them in memory. Every refusal on this
  route — the operator's kill switch, the guild's own switch, an install that
  is not this app's — stops that pull immediately, which is what makes revoking
  real rather than advisory.
* **``/installs/{guild_id}/connections``** reports which per-member handles are
  live, by reference, carrying no values at all. Its ``/resolve`` leg answers
  the one question a delegated call needs: which of those handles belongs to
  the member a delegate's token named.
* **``/installs/{guild_id}/status``** is the app answering the one question this
  build cannot: whether the credentials it was given actually work.

The guild is named in the path because one app serves many. The *app* is never
named in a payload — it is established from the request signature before any of
this runs.
"""

from __future__ import annotations

from typing import Annotated, Optional

from fastapi import APIRouter, Query, Request

from app.api.v1.app_service_endpoints.deps import (
    AdminSessionDep,
    CallerDep,
    parse_body,
    to_http,
)
from app.core.messages import AppChannelMessages
from app.schemas.tenant.app_channel import (
    AppConnectionRead,
    AppConnectionsResponse,
    AppConnectionWrite,
    AppInstallConfigRead,
    AppInstallRead,
    AppInstallsResponse,
    AppStatusRead,
    AppStatusReport,
)
from app.models.tenant.guild_app_user_connection import CONNECTION_ID_LENGTH
from app.services.marketplace import registration_lookup
from app.services.marketplace.app_channel_auth import MAX_APP_ID_LENGTH
from app.services.marketplace.app_subjects import SUBJECT_LENGTH
from app.services.tenant import app_channels as channels_service
from app.services.tenant.app_channels import AppChannelError

# Paths are declared without a trailing slash: a caller signs the path it sends,
# so a redirect to a canonical spelling would arrive carrying a signature over
# the other one.
router = APIRouter(prefix="/installs")


@router.get("", response_model=AppInstallsResponse)
async def list_installs(
    session: AdminSessionDep, caller: CallerDep
) -> AppInstallsResponse:
    """Every guild that has this app installed, and at which pinned version.

    The source of truth an app reconciles against. Installs live in the guild
    schema that holds them — the catalog records what was published, never who
    installed it — so this walks the guilds this deployment has and reports the
    ones whose install belongs to the calling app.
    """
    summaries = await channels_service.install_summaries(session, caller.registration)
    return AppInstallsResponse(
        items=[AppInstallRead(**summary) for summary in summaries]
    )


@router.get("/{guild_id}/config", response_model=AppInstallConfigRead)
async def read_install_config(
    guild_id: int, session: AdminSessionDep, caller: CallerDep
) -> AppInstallConfigRead:
    """The decrypted configuration for one install.

    The one route in this build that returns stored plaintext, and it returns it
    only to the app the values were supplied for: the guild-wide credentials an
    admin typed, plus the per-member ones the app wrote back itself, each keyed
    by the opaque reference it knows that member by.

    Refused when the operator has turned the registration off, when the guild
    has turned the app off, or when the install is not this app's — an app whose
    access ended stops being able to pull at that moment.
    """
    try:
        app = await channels_service.load_install(
            session, caller.registration, guild_id
        )
        payload = await channels_service.config_payload(session, app)
    except AppChannelError as exc:
        raise to_http(exc) from exc
    return AppInstallConfigRead(**payload)


@router.get("/{guild_id}/connections", response_model=AppConnectionsResponse)
async def list_install_connections(
    guild_id: int, session: AdminSessionDep, caller: CallerDep
) -> AppConnectionsResponse:
    """The app's per-member connections for one guild.

    Addressed by opaque reference and carrying status only. An app matching its
    stored credentials against what the platform still holds does not need a
    value to do it, and this route has none to give.
    """
    try:
        app = await channels_service.load_install(
            session, caller.registration, guild_id
        )
        rows = await channels_service.connection_payload(session, app)
    except AppChannelError as exc:
        raise to_http(exc) from exc
    return AppConnectionsResponse(items=[AppConnectionRead(**row) for row in rows])


#: Which app minted the subject, by the public id its registration carries.
DelegateParam = Annotated[str, Query(min_length=1, max_length=MAX_APP_ID_LENGTH)]
#: The pairwise subject itself, bounded to the width the column stores so an
#: oversized value is refused before it reaches a lookup.
SubjectParam = Annotated[str, Query(min_length=1, max_length=SUBJECT_LENGTH)]
#: Which of the install's connections is meant, by manifest id.
ConnectionParam = Annotated[Optional[str], Query(max_length=CONNECTION_ID_LENGTH)]


async def _delegated_member(guild_id: int, delegate: str, subject: str) -> int:
    """The member a delegate's subject names, in this guild.

    Three questions, and the answer to any of them being no is the same
    refusal — see :func:`resolve_delegated_connection`.
    """
    miss = AppChannelError(AppChannelMessages.CONNECTION_NOT_FOUND, status_code=404)
    if await registration_lookup.live_delegate(delegate) is None:
        raise miss
    user_id = await registration_lookup.resolve_delegated_member(
        guild_id, delegate, subject
    )
    if user_id is None:
        raise miss
    # Read at the moment it is used rather than taken from the subject having
    # been minted: a member who has withdrawn is no longer someone this
    # delegate may name.
    if not await registration_lookup.delegation_allowed(
        guild_id, delegate, user_id, need_write=False
    ):
        raise miss
    return user_id


# Declared ahead of the ``{connection_ref}`` route below: the two differ by
# method today, but a literal segment has to be matched before a parameterized
# one or a request for ``resolve`` is read as a reference spelled that way.
@router.get("/{guild_id}/connections/resolve", response_model=AppConnectionRead)
async def resolve_delegated_connection(
    guild_id: int,
    delegate: DelegateParam,
    subject: SubjectParam,
    session: AdminSessionDep,
    caller: CallerDep,
    connection: ConnectionParam = None,
) -> AppConnectionRead:
    """Turn a delegate's subject into the caller's own handle for that member.

    Two apps hold an identifier for the same person and neither can turn one
    into the other: a delegation token names the member by a subject minted for
    the delegate, and the app it is presented to knows them by its own opaque
    reference. Only Initiative holds both, so this is where the two meet — and
    what comes back is a reference the caller already had, never a name, an
    address, or anything that correlates with what another app was told.

    Three parties have to still be saying yes, and all three are read now
    rather than taken from anything the caller presented:

    * the delegate is one this deployment runs, switched on, and allowed to
      delegate — the same rule that decides which keys verify its tokens;
    * the subject was minted for **that** delegate's install in this guild;
    * the member authorized that delegate to carry their name.

    Every miss answers ``404``. "No such subject", "that member has not
    connected", and "that delegate is switched off" are this deployment's own
    wiring, and the caller has established nothing about the person it is
    asking after.
    """
    try:
        app = await channels_service.load_install(
            session, caller.registration, guild_id
        )
        user_id = await _delegated_member(guild_id, delegate, subject)
        row = await channels_service.connection_for_member(
            session, app, user_id=user_id, connection_id=connection
        )
    except AppChannelError as exc:
        raise to_http(exc) from exc
    return AppConnectionRead(**row)


@router.put(
    "/{guild_id}/connections/{connection_ref}", response_model=AppConnectionRead
)
async def write_install_connection(
    guild_id: int,
    connection_ref: str,
    request: Request,
    session: AdminSessionDep,
    caller: CallerDep,
) -> AppConnectionRead:
    """Store what a vendor flow produced for one member's connection.

    The app runs the flow at its own URL — its callback is its own domain, which
    is what vendors register — and writes the result back here. That is what
    keeps custody on this side: a token rotated at 03:00 through this same route
    is still revocable at 03:05. Refresh and first connect are the same call.

    Bounded to the fields the pinned manifest marked ``managed``; a connection a
    guild admin blocked is refused, since stopping that member's access is
    precisely what the block was for.
    """
    payload = parse_body(request, AppConnectionWrite)
    try:
        app = await channels_service.load_install(
            session, caller.registration, guild_id, for_write=True
        )
        row = await channels_service.write_connection_values(
            session,
            app,
            connection_ref=connection_ref,
            values=payload.values,
            status=payload.status,
            account_label=payload.account_label,
        )
    except AppChannelError as exc:
        raise to_http(exc) from exc
    return AppConnectionRead(**row)


@router.post("/{guild_id}/status", response_model=AppStatusRead)
async def report_install_status(
    guild_id: int,
    request: Request,
    session: AdminSessionDep,
    caller: CallerDep,
) -> AppStatusRead:
    """Record whether the configuration this guild supplied actually works.

    Presence of values is what this build can know by itself; whether a
    credential carries the permissions it needs is something only the vendor can
    confirm. This is how that answer reaches the admin who pasted the token —
    an install nothing reports on simply stays ``unverified``, and nothing
    blocks waiting for it.
    """
    payload = parse_body(request, AppStatusReport)
    try:
        app = await channels_service.load_install(
            session, caller.registration, guild_id, for_write=True
        )
        result = await channels_service.report_config_state(
            session, app, state=payload.state, detail=payload.detail
        )
    except AppChannelError as exc:
        raise to_http(exc) from exc
    return AppStatusRead(**result)
