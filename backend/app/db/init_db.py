from datetime import datetime, timezone
import asyncio
from contextlib import suppress
from urllib.parse import urlparse

import asyncpg
from sqlalchemy import delete as sql_delete

from app.core.audit_events import AuditEventType
from app.core.config import settings
from app.core.security import get_password_hash
from app.core.version import get_version
from app.db.schema_provisioning import (
    deprovision_guild,
    ensure_shared_table_grants,
    ensure_system_engine_bypassrls,
    verify_effective_shared_grants,
    verify_engine_identities,
)
from app.db.session import (
    SystemSessionLocal,
    migration_chain,
    migration_lock,
    run_migrations,
    set_rls_context,
)
from app.models.platform.guild import Guild
from app.models.platform.user import User, UserRole
from app.services import audit as audit_service
from app.services.auth import addresses
from app.services.platform import app_settings as app_settings_service
from app.services.platform import dm_settings as dm_settings_service
from app.services.platform import guilds as guilds_service
from app.core import usernames

# The squashed baseline (v0.53.5 snapshot). Databases stamped at an older
# revision must go through a v0.53.x release first — see check_pre_baseline_db.
BASELINE_REVISION = "20260626_0125"


async def init_owner() -> None:
    if not (settings.FIRST_OWNER_EMAIL and settings.FIRST_OWNER_PASSWORD):
        return

    async with SystemSessionLocal() as session:
        existing = await addresses.find_user_by_address(
            session, settings.FIRST_OWNER_EMAIL
        )
        if existing is not None:
            return  # already seeded

        # Create the first superuser (the platform owner)...
        user = User(
            full_name=settings.FIRST_OWNER_FULL_NAME,
            username=usernames.from_full_name(settings.FIRST_OWNER_FULL_NAME)
            or usernames.random_name(),
            discriminator=usernames.random_discriminator(),
            hashed_password=get_password_hash(settings.FIRST_OWNER_PASSWORD),
            password_set_at=datetime.now(timezone.utc),
            role=UserRole.owner,
        )
        session.add(user)
        await session.flush()
        addresses.record_address(
            session,
            user_id=user.id,
            email=settings.FIRST_OWNER_EMAIL,
            source=addresses.SOURCE_SIGNUP,
            verified=True,
        )
        await dm_settings_service.seed_for_new_account(session, user_id=user.id)
        # Nobody signed in made this account, so it carries no actor.
        await audit_service.record(
            session,
            event_type=AuditEventType.USER_CREATED,
            actor_user_id=None,
            target_user_id=user.id,
            detail={"via": "bootstrap"},
        )
        await session.commit()

        # ...and their guild the same way the API does: create the shared rows,
        # commit, then provision the schema and seed its content (settings +
        # default initiative). No bespoke seeding path — it's a real guild.
        guild = await guilds_service.create_guild(
            session, name="Primary Community", creator=user
        )
        await session.commit()
        # Capture ids before the seed: the rollback in the failure path expires the
        # ORM objects, so reading guild.id / user.id afterwards would reload.
        guild_id = guild.id
        user_id = user.id
        try:
            await guilds_service.seed_guild_content(
                session, guild_id=guild_id, owner=user
            )
            await session.commit()
        except Exception:
            # Undo the whole first-boot seed so a restart re-initializes cleanly.
            # Otherwise the committed user makes init_owner short-circuit on
            # every restart, stranding the primary guild without a schema. Mirrors
            # the API/registration cleanup. Roll back FIRST (an aborted session
            # would fault the cleanup queries, and it reverts the seed's SET ROLE
            # so deprovision can DROP the role); this is a system-engine
            # session, so the bulk DELETEs aren't RLS-filtered.
            await session.rollback()
            with suppress(Exception):
                await deprovision_guild(guild_id)
            await session.exec(sql_delete(Guild).where(Guild.id == guild_id))
            await session.exec(sql_delete(User).where(User.id == user_id))
            await session.commit()
            raise


def _is_dated_revision(revision: str) -> bool:
    """True for this repo's YYYYMMDD_NNNN revision ids (explicit check)."""
    return (
        len(revision) == 13
        and revision[8] == "_"
        and revision[:8].isdigit()
        and revision[9:].isdigit()
    )


def _require_image_knows(stamped: list[str]) -> None:
    """Exit with instructions if this image lacks a revision the database is
    stamped at — the mirror of the pre-baseline case below, and the same
    cryptic alembic failure ("can't locate revision") if nothing catches it.

    A database gets ahead of its image whenever the container comes back on an
    older one than last upgraded it: a pull that did not replace the tag it was
    meant to, a deliberate roll-back, or a half-finished rebuild whose leftover
    container is the one still being started.
    """
    revisions, head = migration_chain()
    if not revisions:
        return  # Chain unreadable; let alembic surface whatever is wrong with it
    ahead = [revision for revision in stamped if revision not in revisions]
    if not ahead:
        return

    raise SystemExit(
        f"\n{'=' * 70}\n"
        f"This image is older than the database.\n\n"
        f"  database stamped at:   {', '.join(sorted(ahead))}\n"
        f"  newest migration here: {head or '?'}\n"
        f"  this image:            {get_version()}\n\n"
        f"Migrations only run forward, so this version cannot serve this\n"
        f"database. Start the release that last upgraded it — or any newer\n"
        f"one — and the app comes up where it left off.\n\n"
        f"If it keeps coming back on the old image after you pull a new one,\n"
        f"look for a container the upgrade left behind and started instead:\n"
        f"compose renames the one it is replacing to <12 hex characters>_<name>\n"
        f"and leaves it there when the rebuild does not finish. Remove it and\n"
        f"bring the project up again.\n\n"
        f"Running this version deliberately means restoring the database\n"
        f"backup taken before that upgrade; there is no downgrade path.\n"
        f"{'=' * 70}"
    )


