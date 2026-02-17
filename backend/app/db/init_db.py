import asyncio
from urllib.parse import urlparse

import asyncpg
from sqlmodel import select

from app.core.config import settings
from app.core.security import get_password_hash
from app.db.session import AdminSessionLocal, run_migrations
from app.models.user import User, UserRole
from app.models.guild import GuildRole
from app.services import app_settings as app_settings_service
from app.services import initiatives as initiatives_service
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
        async with session.begin():
            primary_guild = await guilds_service.get_primary_guild(session)
            result = await session.exec(select(User).where(User.email == settings.FIRST_SUPERUSER_EMAIL))
            user = result.one_or_none()
            if user:
                await guilds_service.ensure_membership(
                    session,
                    guild_id=primary_guild.id,
                    user_id=user.id,
                    role=GuildRole.admin,
                )
                await initiatives_service.ensure_default_initiative(session, user, guild_id=primary_guild.id)
                return

            superuser = User(
                email=settings.FIRST_SUPERUSER_EMAIL,
                full_name=settings.FIRST_SUPERUSER_FULL_NAME,
                hashed_password=get_password_hash(settings.FIRST_SUPERUSER_PASSWORD),
                role=UserRole.admin,
                email_verified=True,
            )
            session.add(superuser)
            await session.flush()
            await guilds_service.ensure_membership(
                session,
                guild_id=primary_guild.id,
                user_id=superuser.id,
                role=GuildRole.admin,
            )
            await initiatives_service.ensure_default_initiative(session, superuser, guild_id=primary_guild.id)


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

        if revision == BASELINE_REVISION:
            # Already on baseline, but roles may be missing if the user
            # upgraded to v0.30.0 without running init-db.sh. Clear the
            # stamp so the baseline migration re-runs — it's idempotent
            # and will create roles, RLS policies, and grants as needed.
            has_roles = await conn.fetchval(
                "SELECT EXISTS ("
                "  SELECT 1 FROM pg_roles WHERE rolname = 'app_user'"
                ")"
            )
            if not has_roles:
                print("Baseline stamped but database roles missing. Re-running baseline migration...")
                await conn.execute("DELETE FROM alembic_version")
            return

        raise SystemExit(
            f"\n{'=' * 70}\n"
            f"Pre-v0.30.0 database detected (revision: {revision}).\n\n"
            f"The database schema must be upgraded before this version can run.\n"
            f"Run the upgrade script with psql:\n\n"
            f"  curl -fsSL {UPGRADE_SCRIPT_URL} \\\n"
            f"    -o upgrade-to-baseline.sql\n\n"
            f"  psql -v ON_ERROR_STOP=1 \\\n"
            f"    -f upgrade-to-baseline.sql \"$DATABASE_URL\"\n\n"
            f"Then restart the application. The baseline migration will\n"
            f"create database roles, RLS policies, and grants automatically.\n"
            f"{'=' * 70}"
        )
    finally:
        await conn.close()


async def init() -> None:
    await check_pre_baseline_db()
    await run_migrations()
    await init_superuser()
    async with AdminSessionLocal() as session:
        await app_settings_service.get_or_create_guild_settings(session)


if __name__ == "__main__":  # pragma: no cover
    asyncio.run(init())
