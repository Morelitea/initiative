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

What survives an upgrade is the same either way. Stored configuration is pruned
to what the new definition still declares — a value cannot outlive the field it
was typed into — and a connection the new version dropped is *revoked* rather
than merely forgotten, since the app is still holding whatever that credential
bought it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.session import AdminSessionLocal, set_rls_context
from app.models.platform.guild import Guild, GuildStatus
from app.models.tenant.guild_app import GuildApp
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
    "AUTO_UPDATE_POLL_SECONDS",
    "PendingUpdate",
    "apply_version",
    "update_version",
    "process_app_auto_updates",
]

#: How often the sweep runs. An hour rather than minutes: a published version
#: reaching every guild within the hour is what "automatic" needs to mean, and
#: the pass costs one catalog read per installed listing per guild.
AUTO_UPDATE_POLL_SECONDS = 3600


@dataclass(frozen=True)
class PendingUpdate:
    """A version an install could move to, and the definition it carries."""

    version: str
    definition: dict


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
    session: AsyncSession, app: GuildApp, pending: PendingUpdate
) -> GuildApp:
    """Re-pin one install to a newer version of its listing.

    Everything the guild put in stays where it is, minus what the new definition
    stopped declaring. A dropped connection takes its values with it and is
    revoked on the way out; a dropped per-member connection is disconnected the
    same way, so no member is left holding vendor access this build no longer
    has a form for.

    The caller commits — an upgrade is one transaction with whatever else it is
    part of — and drains the queued revocations afterwards, so an app is told a
    credential is finished only once the write that finished it is durable.
    """
    definition = pending.definition

    config, config_secrets, dropped = app_config_service.prune_to_definition(
        definition, app.config, app.config_secrets
    )
    for connection_id in sorted(dropped):
        revocation_service.queue_revocation(
            session,
            revocation_service.RevocationIntent(
                guild_id=app.guild_id,
                app_id=app.id,
                listing_uid=app.listing_uid,
                connection_id=connection_id,
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
            )
    return app


# --- the sweep --------------------------------------------------------------


async def _update_guild(session: AsyncSession, guild_id: int) -> int:
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
        pending = await _resolve_pending(session, app)
        if pending is None:
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


async def _update_all_guilds(session: AsyncSession) -> None:
    """One pass over every guild that is taking writes.

    Guilds are enumerated on the system engine, then each is visited in its own
    schema as a guild admin — ``SET ROLE`` drops the system engine's bypass, so
    the admin context is what carries the write. Only ``active`` guilds are
    swept: a guild on hold is frozen, and a background re-pin is still a change
    to what its members see.
    """
    await set_rls_context(session)
    guild_ids = list(
        await session.exec(
            select(Guild.id)
            .where(Guild.status == GuildStatus.active.value)
            .order_by(Guild.id.asc())
        )
    )
    for guild_id in guild_ids:
        # Ids collide across schemas, so the identity map is cleared between
        # guilds rather than carried into the next one.
        session.expunge_all()
        await set_rls_context(session, guild_id=guild_id, guild_role="admin")
        try:
            await _update_guild(session, guild_id)
            await session.commit()
        except Exception:
            # One guild's bad install must not cost every later guild its pass.
            # The queued revocations are dropped with the writes they belonged
            # to: nothing was taken away, so there is nothing to tell an app.
            logger.exception("app auto-update: guild %s failed", guild_id)
            await session.rollback()
            revocation_service.drain_revocations(session)
            continue
        # After the commit, always: an app is told a credential is finished
        # only once the write that finished it is durable.
        intents = revocation_service.drain_revocations(session)
        if intents:
            await revocation_service.dispatch_revocations(intents)


async def process_app_auto_updates() -> None:
    """One pass of the auto-update loop. Idempotent, and quiet when nothing is
    due — an install already on the version the catalog offers resolves to
    nothing to do."""
    async with AdminSessionLocal() as session:
        await _update_all_guilds(session)
