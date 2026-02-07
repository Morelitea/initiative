import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator, Optional

from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.db import base  # noqa: F401  # ensure models are imported for Alembic

# Primary engine: prefer non-superuser (DATABASE_URL_APP) for RLS enforcement,
# fall back to DATABASE_URL for backward compatibility.
_primary_url = settings.DATABASE_URL_APP or settings.DATABASE_URL
engine = create_async_engine(_primary_url, echo=False, future=True)

# Admin engine: for migrations, background jobs, startup seeding.
# Prefer DATABASE_URL_ADMIN (BYPASSRLS), fall back to DATABASE_URL.
_admin_url = settings.DATABASE_URL_ADMIN or settings.DATABASE_URL
admin_engine = create_async_engine(_admin_url, echo=False, future=True)

AsyncSessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
    class_=AsyncSession,
)

AdminSessionLocal = sessionmaker(
    bind=admin_engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
    class_=AsyncSession,
)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    # Pin the DBAPI connection for the entire request lifetime.
    # Without this, session.commit() may release the connection back to the
    # pool and the next query may get a DIFFERENT connection that doesn't
    # have our SET variables for RLS context.
    async with engine.connect() as conn:
        async with AsyncSession(bind=conn, autoflush=False, expire_on_commit=False) as session:
            if settings.ENABLE_RLS:
                # Reset RLS variables from any previous request on this pooled connection.
                # Uses set_config() in a single round-trip for efficiency.
                await session.execute(text(
                    "SELECT set_config('app.current_user_id', '', false), "
                    "set_config('app.current_guild_id', '', false), "
                    "set_config('app.current_guild_role', '', false), "
                    "set_config('app.is_superadmin', 'false', false)"
                ))
            yield session


async def get_admin_session() -> AsyncGenerator[AsyncSession, None]:
    """Get a session that bypasses RLS (for migrations, background jobs, etc.)."""
    async with AdminSessionLocal() as session:
        yield session


async def set_rls_context(
    session: AsyncSession,
    user_id: Optional[int] = None,
    guild_id: Optional[int] = None,
    guild_role: Optional[str] = None,
    is_superadmin: bool = False,
) -> None:
    """Set PostgreSQL session variables for RLS policy evaluation.

    These variables are used by RLS policies to determine which rows
    the current session can access. Uses SET (not SET LOCAL) so the
    settings persist across transaction boundaries — service functions
    that call session.commit() won't clear the context.

    All four variables are always written (defaulting to empty/false)
    so that stale values from a previous request on the same pooled
    connection can never leak into the current request.
    """
    if not settings.ENABLE_RLS:
        return

    # SET does not support bind parameters ($1) in PostgreSQL,
    # so we must use literal values. Integer IDs are safe by type;
    # guild_role is validated against a known allowlist.
    _VALID_ROLES = {"admin", "member"}
    if guild_role is not None and guild_role not in _VALID_ROLES:
        raise ValueError(f"Invalid guild_role: {guild_role!r}")

    await session.execute(text(
        f"SET app.current_user_id = '{int(user_id)}'" if user_id is not None
        else "SET app.current_user_id = ''"
    ))
    await session.execute(text(
        f"SET app.current_guild_id = '{int(guild_id)}'" if guild_id is not None
        else "SET app.current_guild_id = ''"
    ))
    await session.execute(text(
        f"SET app.current_guild_role = '{guild_role}'" if guild_role is not None
        else "SET app.current_guild_role = ''"
    ))
    await session.execute(text(
        "SET app.is_superadmin = 'true'" if is_superadmin
        else "SET app.is_superadmin = 'false'"
    ))


@asynccontextmanager
async def rls_session(
    user_id: int,
    guild_id: int,
    guild_role: Optional[str] = None,
    is_superadmin: bool = False,
) -> AsyncGenerator[AsyncSession, None]:
    """Context manager that provides a session with RLS context set.

    Example:
        async with rls_session(user_id=1, guild_id=2) as session:
            # All queries in this session will be filtered by RLS
            projects = await session.exec(select(Project))
    """
    async with AsyncSessionLocal() as session:
        async with session.begin():
            await set_rls_context(
                session,
                user_id=user_id,
                guild_id=guild_id,
                guild_role=guild_role,
                is_superadmin=is_superadmin,
            )
            yield session


BACKEND_DIR = Path(__file__).resolve().parents[2]
ALEMBIC_INI_PATH = BACKEND_DIR / "alembic.ini"
ALEMBIC_SCRIPT_LOCATION = BACKEND_DIR / "alembic"


def _get_alembic_config() -> Config:
    config = Config(str(ALEMBIC_INI_PATH))
    config.set_main_option("script_location", str(ALEMBIC_SCRIPT_LOCATION))
    # Use admin URL for migrations (has BYPASSRLS privilege), fall back to regular URL
    migration_url = settings.DATABASE_URL_ADMIN or settings.DATABASE_URL
    config.set_main_option("sqlalchemy.url", migration_url)
    config.attributes["configure_logger"] = False
    return config


async def run_migrations() -> None:
    config = _get_alembic_config()
    await asyncio.to_thread(command.upgrade, config, "head")


async def init_models() -> None:  # Backwards compatibility for existing imports
    await run_migrations()
