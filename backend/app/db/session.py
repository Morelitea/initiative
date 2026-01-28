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

engine = create_async_engine(settings.DATABASE_URL, echo=False, future=True)

# Admin engine for operations that need to bypass RLS (migrations, background jobs)
admin_engine = None
if settings.DATABASE_URL_ADMIN:
    admin_engine = create_async_engine(settings.DATABASE_URL_ADMIN, echo=False, future=True)

AsyncSessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
    class_=AsyncSession,
)

AdminSessionLocal = None
if admin_engine:
    AdminSessionLocal = sessionmaker(
        bind=admin_engine,
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
        class_=AsyncSession,
    )


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session


async def get_admin_session() -> AsyncGenerator[AsyncSession, None]:
    """Get a session that bypasses RLS (for migrations, background jobs, etc.)."""
    if AdminSessionLocal:
        async with AdminSessionLocal() as session:
            yield session
    else:
        # Fall back to regular session if no admin URL configured
        async with AsyncSessionLocal() as session:
            yield session


async def set_rls_context(
    session: AsyncSession,
    user_id: Optional[int] = None,
    guild_id: Optional[int] = None,
) -> None:
    """Set PostgreSQL session variables for RLS policy evaluation.

    These variables are used by RLS policies to determine which rows
    the current session can access. Uses SET LOCAL so the settings
    only apply to the current transaction.
    """
    if not settings.ENABLE_RLS:
        return

    if user_id is not None:
        await session.execute(
            text("SET LOCAL app.current_user_id = :uid"),
            {"uid": str(user_id)},
        )
    if guild_id is not None:
        await session.execute(
            text("SET LOCAL app.current_guild_id = :gid"),
            {"gid": str(guild_id)},
        )


@asynccontextmanager
async def rls_session(
    user_id: int,
    guild_id: int,
) -> AsyncGenerator[AsyncSession, None]:
    """Context manager that provides a session with RLS context set.

    Example:
        async with rls_session(user_id=1, guild_id=2) as session:
            # All queries in this session will be filtered by RLS
            projects = await session.exec(select(Project))
    """
    async with AsyncSessionLocal() as session:
        async with session.begin():
            await set_rls_context(session, user_id=user_id, guild_id=guild_id)
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
