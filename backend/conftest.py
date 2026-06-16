"""
Pytest configuration and fixtures for backend tests.

This module provides the core testing infrastructure including:
- Test database setup and teardown
- Session fixtures for database access
- Authentication helpers and fixtures
- Test client for API integration tests
"""

import asyncio
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import asyncpg
import pytest
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.core.rate_limit import limiter
from app.db.session import get_admin_session, get_session
from app.main import app

# Per-guild ROLES are cluster-global (Postgres has no per-database roles), so the
# suite's guild_<id> roles would collide with a co-located seeded dev DB's. Prefix
# the suite's roles (test_guild_<id>) so they're distinct catalog entries. Schemas
# are per-database and stay unprefixed. Set at import — before any provisioning.
settings.GUILD_ROLE_PREFIX = "test_"

# Use a separate test database (replace only the database name at the end)
_base_url = settings.DATABASE_URL.rsplit("/", 1)[0]
TEST_DATABASE_URL = _base_url + "/initiative_test"
TEST_DB_NAME = "initiative_test"

BACKEND_DIR = Path(__file__).resolve().parent


async def _ensure_test_database() -> None:
    """Create the test database if it doesn't exist."""
    parsed = urlparse(settings.DATABASE_URL.replace("+asyncpg", ""))
    conn = await asyncpg.connect(
        user=parsed.username,
        password=parsed.password,
        host=parsed.hostname,
        port=parsed.port or 5432,
        database="postgres",
    )
    try:
        exists = await conn.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1", TEST_DB_NAME
        )
        if not exists:
            await conn.execute(f'CREATE DATABASE "{TEST_DB_NAME}"')
    finally:
        await conn.close()


def _run_test_migrations() -> None:
    """Ensure test database exists and run alembic upgrade head."""
    asyncio.run(_ensure_test_database())
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    config.set_main_option("sqlalchemy.url", TEST_DATABASE_URL)
    config.attributes["configure_logger"] = False
    config.attributes["url_configured"] = True
    command.upgrade(config, "head")


@pytest.fixture(scope="session", autouse=True)
def _apply_migrations():
    """Automatically create test database and run migrations once per session."""
    _run_test_migrations()


@pytest.fixture(scope="session", autouse=True)
def _install_soft_delete_filter():
    """Install the SQLAlchemy session-wide filter that hides soft-deleted rows
    by default. Mirrors the production startup hook in app/main.py so tests
    see the same query semantics as live requests."""
    from app.db.soft_delete_filter import install_soft_delete_filter

    install_soft_delete_filter()


@pytest.fixture(autouse=True)
def _disable_hibp_check(monkeypatch):
    """Disable the HaveIBeenPwned breach lookup for all tests by default.

    Without this, every registration / password change test would make
    a real outbound HTTPS call to the HIBP API — flaky and slow.
    Tests that explicitly exercise the breach path opt back in via
    their own monkeypatch + ``hibp.is_password_breached`` stub.
    """
    from app.core.config import settings as app_settings

    monkeypatch.setattr(app_settings, "HIBP_CHECK_ENABLED", False)


@pytest.fixture(scope="function")
async def engine():
    """Create a test database engine."""
    test_engine = create_async_engine(
        TEST_DATABASE_URL, echo=False, future=True, pool_pre_ping=True
    )
    yield test_engine
    await test_engine.dispose()


def _test_url_for_role(role: str) -> str:
    """Test-DB connection URL for a given Postgres login role.

    The default ``engine``/``session`` fixtures connect as the SUPERUSER, which
    bypasses table/schema GRANTs and BYPASSRLS — so they silently mask
    permission bugs that bite the real ``app_admin``/``app_user`` roles in
    production (e.g. a cross-schema ``SELECT`` without ``SET ROLE``). This maps a
    role name onto a test-DB URL using that role's real credentials so a test can
    exercise the production privilege boundary.
    """
    if role in ("superuser", "su"):
        return TEST_DATABASE_URL
    base = {
        "app_admin": settings.DATABASE_URL_ADMIN,
        "app_user": settings.DATABASE_URL_APP,
    }.get(role)
    if base is None:
        raise ValueError(f"unknown test role: {role!r}")
    return base.rsplit("/", 1)[0] + "/" + TEST_DB_NAME


