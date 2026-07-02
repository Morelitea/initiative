import asyncio
from contextlib import suppress
from urllib.parse import urlparse

import asyncpg
from sqlalchemy import delete as sql_delete
from sqlmodel import select

from app.core.config import settings
from app.core.encryption import encrypt_field, hash_email, SALT_EMAIL
from app.core.security import get_password_hash
from app.db.schema_provisioning import deprovision_guild
from app.db.session import AdminSessionLocal, run_migrations, set_rls_context
from app.models.platform.guild import Guild
from app.models.platform.user import User, UserRole
from app.services.platform import app_settings as app_settings_service
from app.services.platform import guilds as guilds_service

# The squashed baseline (v0.53.5 snapshot). Databases stamped at an older
# revision must go through a v0.53.x release first — see check_pre_baseline_db.
BASELINE_REVISION = "20260626_0125"


async def init_owner() -> None:
    if not (settings.FIRST_OWNER_EMAIL and settings.FIRST_OWNER_PASSWORD):
        return

    async with AdminSessionLocal() as session:
        existing = await session.exec(
            select(User).where(
                User.email_hash == hash_email(settings.FIRST_OWNER_EMAIL)
            )
        )
        if existing.one_or_none() is not None:
            return  # already seeded

        # Create the first superuser (the platform owner)...
        user = User(
            email_hash=hash_email(settings.FIRST_OWNER_EMAIL),
            email_encrypted=encrypt_field(settings.FIRST_OWNER_EMAIL, SALT_EMAIL),
            full_name=settings.FIRST_OWNER_FULL_NAME,
            hashed_password=get_password_hash(settings.FIRST_OWNER_PASSWORD),
            role=UserRole.owner,
            email_verified=True,
        )
        session.add(user)
        await session.commit()

        # ...and their guild the same way the API does: create the shared rows,
        # commit, then provision the schema and seed its content (settings +
        # default initiative). No bespoke seeding path — it's a real guild.
        guild = await guilds_service.create_guild(
            session, name="Primary Guild", creator=user
        )
        await session.commit()
        # Capture ids before the seed: the rollback in the failure path expires the
        # ORM objects, so reading guild.id / user.id afterwards would reload.
        guild_id = guild.id
        user_id = user.id
        try:
            await guilds_service.seed_guild_content(
                session, guild_id=guild_id, creator=user
            )
            await session.commit()
        except Exception:
            # Undo the whole first-boot seed so a restart re-initializes cleanly.
            # Otherwise the committed user makes init_owner short-circuit on
            # every restart, stranding the primary guild without a schema. Mirrors
            # the API/registration cleanup. Roll back FIRST (an aborted session
            # would fault the cleanup queries, and it reverts the seed's SET ROLE
            # so deprovision can DROP the role); this is an admin (BYPASSRLS)
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

        revision = await conn.fetchval(
            "SELECT version_num FROM alembic_version LIMIT 1"
        )
        if revision is None:
            return  # Fresh database (empty alembic_version)

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
            return  # post-squash revision (e.g. 20260701_0126) — normal upgrade

        raise SystemExit(
            f"\n{'=' * 70}\n"
            f"Pre-v0.53.2 database detected (revision: {revision}).\n\n"
            f"This version's migration history starts at the v0.53.5 baseline;\n"
            f"older databases must step through a v0.53.x release first:\n\n"
            f"  1. Deploy any v0.53.x image (e.g. morelitea/initiative:0.53.5)\n"
            f"     and let it boot once — its migrations and startup conversion\n"
            f"     bring the database to the baseline state.\n"
            f"  2. Then deploy this version and restart.\n\n"
            f"(Installs older than v0.30.0 should first follow the v0.30.0\n"
            f"upgrade instructions, then step through v0.53.x.)\n"
            f"{'=' * 70}"
        )
    finally:
        await conn.close()


async def init() -> None:
    await check_pre_baseline_db()
    await run_migrations()
    await init_owner()
    async with AdminSessionLocal() as session:
        # guild_settings is guild-scoped; route into the primary guild's schema so
        # the seeded settings row lands there, not in public. get_primary_guild_id
        # provisions the guild if it has to create it (no-FIRST_OWNER path).
        primary_id = await guilds_service.get_primary_guild_id(session)
        await set_rls_context(session, guild_id=primary_id)
        await app_settings_service.get_or_create_guild_settings(
            session, guild_id=primary_id
        )


if __name__ == "__main__":  # pragma: no cover
    asyncio.run(init())
