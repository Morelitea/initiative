"""What an app service may read and write about its own installs.

An app knows its installs by pulling them: the configuration each guild
supplied, and which members connected their own accounts. This module is the
guild-touching half of those calls — the caller has already been established
from its installation token (``/plugin-platform/installation/*``), and everything
here answers in terms of *that* registration and install.

Three rules run through all of it:

* **An app only ever sees its own installs.** Every lookup is filtered by the
  registration's catalog uid *and* by the pinned definition naming that same
  app, so an install belonging to a different app is indistinguishable from one
  that does not exist.
* **Plaintext leaves in two places.** :func:`config_payload` decrypts what the
  community typed and the managed values each connection's flow produced, and
  never a flow's tokens; :func:`connection_token` hands out one usable access
  token by reference, refreshing or minting it first. The connections view
  carries status and nothing else, so an app reconciling who is connected
  never pulls credentials to do it.
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
from typing import Any, Optional, Protocol, Sequence

from sqlalchemy import func, text
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.session import routed_guild_id
from app.core.messages import PluginChannelMessages
from app.db.event_capture import OUTBOX_CHANNEL
from app.db.session import set_rls_context
from app.models.platform.guild import LIVE_STATUS_VALUES, Guild, CommunityStatus
from app.models.tenant.plugin_event_outbox import PluginEventOutbox
from app.models.tenant.guild_plugin import GuildPlugin
from app.models.tenant.guild_plugin_user_connection import GuildPluginUserConnection
from app.services.marketplace.plugin_refs import ensure_plugin_guild_ref
from app.services.marketplace.registration_lookup import service_public_id
from app.services.marketplace.service_plugins import (
    CONNECTION_STATES,
    ENDPOINT_ID_PREFIX,
)
from app.services.tenant import plugin_config as plugin_config_service
from app.services.tenant import plugin_connection_flows as flows
from app.services.tenant import guild_plugins as guild_plugins_service
from app.db.request_context import SystemGuild, Unattributed

logger = logging.getLogger(__name__)

__all__ = [
    "MAX_EVENT_PAYLOAD_BYTES",
    "PluginChannelError",
    "config_payload",
    "connection_payload",
    "connection_token",
    "emit_event",
    "keep_event",
    "load_install",
    "report_config_state",
    "set_connection_state",
]

#: What one event body may carry. An event is a notification that something
#: happened, not a data transfer — an app with more to say serves it from a data
#: source the platform fetches on demand.
MAX_EVENT_PAYLOAD_BYTES = 8 * 1024

#: The states an app may report about the configuration it was handed.
#: ``unverified`` is this build's resting value and is not something an app
#: asserts — it says nothing, or it says whether the credentials work.
REPORTABLE_CONFIG_STATES: frozenset[str] = frozenset({"ok", "invalid"})

#: Bound on the short code an app attaches to an ``invalid`` verdict, matching
#: the column it lands in.
MAX_CONFIG_STATE_DETAIL = 120


class RegisteredPlugin(Protocol):
    """What these calls read of the caller's registration: its id and the
    listing it speaks for. The registration snapshot carries both."""

    public_id: str
    listing_uid: Optional[str]


class PluginChannelError(Exception):
    """A refusal on the app channel, as a message code plus its HTTP answer."""

    def __init__(self, code: str, status_code: int = 400) -> None:
        super().__init__(code)
        self.code = code
        self.status_code = status_code


# --- which installs are this app's ------------------------------------------


def owns_install(app: GuildPlugin, registration: RegisteredPlugin) -> bool:
    """Whether this install is the calling app's.

    Two independent statements have to agree: the install was made from the
    listing this registration speaks for, and the definition the guild pinned
    names this same app as its service. Either alone would be enough in the
    ordinary case; requiring both means a registration re-pointed at another
    listing still cannot reach installs it was not wired for. A declarative
    app names no service: it is its listing's, so the listing is the one
    statement there is.
    """
    if app.plugin_kind != "service":
        return False
    if not registration.listing_uid or app.listing_uid != registration.listing_uid:
        return False
    return (
        service_public_id(app.definition, listing_public_id=registration.public_id)
        == registration.public_id
    )


async def _route(session: AsyncSession, guild_id: int, *, read_only: bool) -> None:
    """Point the system-engine session at one guild, with the install's
    authority. ``SET ROLE`` drops the engine's bypass, so the guild's own
    policies decide from here; a frozen guild is routed to its SELECT-only role
    so no write can land in it whatever the caller asked for."""
    session.expunge_all()
    await set_rls_context(session, SystemGuild(guild_id, read_only=read_only))


async def _install_guild_ref(session: AsyncSession, app: GuildPlugin) -> str:
    """What this install calls the guild it is in.

    Every payload on this channel names the guild by it, because it is the only
    name the app on the other end has for it. The community is the one the
    session read the install from.
    """
    return await ensure_plugin_guild_ref(
        guild_id=routed_guild_id(session), plugin_install_id=app.id
    )


async def _guild_row(session: AsyncSession, guild_id: int) -> Optional[Guild]:
    await set_rls_context(session, Unattributed())
    return (await session.exec(select(Guild).where(Guild.id == guild_id))).first()


async def load_install(
    session: AsyncSession,
    registration: RegisteredPlugin,
    guild_id: int,
    *,
    plugin_install_id: int,
    for_write: bool = False,
) -> GuildPlugin:
    """The calling app's install in one guild, with the session routed to it.
    ``session`` is a system session from that guild's cohort, as
    ``get_system_session`` hands one to an installation token's request.

    ``plugin_install_id`` is the install the caller's reference named, and the one
    found here has to be it. A guild that removed this app and added it again
    holds a different install, and a reference minted against the first names
    only the first — so the check is what keeps the reference specific rather
    than standing for whatever this app's install in that guild happens to be.

    Everything that is not this app's install answers the same way — a guild
    that does not exist, one that is suspended, one that never installed the
    app, one that installed a different app, and one whose install has been
    replaced are one refusal, because the caller is entitled to distinguish
    none of them.

    ``for_write`` refuses a guild the operator has frozen, so a write is turned
    away with a reason rather than failing against a read-only database role.
    """
    guild = await _guild_row(session, guild_id)
    if guild is None or guild.status not in LIVE_STATUS_VALUES:
        raise PluginChannelError(PluginChannelMessages.INSTALL_NOT_FOUND, status_code=404)

    frozen = guild.status == CommunityStatus.read_only.value
    if for_write and frozen:
        raise PluginChannelError(PluginChannelMessages.GUILD_READ_ONLY, status_code=409)

    await _route(session, guild_id, read_only=frozen or not for_write)
    if not registration.listing_uid:
        raise PluginChannelError(PluginChannelMessages.INSTALL_NOT_FOUND, status_code=404)

    app = (
        await session.exec(
            select(GuildPlugin).where(GuildPlugin.listing_uid == registration.listing_uid)
        )
    ).first()
    if app is None or not owns_install(app, registration):
        raise PluginChannelError(PluginChannelMessages.INSTALL_NOT_FOUND, status_code=404)
    if app.id != plugin_install_id:
        raise PluginChannelError(PluginChannelMessages.INSTALL_NOT_FOUND, status_code=404)
    if not app.enabled:
        # The guild's own kill switch, beside the operator's: the install stays
        # exactly as it is, and nothing flows through it until it is switched
        # back on. Every channel stops here, the credential pull included.
        raise PluginChannelError(PluginChannelMessages.INSTALL_DISABLED, status_code=409)
    return app


# --- the custody channel ----------------------------------------------------


async def config_payload(session: AsyncSession, app: GuildPlugin) -> dict[str, Any]:
    """The decrypted configuration for one install.

    It carries both halves of what an app is configured with: the guild-wide
    values (typed by an admin, or returned by a flow's ``after_connect``) and
    each member's managed values, keyed by the opaque reference the app knows
    that member by. A flow's tokens are never in it: the app asks for one with
    :func:`connection_token` when it needs it.
    """
    connections: dict[str, dict[str, Any]] = {}
    connection_refs: dict[str, str] = {}
    secrets = await guild_plugins_service.load_secrets(session, app)
    for connection in plugin_config_service.definition_connections(app.definition):
        connection_id = connection.get("id")
        if not isinstance(connection_id, str):
            continue
        if connection.get("scope") != "static":
            # Per-member values are reported below, per connection reference —
            # there is no guild-wide value for a credential a vendor issued to
            # one person.
            continue
        values = plugin_config_service.without_tokens(
            (app.config or {}).get(connection_id)
        )
        values.update(
            plugin_config_service.decrypt_connection_secrets(
                plugin_config_service.without_tokens(secrets.get(connection_id))
            )
        )
        if values:
            connections[connection_id] = values
        ref = (app.connection_refs or {}).get(connection_id)
        if isinstance(ref, str) and ref:
            connection_refs[connection_id] = ref

    member_values = [
        {
            "connection_id": row.connection_id,
            "connection_ref": row.connection_ref,
            "status": row.status,
            "values": {
                **plugin_config_service.without_tokens(row.config),
                **plugin_config_service.decrypt_connection_secrets(
                    plugin_config_service.without_tokens(row.config_secrets)
                ),
            },
        }
        for row in await _member_rows(session, app)
        if row.blocked_at is None
    ]

    state = plugin_config_service.config_state(app)
    return {
        "community_ref": await _install_guild_ref(session, app),
        "install_id": app.id,
        "listing_uid": app.listing_uid,
        "listing_version": app.listing_version,
        "enabled": app.enabled,
        "config_state": state.state,
        "config_state_detail": state.detail,
        "needs_config": state.needs_config,
        "connections": connections,
        "connection_refs": connection_refs,
        "member_connections": member_values,
    }


async def connection_token(
    session: AsyncSession,
    app: GuildPlugin,
    registration: RegisteredPlugin,
    *,
    connection_ref: str,
) -> dict[str, Any]:
    """One usable access token for a connection of this install, by its ref.

    A member's connection must be connected and not blocked; its token is
    refreshed when it is close to expiring, once however many ask at once, and
    a refresh the vendor refuses leaves the connection ``expired``. A guild-wide
    connection answers its ``jwt_bearer`` token, or its own stored token.
    """
    try:
        guild_connection = plugin_config_service.connection_id_for_ref(app, connection_ref)
        if guild_connection is not None:
            tokens = await flows.community_token(
                session,
                app=app,
                public_id=registration.public_id,
                connection_id=guild_connection,
                guild_id=routed_guild_id(session),
            )
        else:
            member = await flows.member_token(
                session,
                app=app,
                public_id=registration.public_id,
                connection_ref=connection_ref,
                guild_id=routed_guild_id(session),
            )
            if member is None:
                raise PluginChannelError(
                    PluginChannelMessages.CONNECTION_NOT_FOUND, status_code=404
                )
            tokens = member
    except flows.ConnectionFlowError as exc:
        raise PluginChannelError(exc.code, status_code=exc.status_code) from exc
    return flows.token_response(tokens)


# --- who connected ----------------------------------------------------------


async def _member_rows(
    session: AsyncSession, app: GuildPlugin
) -> Sequence[GuildPluginUserConnection]:
    return (
        await session.exec(
            select(GuildPluginUserConnection)
            .where(GuildPluginUserConnection.plugin_id == app.id)
            .order_by(
                GuildPluginUserConnection.connection_id,
                GuildPluginUserConnection.id,
            )
        )
    ).all()


async def connection_payload(
    session: AsyncSession, app: GuildPlugin
) -> list[dict[str, Any]]:
    """The app's per-member connections for one guild, by reference alone.

    Status and nothing more: an app reconciling which of its handles are still
    live does not need a credential to do it, and this view never carries one.
    Who the member is stays on this side — the reference is the whole of the
    app's name for them.
    """
    return [_connection_read(row) for row in await _member_rows(session, app)]


def _connection_read(row: GuildPluginUserConnection) -> dict[str, Any]:
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


# --- what an app reports back -----------------------------------------------


async def report_config_state(
    session: AsyncSession,
    app: GuildPlugin,
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
        raise PluginChannelError(PluginChannelMessages.INVALID_CONFIG_STATE)
    cleaned = (detail or "").strip() or None
    if cleaned is not None and len(cleaned) > MAX_CONFIG_STATE_DETAIL:
        raise PluginChannelError(PluginChannelMessages.INVALID_CONFIG_STATE)
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
        "community_ref": await _install_guild_ref(session, app),
        "install_id": app.id,
        "config_state": app.config_state,
        "config_state_detail": app.config_state_detail,
    }


def set_connection_state(app: GuildPlugin, connection_id: str, state: str) -> bool:
    """Record what a declarative app learned of one connection at the vendor
    (a delivery's ``status``, or its health check) as the install's
    configuration state, where a container's verdict is shown. Answers whether
    it moved; the caller writes it.

    A state other than ``ok`` is ``invalid``, its detail the connection and
    the state (``workspace_suspended``). ``ok`` clears a verdict about this
    connection and leaves one about another as it is.
    """
    about = {f"{connection_id}_{other}" for other in CONNECTION_STATES if other != "ok"}
    if state == "ok":
        if app.config_state == "invalid" and app.config_state_detail not in about:
            return False
        verdict: tuple[str, Optional[str]] = ("ok", None)
    else:
        verdict = ("invalid", f"{connection_id}_{state}")
    if (app.config_state, app.config_state_detail) == verdict:
        return False
    app.config_state, app.config_state_detail = verdict
    app.updated_at = datetime.now(timezone.utc)
    return True


# --- events in --------------------------------------------------------------


def _payload_size(payload: dict[str, Any]) -> int:
    try:
        encoded = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise PluginChannelError(PluginChannelMessages.INVALID_PAYLOAD) from exc
    return len(encoded.encode("utf-8"))


async def emit_event(
    session: AsyncSession,
    app: GuildPlugin,
    registration: RegisteredPlugin,
    *,
    event_type: str,
    payload: dict[str, Any],
    initiative_id: Optional[int],
    token_initiative_id: Optional[int],
) -> None:
    """Keep one event the app emits (:func:`keep_event`), and commit it."""
    await keep_event(
        session,
        app,
        registration,
        event_type=event_type,
        payload=payload,
        initiative_id=initiative_id,
        token_initiative_id=token_initiative_id,
    )
    await session.commit()


async def keep_event(
    session: AsyncSession,
    app: GuildPlugin,
    registration: RegisteredPlugin,
    *,
    event_type: str,
    payload: dict[str, Any],
    initiative_id: Optional[int],
    token_initiative_id: Optional[int] = None,
) -> None:
    """Keep one event an app emits, for the outbox poller to deliver: a
    container's, or one a declarative app's webhook mapping emits.

    The type is an ``emit`` endpoint the *pinned* definition declares,
    namespaced under the emitting app. `emit` and not merely declared: reads
    and writes share the id space, and an app that could announce under a
    read's id would be emitting something a subscriber has no way to have
    asked for.

    An event about an initiative names one the install is placed in; a token
    narrowed to an initiative emits in that one. The row is written in the
    caller's transaction, which wakes the outbox drain as a captured change
    does once it commits, and the poller delivers it to the community's
    subscriptions with the change log, retrying until each accepts it.
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
        raise PluginChannelError(PluginChannelMessages.UNKNOWN_EVENT_TYPE)

    if _payload_size(payload) > MAX_EVENT_PAYLOAD_BYTES:
        raise PluginChannelError(PluginChannelMessages.EVENT_TOO_LARGE, status_code=413)

    if initiative_id is None:
        initiative_id = token_initiative_id
    if initiative_id is not None and (
        token_initiative_id not in (None, initiative_id)
        or not await guild_plugins_service.is_placed(session, app.id, initiative_id)
    ):
        raise PluginChannelError(PluginChannelMessages.INITIATIVE_NOT_PLACED, status_code=403)

    session.add(
        PluginEventOutbox(
            txn_id=func.txid_current(),
            install_id=app.id,
            event_type=event_type,
            initiative_id=initiative_id,
            payload=payload,
        )
    )
    # The same hint the capture trigger raises, heard once this commits.
    await session.exec(
        text(
            "SELECT pg_notify(:channel, current_schema() || ':' || txid_current())"
        ).bindparams(channel=OUTBOX_CHANNEL)
    )
