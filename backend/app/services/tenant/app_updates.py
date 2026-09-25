"""Moving an install onto a newer version of its listing.

One function does the re-pin, and two callers ask for it: a guild admin
pressing Update, and the sweep below that applies published versions to the
installs tracking them. Writing that reasoning twice is how the two would come
to disagree about what an upgrade leaves behind — so the endpoint keeps the
HTTP vocabulary and this keeps the meaning.

**Auto is the resting state.** An install tracks its listing unless a guild
admin says otherwise, because an install quietly falling behind its publisher is
the worse default: a fix reaches the guild without anyone having to notice it
exists. Turning it off is a guild's own answer to "we read each version first",
and the manual Update button then does exactly what this sweep would have.

**A version that asks for more waits.** Asking for more is a grantable scope
neither the install's grant nor its pinned version already names, or a surface
inside initiatives the pinned version does not have. The sweep does not apply
such a version: it records it as ``pending_version`` and tells the community's
seat once, and the install keeps running its pinned version with its current
grant. The seat accepts it from the Update button, adding the scopes it
consents to, or declines it, which stops the asking until a newer version is
published. A version asking for nothing new applies as before.

**A required app does not wait.** The deployment's registration is what
installed it and granted what it requests within the ceiling, with no seat
asked; its newer versions are applied the same way, adding the new scopes
within the ceiling. A community with no seat holder would otherwise keep a
required app on a version it can no longer serve.

What survives an upgrade is the same either way. Stored configuration is pruned
to what the new definition still declares — a value cannot outlive the field it
was typed into — and a connection the new version dropped is *revoked* rather
than merely forgotten, since the app is still holding whatever that credential
bought it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.session import routed_guild_id, set_rls_context
from app.models.platform.guild import GuildMembership, GuildRole
from app.models.platform.notification import NotificationType
from app.models.tenant.guild_app import GuildApp
from app.services.marketplace import registration_lookup
from app.services.marketplace.definitions import GUILD_INSTALLABLE_APP_KINDS
from app.services.marketplace.installs import (
    ListingInstallError,
    resolve_listing_install,
)
from app.services.tenant import app_config as app_config_service
from app.services.tenant import app_connections as connections_service
from app.services.tenant import app_revocation as revocation_service
from app.services.tenant import guild_apps as guild_apps_service

logger = logging.getLogger(__name__)

__all__ = [
    "AskedUpdate",
    "PendingUpdate",
    "UPDATES_TARGET_PATH",
    "UpdateOffer",
    "UpgradeAsks",
    "apply_version",
    "decline_version",
    "notify_pending_updates",
    "update_offer",
    "update_version",
    "upgrade_asks",
    "update_guild",
]

#: Where the seat answers a pending version, inside the community: the
#: integrations settings, which list every app with its updates.
UPDATES_TARGET_PATH = "/settings/integrations"


@dataclass(frozen=True)
class PendingUpdate:
    """A version an install could move to, and the definition it carries."""

    version: str
    definition: dict


@dataclass(frozen=True)
class UpgradeAsks:
    """What a version asks for that the install does not already have.

    ``added_scopes`` are grantable scopes (requested and within the ceiling)
    that neither the install's grant nor its pinned version names, in
    vocabulary order. A scope the pinned version already requested and the
    seat left out is not new: the seat has answered it. ``added_surfaces``
    are the surfaces rendering inside initiatives that the pinned version does
    not have, as ``{"id", "name"}``.
    """

    added_scopes: tuple[str, ...] = ()
    added_surfaces: tuple[dict[str, Any], ...] = field(default=())

    @property
    def asks_more(self) -> bool:
        return bool(self.added_scopes or self.added_surfaces)


def upgrade_asks(
    app: GuildApp, definition: dict, ceiling: Iterable[str]
) -> UpgradeAsks:
    """What moving ``app`` to ``definition`` would ask the seat for."""
    held = set(app.granted_scopes or ()) | set(
        guild_apps_service.requested_scopes(app.definition)
    )
    added_scopes = tuple(
        scope
        for scope in guild_apps_service.grantable_scopes(definition, ceiling)
        if scope not in held
    )
    current = guild_apps_service.initiative_surface_ids(app.definition)
    added_surfaces = tuple(
        {"id": embed["id"], "name": embed.get("name") or {}}
        for embed in guild_apps_service.declared_surfaces(definition)
        if guild_apps_service.surface_renders_in(embed, "initiative")
        and embed["id"] not in current
    )
    return UpgradeAsks(added_scopes=added_scopes, added_surfaces=added_surfaces)


async def _ceiling(definition: dict) -> tuple[str, ...]:
    """The registration's ceiling for the service a definition names, or none."""
    registration = await registration_lookup.registration_for_definition(definition)
    return tuple(registration.scope_ceiling) if registration is not None else ()


@dataclass(frozen=True)
class UpdateOffer:
    """The version an install could move to, and what it would ask for."""

    update: "PendingUpdate"
    asks: UpgradeAsks

    @property
    def version(self) -> str:
        return self.update.version


