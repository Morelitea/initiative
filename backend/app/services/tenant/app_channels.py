"""What an app service may read and write about its own installs.

An app knows its installs by pulling them: which guilds have it, the
configuration each guild supplied, and which members connected their own
accounts. This module is the guild-touching half of that channel — the caller
has already been established from its signature
(:mod:`app.services.marketplace.app_channel_auth`), and everything here answers
in terms of *that* registration.

Three rules run through all of it:

* **An app only ever sees its own installs.** Every lookup is filtered by the
  registration's catalog uid *and* by the pinned definition naming that same
  app, so an install belonging to a different app is indistinguishable from one
  that does not exist.
* **Plaintext leaves in exactly one place.** :func:`config_payload` is the
  custody channel: it decrypts what the guild and its members stored and hands
  it to the app that needs it. The connections view carries status and nothing
  else, so an app reconciling who is connected never pulls credentials to do it.
* **People are addressed by reference.** Per-member rows are keyed by their
  opaque ``connection_ref``; no user id, email, or name is ever in a payload
  here.

Guild content lives in per-guild schemas, so every read routes the system-engine
session into one guild at a time as a guild admin — the app is acting with the
install's authority, and ``SET ROLE`` drops the system engine's bypass, so the
guild's own policies are what answer.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional, Sequence

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.messages import AppChannelMessages
from app.db.session import set_rls_context
from app.models.platform.app_service_registration import AppServiceRegistration
from app.models.platform.guild import Guild, GuildStatus
from app.models.tenant.guild_app import GuildApp
from app.models.tenant.guild_app_user_connection import GuildAppUserConnection
from app.services.marketplace.service_apps import ENDPOINT_ID_PREFIX
from app.services.tenant import app_config as app_config_service
from app.services.tenant.webhook_dispatcher import dispatch_event

logger = logging.getLogger(__name__)

__all__ = [
    "MAX_EVENT_PAYLOAD_BYTES",
    "AppChannelError",
    "config_payload",
    "connection_for_member",
    "connection_payload",
    "emit_event",
    "install_summaries",
    "load_install",
    "report_config_state",
    "write_connection_values",
]

#: What one event body may carry. An event is a notification that something
#: happened, not a data transfer — an app with more to say serves it from a data
#: source the platform fetches on demand.
MAX_EVENT_PAYLOAD_BYTES = 64 * 1024

#: The states an app may report about the configuration it was handed.
#: ``unverified`` is this build's resting value and is not something an app
#: asserts — it says nothing, or it says whether the credentials work.
REPORTABLE_CONFIG_STATES: frozenset[str] = frozenset({"ok", "invalid"})

#: Bound on the short code an app attaches to an ``invalid`` verdict, matching
#: the column it lands in.
MAX_CONFIG_STATE_DETAIL = 120


class AppChannelError(Exception):
    """A refusal on the app channel, as a message code plus its HTTP answer."""

    def __init__(self, code: str, status_code: int = 400) -> None:
        super().__init__(code)
        self.code = code
        self.status_code = status_code


# --- which installs are this app's ------------------------------------------


def _definition_service_id(definition: dict[str, Any] | None) -> Optional[str]:
    service = (definition or {}).get("service")
    if not isinstance(service, dict):
        return None
    public_id = service.get("public_id")
    return public_id if isinstance(public_id, str) else None


def owns_install(app: GuildApp, registration: AppServiceRegistration) -> bool:
    """Whether this install is the calling app's.

    Two independent statements have to agree: the install was made from the
    listing this registration speaks for, and the definition the guild pinned
    names this same app as its service. Either alone would be enough in the
    ordinary case; requiring both means a registration re-pointed at another
    listing still cannot reach installs it was not wired for.
    """
    if app.app_kind != "service":
        return False
    if not registration.listing_uid or app.listing_uid != registration.listing_uid:
        return False
    return _definition_service_id(app.definition) == registration.public_id


async def _guild_ids(session: AsyncSession) -> list[int]:
    """Every guild whose content this channel may reach, lowest id first.

    Suspended guilds are left out: a suspended guild's content is frozen for
    members and admins alike, and an app pulling for it would be reaching past
    a hold the operator put there. It reappears when the guild does.
    """
    await set_rls_context(session)
    rows = await session.exec(
        select(Guild.id, Guild.status)
        .where(Guild.status != GuildStatus.suspended.value)
        .order_by(Guild.id.asc())
    )
    return [row[0] for row in rows]


async def _route(session: AsyncSession, guild_id: int, *, read_only: bool) -> None:
    """Point the system-engine session at one guild, with the install's
    authority. ``SET ROLE`` drops the engine's bypass, so the guild's own
    policies decide from here; a frozen guild is routed to its SELECT-only role
    so no write can land in it whatever the caller asked for."""
    session.expunge_all()
    await set_rls_context(
        session, guild_id=guild_id, guild_role="admin", read_only=read_only
    )


async def _guild_row(session: AsyncSession, guild_id: int) -> Optional[Guild]:
    await set_rls_context(session)
    return (await session.exec(select(Guild).where(Guild.id == guild_id))).first()


async def install_summaries(
    session: AsyncSession, registration: AppServiceRegistration
) -> list[dict[str, Any]]:
    """Every guild that has this app installed, and at which version.

    Installs live in the guild schema that holds them — the catalog records what
    was published, never who installed it — so this visits each guild in turn.
    That cost tracks the number of guilds rather than the number of installs,
    which is the price of the catalog carrying no index of who installed what.

    A registration that has never verified names no listing, so it has no
    installs to report.
    """
    if not registration.listing_uid:
        return []

    summaries: list[dict[str, Any]] = []
    for guild_id in await _guild_ids(session):
        await _route(session, guild_id, read_only=True)
        rows = (
            await session.exec(
                select(GuildApp)
                .where(GuildApp.listing_uid == registration.listing_uid)
                .order_by(GuildApp.id.asc())
            )
        ).all()
        summaries.extend(
            _summarize(app) for app in rows if owns_install(app, registration)
        )
    return summaries


def _summarize(app: GuildApp) -> dict[str, Any]:
    """One install as the app is told about it.

    Ids and state only: which guild, which install, which version it is pinned
    to, and whether it is live. Nothing about who is in the guild, and nothing
    about what anyone configured — those are the config and connections
    channels, addressed one guild at a time.
    """
    state = app_config_service.config_state(app)
    return {
        "install_id": app.id,
        "guild_id": app.guild_id,
        "listing_uid": app.listing_uid,
        "listing_version": app.listing_version,
        "name": app.name,
        "enabled": app.enabled,
        "config_state": state.state,
        "config_state_detail": state.detail,
        "needs_config": state.needs_config,
        "updated_at": app.updated_at,
    }


async def load_install(
    session: AsyncSession,
    registration: AppServiceRegistration,
    guild_id: int,
    *,
    for_write: bool = False,
) -> GuildApp:
    """The calling app's install in one guild, with the session routed to it.

    Everything that is not this app's install answers the same way — a guild
    that does not exist, one that is suspended, one that never installed the
    app, and one that installed a different app are one refusal, because the
    caller is entitled to distinguish none of them.

    ``for_write`` refuses a guild the operator has frozen, so a write is turned
    away with a reason rather than failing against a read-only database role.
    """
    guild = await _guild_row(session, guild_id)
    if guild is None or guild.status == GuildStatus.suspended.value:
        raise AppChannelError(AppChannelMessages.INSTALL_NOT_FOUND, status_code=404)

    frozen = guild.status == GuildStatus.read_only.value
    if for_write and frozen:
        raise AppChannelError(AppChannelMessages.GUILD_READ_ONLY, status_code=409)

    await _route(session, guild_id, read_only=frozen or not for_write)
    if not registration.listing_uid:
        raise AppChannelError(AppChannelMessages.INSTALL_NOT_FOUND, status_code=404)

    app = (
        await session.exec(
            select(GuildApp).where(GuildApp.listing_uid == registration.listing_uid)
        )
    ).first()
    if app is None or not owns_install(app, registration):
        raise AppChannelError(AppChannelMessages.INSTALL_NOT_FOUND, status_code=404)
    if not app.enabled:
        # The guild's own kill switch, beside the operator's: the install stays
        # exactly as it is, and nothing flows through it until it is switched
        # back on. Every channel stops here, the credential pull included.
        raise AppChannelError(AppChannelMessages.INSTALL_DISABLED, status_code=409)
    return app


# --- the custody channel ----------------------------------------------------


async def config_payload(session: AsyncSession, app: GuildApp) -> dict[str, Any]:
    """The decrypted configuration for one install — the custody channel.

    This is the one place stored plaintext leaves the platform, and it goes only
    to the app that the values were supplied for. It carries both halves of what
    an app holds credentials for: the guild-wide values an admin typed, and the
    per-member values the app itself wrote back after a vendor flow, each keyed
    by the opaque reference the app knows that member by.

    Reading it here is what keeps custody real — the app caches in memory, and
    revoking, rotating, or uninstalling on this side means the next pull simply
    stops returning them.
    """
    connections: dict[str, dict[str, Any]] = {}
    for connection in app_config_service.definition_connections(app.definition):
        connection_id = connection.get("id")
        if not isinstance(connection_id, str):
            continue
        if connection.get("scope") != "static":
            # Per-member values are reported below, per connection reference —
            # there is no guild-wide value for a credential a vendor issued to
            # one person.
            continue
        values = dict((app.config or {}).get(connection_id) or {})
        values.update(
            app_config_service.decrypt_connection_secrets(
                (app.config_secrets or {}).get(connection_id) or {}
            )
        )
        if values:
            connections[connection_id] = values

    member_values = [
        {
            "connection_id": row.connection_id,
            "connection_ref": row.connection_ref,
            "status": row.status,
            "values": {
                **dict(row.config or {}),
                **app_config_service.decrypt_connection_secrets(row.config_secrets),
            },
        }
        for row in await _member_rows(session, app)
        if row.blocked_at is None
    ]

    state = app_config_service.config_state(app)
    return {
        "guild_id": app.guild_id,
        "install_id": app.id,
        "listing_uid": app.listing_uid,
        "listing_version": app.listing_version,
        "enabled": app.enabled,
        "config_state": state.state,
        "config_state_detail": state.detail,
        "needs_config": state.needs_config,
        "connections": connections,
        "member_connections": member_values,
    }


# --- who connected ----------------------------------------------------------


async def _member_rows(
    session: AsyncSession, app: GuildApp
) -> Sequence[GuildAppUserConnection]:
    return (
        await session.exec(
            select(GuildAppUserConnection)
            .where(GuildAppUserConnection.app_id == app.id)
            .order_by(
                GuildAppUserConnection.connection_id,
                GuildAppUserConnection.id,
            )
        )
    ).all()


async def connection_payload(
    session: AsyncSession, app: GuildApp
) -> list[dict[str, Any]]:
    """The app's per-member connections for one guild, by reference alone.

    Status and nothing more: an app reconciling which of its handles are still
    live does not need a credential to do it, and this view never carries one.
    Who the member is stays on this side — the reference is the whole of the
    app's name for them.
    """
    return [_connection_read(row) for row in await _member_rows(session, app)]


def _connection_read(row: GuildAppUserConnection) -> dict[str, Any]:
    """One connection as the app is told about it: which of its own
    connections, the handle to address it by, and where it has got to."""
    return {
        "connection_id": row.connection_id,
        "connection_ref": row.connection_ref,
        "status": row.status,
        "blocked": row.blocked_at is not None,
        "account_label": row.account_label,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


async def connection_for_member(
    session: AsyncSession,
    app: GuildApp,
    *,
    user_id: int,
    connection_id: Optional[str] = None,
) -> dict[str, Any]:
    """The handle this app knows one member's connection by.

    The reverse of every other route here: those address a member by the
    reference and never learn who it is, while this one starts from a member
    the platform resolved and answers with the reference — still the whole of
    the app's name for them. It is scoped to the install passed in, so what
    comes back is the caller's own handle and never another app's.

    Blocked rows are not answers. The block is what ended that member's access
    and the custody channel already stops serving their values, so a reference
    to one names nothing the app could act with.

    ``connection_id`` names which of the install's connections is meant. An
    install declaring one per-member connection needs no such statement; one
    declaring several is asked to make it.

    Which of those an install *is* comes from the pinned definition, never from
    how many rows a member happens to have: an app that declares two and gets an
    answer only because this member has connected one of them would start being
    refused the day they connect the other. The question a caller has to answer
    is a property of its own manifest, so it reads the same on every member.
    """
    target = connection_id or _sole_member_connection(app)
    row = (
        await session.exec(
            select(GuildAppUserConnection).where(
                GuildAppUserConnection.app_id == app.id,
                GuildAppUserConnection.user_id == user_id,
                GuildAppUserConnection.connection_id == target,
                GuildAppUserConnection.blocked_at.is_(None),
            )
        )
    ).first()
    if row is None:
        raise AppChannelError(AppChannelMessages.CONNECTION_NOT_FOUND, status_code=404)
    return _connection_read(row)


def _sole_member_connection(app: GuildApp) -> str:
    """The one per-member connection this install declares, or a refusal.

    An install declaring none has nothing a member could have connected, which
    is the same answer as a member who has not connected: not found.
    """
    declared = app_config_service.member_connection_ids(app.definition)
    if len(declared) == 1:
        return declared[0]
    if not declared:
        raise AppChannelError(AppChannelMessages.CONNECTION_NOT_FOUND, status_code=404)
    raise AppChannelError(AppChannelMessages.CONNECTION_UNSPECIFIED, status_code=422)


async def _row_by_ref(
    session: AsyncSession, app: GuildApp, connection_ref: str
) -> GuildAppUserConnection:
    row = (
        await session.exec(
            select(GuildAppUserConnection).where(
                GuildAppUserConnection.app_id == app.id,
                GuildAppUserConnection.connection_ref == connection_ref,
            )
        )
    ).first()
    if row is None:
        raise AppChannelError(AppChannelMessages.CONNECTION_NOT_FOUND, status_code=404)
    return row


# --- what an app reports back -----------------------------------------------


async def report_config_state(
    session: AsyncSession,
    app: GuildApp,
    *,
    state: str,
    detail: Optional[str] = None,
) -> dict[str, Any]:
    """Record the app's verdict on the configuration it was given.

    Presence of values is all this build can know by itself; whether a
    credential carries the permissions it needs is something only the vendor can
    confirm, and this is how that answer gets back to the admin who pasted it.
    An app that never reports leaves the install ``unverified`` — nothing blocks
    on the round trip.
    """
    if state not in REPORTABLE_CONFIG_STATES:
        raise AppChannelError(AppChannelMessages.INVALID_CONFIG_STATE)
    cleaned = (detail or "").strip() or None
    if cleaned is not None and len(cleaned) > MAX_CONFIG_STATE_DETAIL:
        raise AppChannelError(AppChannelMessages.INVALID_CONFIG_STATE)
    if state == "ok":
        # A verdict of "working" carries no complaint to display beside it.
        cleaned = None

    app.config_state = state
    app.config_state_detail = cleaned
    app.updated_at = datetime.now(timezone.utc)
    session.add(app)
    await session.commit()
    await session.refresh(app)
    return {
        "guild_id": app.guild_id,
        "install_id": app.id,
        "config_state": app.config_state,
        "config_state_detail": app.config_state_detail,
    }


async def write_connection_values(
    session: AsyncSession,
    app: GuildApp,
    *,
    connection_ref: str,
    values: dict[str, Any],
    status: Optional[str] = None,
    account_label: Optional[str] = None,
) -> dict[str, Any]:
    """Store what a vendor flow produced.

    The app runs the flow at its own URL and writes the result here, which is
    what makes Initiative the custodian of a credential the app obtained: the
    same path serves a refresh, so a token rotated at 03:00 is still revocable
    at 03:05. Only fields the manifest marked ``managed`` may be written this
    way — everything else on a connection is typed by a person.

    The handle says which of two things is being written. A ref this install
    minted for one of its own guild-wide connections is the credential the whole
    guild uses, and it lives on the install row; anything else is looked up
    among the per-member rows. An app cannot confuse them, because it never
    invents a ref: it is handed one, and one nobody minted resolves to neither.

    A connection an admin blocked is refused: the block exists precisely to stop
    that member's access coming back.
    """
    guild_connection = app_config_service.connection_id_for_ref(app, connection_ref)
    if guild_connection is not None:
        return await _write_guild_connection(
            session,
            app,
            connection_id=guild_connection,
            connection_ref=connection_ref,
            values=values,
        )

    row = await _row_by_ref(session, app, connection_ref)
    if row.blocked_at is not None:
        raise AppChannelError(AppChannelMessages.CONNECTION_BLOCKED, status_code=403)

    connection = app_config_service.connection_by_id(app.definition, row.connection_id)
    if connection is None:
        # The install moved to a version that no longer declares this
        # connection; its values are on their way out with it.
        raise AppChannelError(AppChannelMessages.CONNECTION_NOT_FOUND, status_code=404)

    try:
        config, secrets = app_config_service.apply_connection_values(
            connection,
            values,
            current=row.config or {},
            current_secrets=row.config_secrets or {},
            allow_managed=True,
        )
    except app_config_service.AppConfigError as exc:
        raise AppChannelError(exc.code) from exc

    row.config = config
    row.config_secrets = secrets
    if account_label is not None:
        label = account_label.strip()
        row.account_label = label or None
    row.status = _resolved_status(status, config=config, secrets=secrets)
    row.updated_at = datetime.now(timezone.utc)
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return {
        "connection_id": row.connection_id,
        "connection_ref": row.connection_ref,
        "status": row.status,
        "blocked": row.blocked_at is not None,
        "account_label": row.account_label,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


async def _write_guild_connection(
    session: AsyncSession,
    app: GuildApp,
    *,
    connection_id: str,
    connection_ref: str,
    values: dict[str, Any],
) -> dict[str, Any]:
    """Store what an admin's vendor flow produced for the whole guild.

    The same custody as a member's, one row up: the values land on the install
    beside the ones an admin types, so clearing the connection, uninstalling the
    app or moving to a version that no longer declares it take this with them.

    Two arguments the member path has are absent here, and their absence is the
    point rather than an omission. A ``status`` is not one of them, because a
    guild connection has no row of its own to hold one — what it holds is
    values, and whether they add up to a working connection is read off them
    wherever it is asked. And there is no ``account_label``: a member's is the
    only way an admin can see whose account was connected without being shown
    the credential, whereas a guild connection's non-secret values are already
    visible to the admin who governs it, so the vendor account belongs in a
    field the manifest declares rather than in a label beside one.
    """
    connection = app_config_service.connection_by_id(app.definition, connection_id)
    if connection is None:
        # The install moved to a version that no longer declares this
        # connection; its values are on their way out with it.
        raise AppChannelError(AppChannelMessages.CONNECTION_NOT_FOUND, status_code=404)

    try:
        config, secrets = app_config_service.apply_connection_values(
            connection,
            values,
            current=(app.config or {}).get(connection_id) or {},
            current_secrets=(app.config_secrets or {}).get(connection_id) or {},
            allow_managed=True,
        )
    except app_config_service.AppConfigError as exc:
        raise AppChannelError(exc.code) from exc

    # An emptied connection is stored as absent rather than as an empty map, so
    # "has anything been configured here?" has one shape — the same rule the
    # pruning and the admin's own form already keep.
    app.config = _stored(app.config, connection_id, config)
    app.config_secrets = _stored(app.config_secrets, connection_id, secrets)
    app.updated_at = datetime.now(timezone.utc)
    session.add(app)
    await session.commit()
    await session.refresh(app)

    return {
        "connection_id": connection_id,
        "connection_ref": connection_ref,
        "status": "connected"
        if app_config_service.is_satisfied(connection, config, secrets)
        else "pending",
        "blocked": False,
        "account_label": None,
        "created_at": app.created_at,
        "updated_at": app.updated_at,
    }


def _stored(
    current: dict[str, Any] | None, connection_id: str, values: dict[str, Any]
) -> dict[str, Any]:
    kept = {
        key: value for key, value in (current or {}).items() if key != connection_id
    }
    if values:
        kept[connection_id] = values
    return kept


def _resolved_status(
    requested: Optional[str], *, config: dict[str, Any], secrets: dict[str, Any]
) -> str:
    """What a connection's status becomes after a write-back.

    An app may say it is still mid-flow; otherwise the stored values decide, so
    a write that clears everything leaves the row honest rather than claiming a
    connection it no longer holds.
    """
    if requested == "pending":
        return "pending"
    return "connected" if (config or secrets) else "pending"


# --- events in --------------------------------------------------------------


def _payload_size(payload: dict[str, Any]) -> int:
    try:
        encoded = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise AppChannelError(AppChannelMessages.INVALID_PAYLOAD) from exc
    return len(encoded.encode("utf-8"))


async def emit_event(
    session: AsyncSession,
    app: GuildApp,
    registration: AppServiceRegistration,
    *,
    event_type: str,
    payload: dict[str, Any],
) -> None:
    """Re-emit a third-party event into this guild's own dispatcher.

    The app has verified the third party's signature and worked out which of its
    installs the event belongs to; what this adds is the platform's half —
    the type is an `emit` endpoint the *pinned* definition declares, namespaced
    under the calling app, and the guild has that app installed and enabled.

    `emit` and not merely declared: reads and writes share the id space, and an
    app that could announce under a read's id would be emitting something a
    subscriber has no way to have asked for.

    From there it is an ordinary event: the existing dispatcher delivers it to
    whatever the automation delegate subscribed to. Delivery targets are the
    delegate's to own, which is why this is one-way — apps emit, and never
    subscribe.
    """
    definition = app.definition if isinstance(app.definition, dict) else {}
    declared = definition.get("endpoints")
    prefix = f"{ENDPOINT_ID_PREFIX}{registration.public_id}."
    emitted = (
        {
            endpoint.get("id")
            for endpoint in declared
            if isinstance(endpoint, dict) and endpoint.get("direction") == "emit"
        }
        if isinstance(declared, list)
        else set()
    )
    if event_type not in emitted or not event_type.startswith(prefix):
        raise AppChannelError(AppChannelMessages.UNKNOWN_EVENT_TYPE)

    if _payload_size(payload) > MAX_EVENT_PAYLOAD_BYTES:
        raise AppChannelError(AppChannelMessages.EVENT_TOO_LARGE, status_code=413)

    await dispatch_event(
        session,
        event_type=event_type,
        guild_id=app.guild_id,
        payload=payload,
    )
