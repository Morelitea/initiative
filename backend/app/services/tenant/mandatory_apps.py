"""Apps the deployment provides, rather than a guild choosing them.

Some apps are not an optional extra: they are part of what a deployment *is*.
An operator says so on the registration (``mandatory``), and this is what that
statement does — every guild has the app, already there, with no admin
discovering it in a catalog and no admin able to remove it.

Six properties, and each one is a deliberate choice:

* **A guild gets it at creation, and an existing guild gets it at boot.** The
  same sweep pattern that reprovisions stale schemas, so the flag reaches guilds
  that predate it without anyone running anything.
* **Installing never fails guild creation.** The install is a local row; the
  app's container may be down, its listing may not have arrived yet, and none of
  that is a reason a guild cannot be created. What is missing is logged, and the
  next boot tries again.
* **The kill switch outranks the flag.** A registration the operator turned off
  installs nowhere new — deactivating an app stops it exactly like any other.
* **It is granted what it asks for, within the ceiling.** The manifest's
  requested scopes, capped by the registration's ``scope_ceiling``: the
  operator's registration is the consent a seat would otherwise give. An
  install already there that holds no grant is given the same on the next
  sweep; one the seat has granted something is left as the seat set it.
* **It is placed in every initiative.** Each one that exists when it is
  installed, and each one created afterwards (``follows_new_initiatives``). The
  seat may still remove it from any single initiative, and that stays removed:
  nothing sweeps the initiatives that already exist.
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

from app.models.platform.guild import GUILD_ADMIN_ROLES, GuildMembership
from app.models.tenant.guild_app import GuildApp
from app.services.guild_sweeps import Scope, each_guild
from app.services.marketplace import app_installs, registration_lookup
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
    "mandatory_grant",
]


@dataclass(frozen=True)
class BackfillResult:
    """What one boot sweep did."""

    guilds: int = 0
    installed: int = 0
    failed: int = 0


def mandatory_grant(
    definition: dict, registration: registration_lookup.RegistrationSnapshot
) -> list[str]:
    """The scopes a mandatory install is granted: what its manifest requests
    and its registration's ceiling allows, sorted.

    Written on the system engine, which the install's grant guard admits.
    """
    return sorted(
        guild_apps_service.grantable_scopes(definition, registration.scope_ceiling)
    )


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
                GuildMembership.role.in_(GUILD_ADMIN_ROLES),
            )
            .order_by(GuildMembership.user_id)
            .limit(1)
        )
    ).first()


async def install_mandatory_apps(
    session: AsyncSession,
    *,
    guild_id: int,
    created_by: Optional[int] = None,
) -> list[str]:
    """Install every mandatory app this guild does not have yet.

    The session must already be routed into the guild's schema. Rows are
    flushed, not committed: the caller owns the transaction, so a guild creation
    commits its apps together with the rest of its seed.

    Returns the listing uids installed. Anything that could not be installed —
    a registration naming no listing, a listing this deployment does not hold,
    a version needing a newer build — is logged and skipped, because none of
    those is a reason to fail whatever the caller was doing.

    ``created_by`` is also the account the caller's session runs as, and is what
    the audit record names: a guild creation routes as its new owner and passes
    them here, and the boot sweep routes as nobody and passes nothing. The row
    an install is *recorded against* can differ — that is ``installer_id``,
    which falls back to the guild's longest-standing admin.
    """
    registrations = await registration_lookup.mandatory_registrations()
    if not registrations:
        return []

    installer_id = await _installer_user_id(
        session, guild_id=guild_id, preferred=created_by
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
            # A registration from before the listing was stated names none,
            # so there is nothing to install.
            logger.info(
                "mandatory apps: %s names no listing to install",
                registration.public_id,
            )
            continue

        existing = (
            await session.exec(
                select(GuildApp).where(GuildApp.listing_uid == registration.listing_uid)
            )
        ).first()
        if existing is not None:
            # An install the registration marked mandatory after it landed
            # follows new initiatives from here on. The initiatives that exist
            # already keep whatever placement the seat gave them.
            if not existing.follows_new_initiatives:
                existing.follows_new_initiatives = True
                session.add(existing)
            # One that holds no grant yet gets what a new install would. A
            # grant the seat already set is theirs and is left as it is.
            if not existing.granted_scopes:
                granted = mandatory_grant(existing.definition or {}, registration)
                if granted:
                    existing.granted_scopes = granted
                    session.add(existing)
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

        app = await guild_apps_service.install_app(
            session,
            listing_uid=listing.uid,
            listing_version=version.version,
            definition=definition,
            guild_id=guild_id,
            created_by=installer_id,
            name=(definition.get("default_name") or listing.name).strip(),
            actor_user_id=created_by,
            via="mandatory",
            granted_scopes=mandatory_grant(definition, registration),
        )
        # Placed in every initiative there is, and in each one created later.
        app.follows_new_initiatives = True
        session.add(app)
        await session.flush()
        await guild_apps_service.place_in_every_initiative(session, app)
        # Indexed now, before the caller commits: a guild whose seed fails is
        # removed, and its index rows with it.
        await app_installs.record(guild_id, app)
        installed.append(listing.uid)

    return installed


async def backfill_mandatory_apps() -> BackfillResult:
    """Place mandatory apps into guilds that predate the flag.

    Runs at boot, visiting every guild whose schema exists on a system session
    from its cohort. A guild that fails is rolled back and logged; the others
    still get their app, and the next boot tries again.

    Returns immediately when nothing is marked mandatory, which is every
    deployment that has not asked for this.
    """
    if not await registration_lookup.mandatory_registrations():
        return BackfillResult()

    visited = succeeded = installed = 0

    async def backfill(session: AsyncSession, guild_id: int) -> None:
        nonlocal visited, succeeded, installed
        visited += 1
        added = await install_mandatory_apps(session, guild_id=guild_id)
        await session.commit()
        succeeded += 1
        installed += len(added)

    await each_guild([(Scope.PROVISIONED, backfill)], name="mandatory-apps")
    return BackfillResult(
        guilds=visited, installed=installed, failed=visited - succeeded
    )