async def update_offer(session: AsyncSession, app: GuildApp) -> Optional[UpdateOffer]:
    """What the catalog offers this install and what taking it asks, or ``None``."""
    pending = await _resolve_pending(session, app)
    if pending is None:
        return None
    asks = upgrade_asks(app, pending.definition, await _ceiling(pending.definition))
    return UpdateOffer(update=pending, asks=asks)


async def update_version(session: AsyncSession, app: GuildApp) -> Optional[str]:
    """The version this install would get if it updated now, or ``None``.

    ``None`` covers every reason there is nothing to offer — the listing is
    gone, withdrawn, or has published nothing this build can run. They are one
    answer here because they are one answer to the only question being asked:
    is there something to move to.
    """
    pending = await _resolve_pending(session, app)
    return pending.version if pending else None


async def _resolve_pending(
    session: AsyncSession, app: GuildApp
) -> Optional[PendingUpdate]:
    """What the catalog offers this install, or ``None`` if it offers nothing.

    A version of a kind this build cannot mount is *not* offered: applying one
    would leave the guild with an install nothing can serve, which is worse than
    staying on a version that works.
    """
    try:
        _, version = await resolve_listing_install(
            session, app.listing_uid, kind="app", already_installed=True
        )
    except ListingInstallError:
        return None
    if version.version == app.listing_version:
        return None
    definition = dict(version.definition)
    if definition.get("app_kind") not in GUILD_INSTALLABLE_APP_KINDS:
        return None
    return PendingUpdate(version=version.version, definition=definition)


async def apply_version(
    session: AsyncSession,
    app: GuildApp,
    pending: PendingUpdate,
    *,
    add_scopes: Iterable[str] = (),
) -> GuildApp:
    """Re-pin one install to a newer version of its listing.

    Everything the guild put in stays where it is, minus what the new definition
    stopped declaring. A dropped connection takes its values with it and is
    revoked on the way out; a dropped per-member connection is disconnected the
    same way, so no member is left holding vendor access this build no longer
    has a form for.

    ``add_scopes`` are the scopes the seat consented to with this version,
    already checked by the caller against the manifest and the ceiling. They
    join the grant; nothing is taken out of it here, because what a token
    carries is the grant intersected with what the pinned version requests.

    The caller commits — an upgrade is one transaction with whatever else it is
    part of — and drains the queued revocations afterwards, so an app is told a
    credential is finished only once the write that finished it is durable.
    """
    definition = pending.definition
    previous = app.definition
    added = set(add_scopes)
    if added - set(app.granted_scopes or ()):
        app.granted_scopes = sorted(set(app.granted_scopes or ()) | added)
    # Whatever was waiting or declined was a question about an older version
    # than the one this install is now on.
    app.pending_version = None
    app.declined_version = None

    config, config_secrets, dropped = app_config_service.prune_to_definition(
        definition, app.config, app.config_secrets
    )
    for connection_id in sorted(dropped):
        revocation_service.queue_revocation(
            session,
            revocation_service.intent_for(
                guild_id=routed_guild_id(session),
                app_id=app.id,
                listing_uid=app.listing_uid,
                definition=previous,
                connection_id=connection_id,
                config=(app.config or {}).get(connection_id),
                secrets=(app.config_secrets or {}).get(connection_id),
                reason="upgraded",
            ),
        )
    app.config = config
    app.config_secrets = config_secrets
    app.definition = definition
    app.listing_version = pending.version
    # The app has not seen the new configuration shape yet, so whatever it said
    # about the old one is no longer an answer to the current question.
    app.config_state = "unverified"
    app.config_state_detail = None
    guild_apps_service.touch(app)
    session.add(app)

    surviving = {
        connection.get("id")
        for connection in app_config_service.definition_connections(definition)
    }
    for row in await connections_service.list_app_connections(session, app_id=app.id):
        if row.connection_id not in surviving:
            await connections_service.disconnect(
                session,
                app=app,
                connection_id=row.connection_id,
                user_id=row.user_id,
                reason="upgraded",
                definition=previous,
            )
    return app


def decline_version(app: GuildApp, version: str) -> None:
    """Keep the pinned version, and stop asking about ``version``.

    A newer version than this one is asked about afresh.
    """
    app.declined_version = version
    app.pending_version = None
    guild_apps_service.touch(app)


# --- the sweep --------------------------------------------------------------


@dataclass(frozen=True)
class AskedUpdate:
    """A version the sweep recorded as pending, for the seat to be told."""

    app_id: int
    app_name: str
    version: str