@pytest.fixture
async def role_session():
    """Factory yielding a DB session connected AS a given role (default
    ``app_admin``), against the test database.

    Use this to verify behaviour under the REAL production privilege boundary —
    the superuser-backed ``session`` fixture would let a missing ``SET ROLE`` or
    a cross-schema grant gap pass silently. Set up data with the normal
    ``session`` fixture (factories commit, so the rows are visible to this
    separate connection), then assert via ``await role_session("app_admin")``.

    Example:
        s = await role_session("app_admin")
        # raises asyncpg InsufficientPrivilege if the code reads a guild schema
        # without SET ROLE — exactly the bug the superuser session hides.
    """
    created: list = []

    async def _make(role: str = "app_admin") -> AsyncSession:
        eng = create_async_engine(
            _test_url_for_role(role), echo=False, future=True, pool_pre_ping=True
        )
        maker = sessionmaker(bind=eng, class_=AsyncSession, expire_on_commit=False)
        sess = maker()
        created.append((eng, sess))
        return sess

    yield _make

    for eng, sess in created:
        await sess.close()
        await eng.dispose()


@pytest.fixture(autouse=True)
def _schema_test_harness(engine, monkeypatch):
    """Make every test schema-per-guild aware.

    - Installs the before_flush router so direct-session (factory) guild-scoped
      writes land in the guild's schema, mirroring what set_rls_context does for
      the request path.
    - Points the (superuser) provisioning engine at the test DB so create_guild /
      the guilds endpoint provision schemas/roles on the test database.
    """
    import app.db.session as db_session
    from app.testing.schema_harness import install_guild_routing

    install_guild_routing()
    monkeypatch.setattr(db_session, "provisioning_engine", engine)


@pytest.fixture(scope="function")
async def session(engine) -> AsyncGenerator[AsyncSession, None]:
    """
    Create a fresh database session for each test.

    This fixture:
    - Provides a clean AsyncSession for the test
    - Truncates all tables after the test to ensure isolation

    This ensures test isolation by cleaning up all data after each test.

    The session is bound to a single dedicated connection (not the engine pool)
    so that the per-guild ``search_path`` the routing harness sets survives across
    commits — an engine-bound session checks out a fresh, unrouted connection per
    transaction, which is why a flush-then-refresh would otherwise lose the route.
    """
    async with engine.connect() as bound_conn:
        async_session = sessionmaker(
            bind=bound_conn,
            class_=AsyncSession,
            expire_on_commit=False,
            autocommit=False,
            autoflush=False,
        )

        async with async_session() as test_session:
            yield test_session

            # Expire all objects to detach them from the session
            test_session.expire_all()

        # Roll back the bound connection explicitly: closing a session bound to an
        # external connection does NOT end that connection's transaction, so the
        # test's trailing reads would keep AccessShare locks on the guild-schema
        # tables — which the teardown's DROP SCHEMA (AccessExclusive) would block on.
        await bound_conn.rollback()
        # Drop any guild role / schema routing the request path's set_rls_context
        # left on this connection (session-level GUCs survive rollback + pool
        # return), so the superuser cleanup below isn't stuck as guild_<id>.
        await bound_conn.exec_driver_sql(
            "SELECT set_config('role', 'none', false), set_config('search_path', 'public', false)"
        )

    # Session is now closed (its rollback released any lock on public.guilds the
    # create-guild endpoint's trailing SELECT left held). Clean up on a fresh
    # connection: drop the per-guild schemas/roles provisioned during the test
    # (cluster-global roles must not leak between tests), then truncate public.
    async with engine.begin() as conn:
        await conn.exec_driver_sql("SET lock_timeout = '10s'")
        for (schema,) in (
            await conn.execute(
                text(
                    "SELECT nspname FROM pg_namespace WHERE nspname ~ '^guild_[0-9]+$'"
                )
            )
        ).all():
            await conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        # Only the suite's own prefixed roles (test_guild_<id>) — never a
        # co-located dev DB's unprefixed guild_<id> roles (they share this
        # cluster-global catalog but belong to that database).
        role_pattern = f"^{settings.GUILD_ROLE_PREFIX}guild_[0-9]+(_ro)?$"
        roles = [
            r
            for (r,) in (
                await conn.execute(
                    text("SELECT rolname FROM pg_roles WHERE rolname ~ :pat"),
                    {"pat": role_pattern},
                )
            ).all()
        ]
        # Truncate all public tables to reset state.
        await conn.execute(text("SET session_replication_role = 'replica'"))
        for table in reversed(SQLModel.metadata.sorted_tables):
            await conn.execute(
                text(f"TRUNCATE TABLE {table.name} RESTART IDENTITY CASCADE")
            )
        await conn.execute(text("SET session_replication_role = 'origin'"))

    # Drop the suite's prefixed roles, each in its own transaction. Prefixed roles
    # are distinct from a co-located dev DB's, so these should succeed — the
    # suppress is belt-and-suspenders so one stuck role can't abort the rest.
    from contextlib import suppress

    for role in roles:
        with suppress(Exception):
            async with engine.begin() as rconn:
                await rconn.exec_driver_sql("SET lock_timeout = '5s'")
                await rconn.exec_driver_sql(f'DROP OWNED BY "{role}"')
                await rconn.exec_driver_sql(f'DROP ROLE IF EXISTS "{role}"')


