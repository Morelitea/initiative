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

# Primary engine: non-superuser (DATABASE_URL_APP) for RLS-enforced queries.
engine = create_async_engine(settings.DATABASE_URL_APP, echo=False, future=True)

# Admin engine: for background jobs and startup seeding (BYPASSRLS).
admin_engine = create_async_engine(settings.DATABASE_URL_ADMIN, echo=False, future=True)

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
    async with AsyncSessionLocal() as session:
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
    the current session can access. Uses set_config() with is_local=false
    so the settings persist across transaction boundaries and are
    guaranteed to execute on the same connection as subsequent queries.

    All four variables are always written (defaulting to empty/false)
    so that stale values from a previous request on the same pooled
    connection can never leak into the current request.
    """
    _VALID_ROLES = {"admin", "member"}
    if guild_role is not None and guild_role not in _VALID_ROLES:
        raise ValueError(f"Invalid guild_role: {guild_role!r}")

    # Store params on the session so reapply_rls_context() can re-set them
    # after session.commit() which may release the connection to the pool.
    session._rls_params = {  # type: ignore[attr-defined]
        "user_id": user_id,
        "guild_id": guild_id,
        "guild_role": guild_role,
        "is_superadmin": is_superadmin,
    }

    # Use set_config() (a regular SQL function) instead of SET commands.
    # SET is a special PostgreSQL command that asyncpg may execute outside
    # the normal query path, potentially on a different connection.
    # set_config() is a standard SQL query guaranteed to run on the same
    # connection as other session queries.
    uid = str(int(user_id)) if user_id is not None else ""
    gid = str(int(guild_id)) if guild_id is not None else ""
    grole = guild_role if guild_role is not None else ""
    sa = "true" if is_superadmin else "false"

    await session.execute(text(
        "SELECT set_config('app.current_user_id', :uid, false), "
        "set_config('app.current_guild_id', :gid, false), "
        "set_config('app.current_guild_role', :grole, false), "
        "set_config('app.is_superadmin', :sa, false)"
    ), {"uid": uid, "gid": gid, "grole": grole, "sa": sa})


async def reapply_rls_context(session: AsyncSession) -> None:
    """Re-apply stored RLS context after session.commit().

    After commit(), SQLAlchemy may release the connection back to the pool
    and acquire a different one for subsequent queries. The new connection
    won't have our SET variables. Call this after any commit that is
    followed by more queries in the same request.
    """
    params = getattr(session, "_rls_params", None)
    if params:
        await set_rls_context(session, **params)


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
    # Use superuser URL for migrations (needs CREATE ROLE and DDL privileges)
    config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)
    config.attributes["configure_logger"] = False
    config.attributes["url_configured"] = True
    return config


async def run_migrations() -> None:
    config = _get_alembic_config()
    await asyncio.to_thread(command.upgrade, config, "head")
