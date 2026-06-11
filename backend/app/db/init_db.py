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
from app.models.guild import Guild
from app.models.user import User, UserRole
from app.services import app_settings as app_settings_service
from app.services import guilds as guilds_service

BASELINE_REVISION = "20260216_0053"
UPGRADE_SCRIPT_URL = (
    "https://raw.githubusercontent.com/Morelitea/initiative/"
    "main/scripts/upgrade-to-baseline.sql"
)


async def init_superuser() -> None:
    if not (settings.FIRST_SUPERUSER_EMAIL and settings.FIRST_SUPERUSER_PASSWORD):
        return

    async with AdminSessionLocal() as session:
        existing = await session.exec(
            select(User).where(
                User.email_hash == hash_email(settings.FIRST_SUPERUSER_EMAIL)
            )
        )
        if existing.one_or_none() is not None:
            return  # already seeded

        # Create the first superuser (the platform owner)...
        user = User(
            email_hash=hash_email(settings.FIRST_SUPERUSER_EMAIL),
            email_encrypted=encrypt_field(settings.FIRST_SUPERUSER_EMAIL, SALT_EMAIL),
            full_name=settings.FIRST_SUPERUSER_FULL_NAME,
            hashed_password=get_password_hash(settings.FIRST_SUPERUSER_PASSWORD),
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
            # Otherwise the committed user makes init_superuser short-circuit on
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


async def check_pre_baseline_db() -> None:
    """Exit with upgrade instructions if the database is pre-v0.30.0."""
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

        # Check whether the baseline migration has already been applied.
        # After post-baseline migrations run, the stamp advances past
        # BASELINE_REVISION, so we also check for the app_user role which
        # the baseline creates.
        has_roles = await conn.fetchval(
            "SELECT EXISTS (  SELECT 1 FROM pg_roles WHERE rolname = 'app_user')"
        )

        if revision == BASELINE_REVISION:
            # Already on baseline, but roles may be missing if the user
            # upgraded to v0.30.0 without running init-db.sh. Clear the
            # stamp so the baseline migration re-runs — it's idempotent
            # and will create roles, RLS policies, and grants as needed.
            if not has_roles:
                print(
                    "Baseline stamped but database roles missing. Re-running baseline migration..."
                )
                await conn.execute("DELETE FROM alembic_version")
            return

        if has_roles:
            return  # Post-baseline revision; baseline was already applied

        raise SystemExit(
            f"\n{'=' * 70}\n"
            f"Pre-v0.30.0 database detected (revision: {revision}).\n\n"
            f"The database schema must be upgraded before this version can run.\n"
            f"Run the upgrade script with psql:\n\n"
            f"  curl -fsSL {UPGRADE_SCRIPT_URL} \\\n"
            f"    -o upgrade-to-baseline.sql\n\n"
            f"  psql -v ON_ERROR_STOP=1 \\\n"
            f'    -f upgrade-to-baseline.sql "$DATABASE_URL"\n\n'
            f"If psql is not available (e.g. Synology, Unraid), pipe through\n"
            f"the Postgres container:\n\n"
            f"  curl -fsSL {UPGRADE_SCRIPT_URL} | \\\n"
            f"    docker exec -i initiative-db \\\n"
            f"    psql -v ON_ERROR_STOP=1 -U initiative -d initiative\n\n"
            f"Then restart the application. The baseline migration will\n"
            f"create database roles, RLS policies, and grants automatically.\n"
            f"{'=' * 70}"
        )
    finally:
        await conn.close()


async def init() -> None:
    await check_pre_baseline_db()
    await run_migrations()
    # Provision + migrate any pre-cutover guilds from public into their schemas
    # BEFORE anything below routes into a guild's role/schema — an existing guild
    # has no guild_<id> role until it's provisioned, so set_rls_context would fail.
    from app.db.guild_conversion import convert_public_to_guild_schemas

    await convert_public_to_guild_schemas()
    await init_superuser()
    async with AdminSessionLocal() as session:
        # guild_settings is guild-scoped; route into the primary guild's schema so
        # the seeded settings row lands there, not in public. get_primary_guild_id
        # provisions the guild if it has to create it (no-FIRST_SUPERUSER path).
        primary_id = await guilds_service.get_primary_guild_id(session)
        await set_rls_context(session, guild_id=primary_id)
        await app_settings_service.get_or_create_guild_settings(
            session, guild_id=primary_id
        )


if __name__ == "__main__":  # pragma: no cover
    asyncio.run(init())
