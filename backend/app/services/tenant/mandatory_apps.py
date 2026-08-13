"""Apps the deployment provides, rather than a guild choosing them.

Some apps are not an optional extra: they are part of what a deployment *is*.
An operator says so on the registration (``mandatory``), and this is what that
statement does — every guild has the app, already there, with no admin
discovering it in a catalog and no admin able to remove it.

Four properties, and each one is a deliberate choice:

* **A guild gets it at creation, and an existing guild gets it at boot.** The
  same sweep pattern that reprovisions stale schemas, so the flag reaches guilds
  that predate it without anyone running anything.
* **Installing never fails guild creation.** The install is a local row; the
  app's container may be down, its listing may not have arrived yet, and none of
  that is a reason a guild cannot be created. What is missing is logged, and the
  next boot tries again.
* **The kill switch outranks the flag.** A registration the operator turned off
  installs nowhere new — deactivating an app stops it exactly like any other.
* **Clearing the flag destroys nothing.** Nothing here removes an install, so an
  app that stops being mandatory simply becomes an ordinary one a guild admin
  may now remove. Tearing an app down is uninstalling it, which is a different
  path with different consequences.

A self-hosted build that registered no app service has nothing marked mandatory,
so nothing here installs anything and nothing is displayed — the mechanism ships,
and a deployment's configuration decides whether anything uses it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.guild import Guild, GuildMembership, GuildRole
from app.models.tenant.guild_app import GuildApp
from app.services.marketplace import registration_lookup
from app.services.marketplace.definitions import GUILD_INSTALLABLE_APP_KINDS
from app.services.marketplace.installs import (
    ListingInstallError,
    resolve_listing_install,
)
from app.services.tenant import guild_apps as guild_apps_service

logger = logging.getLogger(__name__)

__all__ = [
    "BackfillResult",
    "backfill_mandatory_apps",
    "install_mandatory_apps",
]


@dataclass(frozen=True)
class BackfillResult:
    """What one boot sweep did."""

    guilds: int = 0
    installed: int = 0
    failed: int = 0


async def _installer_user_id(
    session: AsyncSession, *, guild_id: int, preferred: Optional[int] = None
) -> Optional[int]:
    """Who an automatic install is recorded against.

    The install row names a person because every other install does, and a
    guild admin is the honest answer: this is an app they are responsible for
    even though they did not choose it. The guild's own creator is preferred
    when the caller knows them; otherwise the longest-standing admin.
    """
    if preferred is not None:
        return preferred
    return (
        await session.exec(
            select(GuildMembership.user_id)
            .where(
                GuildMembership.guild_id == guild_id,
                GuildMembership.role == GuildRole.admin,
            )
            .order_by(GuildMembership.user_id)
            .limit(1)
        )
    ).first()


async def install_mandatory_apps(
    session: AsyncSession,
    *,
    guild_id: int,
    installed_by_id: Optional[int] = None,
) -> list[str]:
    """Install every mandatory app this guild does not have yet.

    The session must already be routed into the guild's schema. Rows are
    flushed, not committed: the caller owns the transaction, so a guild creation
    commits its apps together with the rest of its seed.

    Returns the listing uids installed. Anything that could not be installed —
    a registration that never verified, a listing this deployment does not hold,
    a version needing a newer build — is logged and skipped, because none of
    those is a reason to fail whatever the caller was doing.
    """
    registrations = await registration_lookup.mandatory_registrations()
    if not registrations:
        return []

    installer_id = await _installer_user_id(
        session, guild_id=guild_id, preferred=installed_by_id
    )
    if installer_id is None:
        logger.warning(
            "mandatory apps: guild %s has no admin to record an install against",
            guild_id,
        )
        return []

    installed: list[str] = []
    for registration in registrations:
        if registration.listing_uid is None:
            # The uid is recorded by the handshake, so a registration that has
            # never verified does not yet name a listing to install.
            logger.info(
                "mandatory apps: %s has not verified yet, so it names no listing",
                registration.public_id,
            )
            continue

        existing = (
            await session.exec(
                select(GuildApp).where(GuildApp.listing_uid == registration.listing_uid)
            )
        ).first()
        if existing is not None:
            continue

        try:
            listing, version = await resolve_listing_install(
                session, registration.listing_uid, kind="app"
            )
        except ListingInstallError as exc:
            logger.info(
                "mandatory apps: %s cannot be installed into guild %s (%s)",
                registration.public_id,
                guild_id,
                exc.code,
            )
            continue

        definition = dict(version.definition)
        if definition.get("app_kind") not in GUILD_INSTALLABLE_APP_KINDS:
            logger.warning(
                "mandatory apps: %s is not a kind this build mounts",
                registration.public_id,
            )
            continue

        await guild_apps_service.install_app(
            session,
            listing_uid=listing.uid,
            listing_version=version.version,
            definition=definition,
            guild_id=guild_id,
            installed_by_id=installer_id,
            name=(definition.get("default_name") or listing.name).strip(),
        )
        installed.append(listing.uid)

    return installed


async def backfill_mandatory_apps() -> BackfillResult:
    """Place mandatory apps into guilds that predate the flag.

    Runs at boot on the system engine, routing into each guild as a guild admin
    — the bypass is dropped by ``SET ROLE``, so the sweep needs the guild's own
    authority to write into its schema. A guild that fails is rolled back and
    logged; the others still get their app, and the next boot tries again.

    Returns immediately when nothing is marked mandatory, which is every
    deployment that has not asked for this.
    """
    from app.db import session as db_session

    if not await registration_lookup.mandatory_registrations():
        return BackfillResult()

    installed = failed = 0
    async with db_session.AdminSessionLocal() as session:
        guild_ids = list(
            (await session.exec(select(Guild.id).order_by(Guild.id))).all()
        )
        for guild_id in guild_ids:
            try:
                # One session walks every guild schema, and ids restart at 1 in
                # each of them — so a GuildApp(1) loaded from the last guild is
                # still in the identity map when the next one queries for its
                # own. Detach everything between guilds; nothing is carried
                # across a boundary on purpose.
                session.expunge_all()
                await db_session.set_rls_context(
                    session, guild_id=guild_id, guild_role="admin"
                )
                added = await install_mandatory_apps(session, guild_id=guild_id)
                await session.commit()
                installed += len(added)
            except Exception:
                await session.rollback()
                failed += 1
                logger.exception(
                    "mandatory apps: guild %s could not be backfilled", guild_id
                )

    return BackfillResult(guilds=len(guild_ids), installed=installed, failed=failed)