async def check_pre_baseline_db() -> None:
    """Exit with upgrade instructions if the database predates the v0.53.5
    baseline squash — its revision id no longer exists in this chain, so
    alembic would fail with a cryptic "can't locate revision" otherwise."""
    parsed = urlparse(settings.DATABASE_URL.replace("+asyncpg", ""))

    try:
        conn = await asyncpg.connect(
            user=parsed.username,
            password=parsed.password,
            database=parsed.path.lstrip("/"),
            host=parsed.hostname,
            port=parsed.port or 5432,
        )
    except Exception:
        return  # Can't connect; let alembic surface the error

    try:
        has_table = await conn.fetchval(
            "SELECT EXISTS ("
            "  SELECT 1 FROM information_schema.tables "
            "  WHERE table_schema = 'public' AND table_name = 'alembic_version'"
            ")"
        )
        if not has_table:
            return  # Fresh database

        # Every row, not just one: a database left on a branch carries a stamp
        # per head, and a single image has to be able to run all of them.
        stamped = [
            row["version_num"]
            for row in await conn.fetch("SELECT version_num FROM alembic_version")
        ]
        if not stamped:
            return  # Fresh database (empty alembic_version)
        revision = stamped[0]

        if revision == BASELINE_REVISION:
            # Stamped at the baseline, but roles may be missing on a database
            # that never actually ran it (e.g. restored without roles). Clear
            # the stamp so the (idempotent) baseline migration re-runs — it
            # recreates roles, RLS policies, and grants as needed.
            has_roles = await conn.fetchval(
                "SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_user')"
            )
            if not has_roles:
                print(
                    "Baseline stamped but database roles missing. Re-running baseline migration..."
                )
                await conn.execute("DELETE FROM alembic_version")
            return

        if _is_dated_revision(revision) and revision > BASELINE_REVISION:
            # Post-squash, so alembic can run it — as long as this image is the
            # one that has it. Say so when it isn't, for the same reason the
            # pre-baseline message below exists.
            _require_image_knows(stamped)
            return  # normal upgrade

        raise SystemExit(
            f"\n{'=' * 70}\n"
            f"Pre-v0.53.2 database detected (revision: {revision}).\n\n"
            f"This version's migration history starts at the v0.53.5 baseline;\n"
            f"older databases must step through a v0.53.x release first:\n\n"
            f"  1. Deploy any v0.53.x image (e.g. morelitea/initiative:0.53.5)\n"
            f"     and let it boot once — its migrations and startup conversion\n"
            f"     bring the database to the baseline state.\n"
            f"  2. Then deploy this version and restart.\n\n"
            f"Step 1 is mandatory, not advisory: it is what copies guild content\n"
            f"into the per-guild schemas. This version DROPS the old copies in\n"
            f"the public schema (migration 20260811_0163) and cannot be rolled\n"
            f"back, so anything not converted by then is lost.\n\n"
            f"(Installs older than v0.30.0 are no longer supported for\n"
            f"in-place upgrade — restore into a fresh install instead.)\n"
            f"{'=' * 70}"
        )
    finally:
        await conn.close()


async def migrate_database() -> None:
    """Bring the database to head, one instance at a time.

    The pre-baseline check reads — and on one path clears — the alembic stamp
    that the upgrade then acts on, so the two share a lock rather than taking
    one each.
    """
    async with migration_lock():
        await check_pre_baseline_db()
        await run_migrations()


async def init() -> None:
    await migrate_database()
    # Name the three DB logins in the log and warn loudly on wiring that
    # collapses the role separation, before the heals act on those logins.
    await verify_engine_identities()
    # A policy-bound system engine (restored database, hand-created role) reads
    # shared tables as empty; the seeding below would then try to re-create the
    # primary guild and die on the guilds RLS policy (issue #835). Verify —
    # and, when DATABASE_URL lawfully can, repair — before touching data.
    await ensure_system_engine_bypassrls()
    # And, one gate deeper, the shared-table GRANTs the system engine needs to
    # actually write (BYPASSRLS skips policies, not privilege checks) — a
    # restored role can be missing them, failing with "permission denied for
    # table guilds" (issue #835 follow-up).
    await ensure_shared_table_grants()
    # The heal targets the canonical role names; verify the CONNECTED logins
    # actually hold the audited privileges (exact GRANTs in the error if not).
    await verify_effective_shared_grants()
    await init_owner()
    async with SystemSessionLocal() as session:
        # The platform settings singleton, before anything reads it: a read
        # serves defaults in memory rather than creating the row, so this is
        # where it comes from on a database that has never had one.
        await app_settings_service.seed_app_settings(session)
        # guild_settings is guild-scoped; route into the primary guild's schema so
        # the seeded settings row lands there, not in public. get_primary_guild_id
        # provisions the guild if it has to create it (no-FIRST_OWNER path).
        primary_id = await guilds_service.get_primary_guild_id(session)
        await set_rls_context(session, guild_id=primary_id)
        await app_settings_service.get_or_create_guild_settings(
            session, guild_id=primary_id
        )
        await session.commit()


if __name__ == "__main__":  # pragma: no cover
    asyncio.run(init())