@pytest.fixture
async def client(session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """
    Create an async HTTP client for testing API endpoints.

    This fixture:
    - Overrides the database session dependency to use the test session
    - Provides an AsyncClient configured with the FastAPI app

    Provisioning-engine redirection and per-guild schema/role cleanup are handled
    globally (see ``_schema_test_harness`` and the ``session`` fixture teardown).

    Usage:
        async def test_endpoint(client: AsyncClient):
            response = await client.get("/api/v1/health")
            assert response.status_code == 200
    """

    async def override_get_session() -> AsyncGenerator[AsyncSession, None]:
        yield session

    app.dependency_overrides[get_session] = override_get_session
    app.dependency_overrides[get_admin_session] = override_get_session

    # Disable rate limiting in tests
    limiter.enabled = False

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as test_client:
        yield test_client

    app.dependency_overrides.clear()

    # The create-guild endpoint ends on a SELECT (no commit after), leaving the
    # session idle-in-transaction holding a lock on public.guilds that the
    # teardown's DROP SCHEMA would block on. Release it now.
    await session.rollback()


@pytest.fixture
def auth_headers() -> dict[str, str]:
    """
    Base authentication headers.

    Tests that need authentication should use `authenticated_headers` or
    `create_auth_token` fixtures instead.
    """
    return {}


def create_test_user_data(**overrides: Any) -> dict[str, Any]:
    """
    Create test user data with sensible defaults.

    Args:
        **overrides: Override any default field values

    Returns:
        Dictionary with user data suitable for creating test users
    """
    defaults = {
        "email": "test@example.com",
        "full_name": "Test User",
        "password": "testpassword123",
        "is_active": True,
    }
    return {**defaults, **overrides}


def create_test_guild_data(**overrides: Any) -> dict[str, Any]:
    """
    Create test guild data with sensible defaults.

    Args:
        **overrides: Override any default field values

    Returns:
        Dictionary with guild data suitable for creating test guilds
    """
    defaults = {
        "name": "Test Guild",
        "description": "A test guild",
    }
    return {**defaults, **overrides}


def create_test_initiative_data(**overrides: Any) -> dict[str, Any]:
    """
    Create test initiative data with sensible defaults.

    Args:
        **overrides: Override any default field values

    Returns:
        Dictionary with initiative data suitable for creating test initiatives
    """
    defaults = {
        "title": "Test Initiative",
        "description": "A test initiative",
    }
    return {**defaults, **overrides}


def create_test_project_data(**overrides: Any) -> dict[str, Any]:
    """
    Create test project data with sensible defaults.

    Args:
        **overrides: Override any default field values

    Returns:
        Dictionary with project data suitable for creating test projects
    """
    defaults = {
        "title": "Test Project",
        "description": "A test project",
    }
    return {**defaults, **overrides}