async def notify_pending_updates(
    session: AsyncSession, guild_id: int, asked: Iterable[AskedUpdate]
) -> None:
    """Tell the community's seat holders that versions are waiting for them.

    One line per version per holder, in the approvals category. Runs out of
    the community's schema, on the bell's own rows in ``public``; the caller
    commits.
    """
    from app.services.platform import user_notifications

    waiting = list(asked)
    if not waiting:
        return
    await set_rls_context(session)
    holders = (
        await session.exec(
            select(GuildMembership.user_id).where(
                GuildMembership.guild_id == guild_id,
                GuildMembership.role == GuildRole.superadmin,
            )
        )
    ).all()
    for user_id in holders:
        for one in waiting:
            await user_notifications.create_notification(
                session,
                user_id=user_id,
                notification_type=NotificationType.app_update_pending,
                data={
                    "guild_id": guild_id,
                    "app_id": one.app_id,
                    "app_name": one.app_name,
                    "version": one.version,
                    "target_path": UPDATES_TARGET_PATH,
                },
            )


async def _update_guild(
    session: AsyncSession,
    guild_id: int,
    *,
    asked: Optional[list[AskedUpdate]] = None,
) -> int:
    """Apply what the catalog offers to one guild's tracking installs.

    Runs on a session already routed into that guild. A disabled install is
    updated too: ``auto_update`` says this guild tracks the listing, and an app
    switched back on months later should not come back on a version its
    publisher has long since replaced.

    **An admin editing an install always wins.** The pass reads ids first and
    then takes each row again under ``FOR UPDATE``, rather than working from the
    snapshot the scan produced. Two things follow, and both matter because
    resolving the catalog takes real time between the two reads: the values this
    prunes are the ones the install holds *now*, so a credential saved in the
    meantime is pruned rather than overwritten by a stale copy; and
    ``auto_update`` is read again under the lock, so a guild that opted out in
    the meantime is not updated one last time. An edit arriving while the lock
    is held waits and then applies on top, which is the order it happened in.

    A version that asks for more is not applied. It is recorded as the
    install's ``pending_version`` and appended to ``asked`` the first time it
    is seen, so the caller can tell the seat once it has committed. A version
    the seat declined, or one already pending, is passed over quietly.
    Returns how many installs were moved.
    """
    candidates = (
        await session.exec(
            select(GuildApp.id)
            .where(GuildApp.auto_update.is_(True))
            .order_by(GuildApp.id)
        )
    ).all()

    applied = 0
    for app_id in candidates:
        app = (
            await session.exec(
                select(GuildApp).where(GuildApp.id == app_id).with_for_update()
            )
        ).first()
        # Gone, or no longer tracking, since the scan.
        if app is None or not app.auto_update:
            continue
        offer = await update_offer(session, app)
        if offer is None:
            continue
        pending = offer.update
        mandatory = (await registration_lookup.install_state(app.definition)).mandatory
        if offer.asks.asks_more and mandatory:
            # The registration stands in for the seat, as at install.
            from_version = app.listing_version
            await apply_version(
                session, app, pending, add_scopes=offer.asks.added_scopes
            )
            applied += 1
            logger.info(
                "app auto-update: guild=%s app=%s listing=%s required, %s -> %s",
                guild_id,
                app.id,
                app.listing_uid,
                from_version,
                pending.version,
            )
            continue
        if offer.asks.asks_more:
            if pending.version not in (app.pending_version, app.declined_version):
                app.pending_version = pending.version
                guild_apps_service.touch(app)
                session.add(app)
                if asked is not None:
                    asked.append(
                        AskedUpdate(
                            app_id=app.id,
                            app_name=app.name,
                            version=pending.version,
                        )
                    )
                logger.info(
                    "app auto-update: guild=%s app=%s listing=%s %s waits for the seat",
                    guild_id,
                    app.id,
                    app.listing_uid,
                    pending.version,
                )
            continue
        from_version = app.listing_version
        await apply_version(session, app, pending)
        applied += 1
        logger.info(
            "app auto-update: guild=%s app=%s listing=%s %s -> %s",
            guild_id,
            app.id,
            app.listing_uid,
            from_version,
            pending.version,
        )
    return applied


async def update_guild(session: AsyncSession, guild_id: int) -> None:
    """The sweep's visit to one guild, on a session routed into it.

    Run by the hourly pass: a published version reaching every guild within
    the hour is what "automatic" needs to mean, and a visit costs one catalog
    read per installed listing. Only ``active`` guilds are visited: a guild on
    hold is frozen, and a background re-pin is still a change to what its
    members see.
    """
    asked: list[AskedUpdate] = []
    try:
        await _update_guild(session, guild_id, asked=asked)
        await session.commit()
    except Exception:
        # The queued revocations are dropped with the writes they belonged
        # to: nothing was taken away, so there is nothing to tell an app.
        revocation_service.drain_revocations(session)
        raise
    # After the commit, always: an app is told a credential is finished only
    # once the write that finished it is durable.
    intents = revocation_service.drain_revocations(session)
    if intents:
        await revocation_service.dispatch_revocations(intents)
    # The versions now waiting are durable, so the seat is told about them. A
    # bell that cannot be written is logged: the version stays pending on the
    # install and the settings page still shows it.
    if asked:
        try:
            await notify_pending_updates(session, guild_id, asked)
            await session.commit()
        except Exception:
            logger.exception(
                "app auto-update: guild %s seat could not be told", guild_id
            )
            await session.rollback()
