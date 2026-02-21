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


@pytest.fixture(scope="function")
async def engine():
    """Create a test database engine."""
    test_engine = create_async_engine(TEST_DATABASE_URL, echo=False, future=True, pool_pre_ping=True)
    yield test_engine
    await test_engine.dispose()


@pytest.fixture(scope="function")
async def session(engine) -> AsyncGenerator[AsyncSession, None]:
    """
    Create a fresh database session for each test.

    This fixture:
    - Provides a clean AsyncSession for the test
    - Truncates all tables after the test to ensure isolation

    This ensures test isolation by cleaning up all data after each test.
    """
    # Create a session
    async_session = sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )

    async with async_session() as test_session:
        yield test_session

        # Expire all objects to detach them from the session
        test_session.expire_all()

    # Clean up - truncate all tables to reset state
    # Use a new connection to avoid session conflicts
    async with engine.begin() as conn:
        # Disable foreign key checks temporarily for faster truncate
        await conn.execute(text("SET session_replication_role = 'replica'"))
        for table in reversed(SQLModel.metadata.sorted_tables):
            await conn.execute(text(f"TRUNCATE TABLE {table.name} RESTART IDENTITY CASCADE"))
        await conn.execute(text("SET session_replication_role = 'origin'"))


@pytest.fixture
async def client(session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """
    Create an async HTTP client for testing API endpoints.

    This fixture:
    - Overrides the database session dependency to use the test session
    - Provides an AsyncClient configured with the FastAPI app
    - Automatically handles request/response lifecycle

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
        transport=ASGITransport(app=app),
        base_url="http://test"
    ) as test_client:
        yield test_client

    app.dependency_overrides.clear()


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
