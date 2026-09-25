"""What an app service may read and write about its own installs.

An app knows its installs by pulling them: the configuration each guild
supplied, and which members connected their own accounts. This module is the
guild-touching half of those calls — the caller has already been established
from its installation token (``/app-platform/installation/*``), and everything
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

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.session import routed_guild_id
from app.core.messages import AppChannelMessages
from app.db.session import set_rls_context
from app.models.platform.guild import LIVE_STATUS_VALUES, Guild, GuildStatus
from app.models.tenant.guild_app import GuildApp
from app.models.tenant.guild_app_user_connection import GuildAppUserConnection
from app.services.marketplace.app_refs import ensure_app_guild_ref
from app.services.marketplace.service_apps import ENDPOINT_ID_PREFIX
from app.services.tenant import app_config as app_config_service
from app.services.tenant import app_connection_flows as flows
from app.services.tenant.webhook_dispatcher import dispatch_event

logger = logging.getLogger(__name__)

__all__ = [
    "MAX_EVENT_PAYLOAD_BYTES",
    "AppChannelError",
    "config_payload",
    "connection_payload",
    "connection_token",
    "emit_event",
    "load_install",
    "report_config_state",
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


class RegisteredApp(Protocol):
    """What these calls read of the caller's registration: its id and the
    listing it speaks for. The registration snapshot carries both."""

    public_id: str
    listing_uid: Optional[str]


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


def owns_install(app: GuildApp, registration: RegisteredApp) -> bool:
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


async def _route(session: AsyncSession, guild_id: int, *, read_only: bool) -> None:
    """Point the system-engine session at one guild, with the install's
    authority. ``SET ROLE`` drops the engine's bypass, so the guild's own
    policies decide from here; a frozen guild is routed to its SELECT-only role
    so no write can land in it whatever the caller asked for."""
    session.expunge_all()
    await set_rls_context(session, guild_id=guild_id, read_only=read_only)


async def _install_guild_ref(session: AsyncSession, app: GuildApp) -> str:
    """What this install calls the guild it is in.

    Every payload on this channel names the guild by it, because it is the only
    name the app on the other end has for it. The community is the one the
    session read the install from.
    """
    return await ensure_app_guild_ref(
        guild_id=routed_guild_id(session), app_install_id=app.id
    )


async def _guild_row(session: AsyncSession, guild_id: int) -> Optional[Guild]:
    await set_rls_context(session)
    return (await session.exec(select(Guild).where(Guild.id == guild_id))).first()


async def load_install(
    session: AsyncSession,
    registration: RegisteredApp,
    guild_id: int,
    *,
    app_install_id: int,
    for_write: bool = False,
) -> GuildApp:
    """The calling app's install in one guild, with the session routed to it.

    ``app_install_id`` is the install the caller's reference named, and the one
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
    if app.id != app_install_id:
        raise AppChannelError(AppChannelMessages.INSTALL_NOT_FOUND, status_code=404)
    if not app.enabled:
        # The guild's own kill switch, beside the operator's: the install stays
        # exactly as it is, and nothing flows through it until it is switched
        # back on. Every channel stops here, the credential pull included.
        raise AppChannelError(AppChannelMessages.INSTALL_DISABLED, status_code=409)
    return app


# --- the custody channel ----------------------------------------------------


async def config_payload(session: AsyncSession, app: GuildApp) -> dict[str, Any]:
    """The decrypted configuration for one install.

    It carries both halves of what an app is configured with: the guild-wide
    values (typed by an admin, or returned by a flow's ``after_connect``) and
    each member's managed values, keyed by the opaque reference the app knows
    that member by. A flow's tokens are never in it: the app asks for one with
    :func:`connection_token` when it needs it.
    """
    connections: dict[str, dict[str, Any]] = {}
    connection_refs: dict[str, str] = {}
    for connection in app_config_service.definition_connections(app.definition):
        connection_id = connection.get("id")
        if not isinstance(connection_id, str):
            continue
        if connection.get("scope") != "static":
            # Per-member values are reported below, per connection reference —
            # there is no guild-wide value for a credential a vendor issued to
            # one person.
            continue
        values = _without_tokens((app.config or {}).get(connection_id))
        values.update(
            app_config_service.decrypt_connection_secrets(
                _without_tokens((app.config_secrets or {}).get(connection_id))
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
                **_without_tokens(row.config),
                **app_config_service.decrypt_connection_secrets(
                    _without_tokens(row.config_secrets)
                ),
            },
        }
        for row in await _member_rows(session, app)
        if row.blocked_at is None
    ]

    state = app_config_service.config_state(app)
    return {
        "guild_ref": await _install_guild_ref(session, app),
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


def _without_tokens(values: dict[str, Any] | None) -> dict[str, Any]:
    """A stored map without the keys a flow keeps its tokens under."""
    return {
        key: value
        for key, value in (values or {}).items()
        if key not in app_config_service.RESERVED_TOKEN_KEYS
    }


async def connection_token(
    session: AsyncSession,
    app: GuildApp,
    registration: RegisteredApp,
    *,
    connection_ref: str,
) -> dict[str, Any]:
    """One usable access token for a connection of this install, by its ref.

    A member's connection must be connected and not blocked; its token is
    refreshed under the row's lock when it is close to expiring, and a refresh
    the vendor refuses leaves the connection ``expired``. A guild-wide
    connection answers its ``jwt_bearer`` token, or its own stored token.
    """
    try:
        guild_connection = app_config_service.connection_id_for_ref(app, connection_ref)
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
            )
            if member is None:
                raise AppChannelError(
                    AppChannelMessages.CONNECTION_NOT_FOUND, status_code=404
                )
            tokens = member
    except flows.ConnectionFlowError as exc:
        raise AppChannelError(exc.code, status_code=exc.status_code) from exc
    return flows.token_response(tokens)


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
        "guild_ref": await _install_guild_ref(session, app),
        "install_id": app.id,
        "config_state": app.config_state,
        "config_state_detail": app.config_state_detail,
    }


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
    registration: RegisteredApp,
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
    the community's subscriptions for that type. This route only emits; a
    subscription is registered on the webhook routes.
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
        guild_id=routed_guild_id(session),
        payload=payload,
    )
