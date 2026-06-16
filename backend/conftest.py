"""
Pytest configuration and fixtures for backend tests.

This module provides the core testing infrastructure including:
- Test database setup and teardown
- Session fixtures for database access
- Authentication helpers and fixtures
- Test client for API integration tests
"""

import asyncio
import fcntl
import os
import tempfile
from collections.abc import AsyncGenerator
from contextlib import suppress
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import asyncpg
import pytest
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.core.rate_limit import limiter
from app.db.session import get_admin_session, get_session
from app.main import app

# --- Per-worker isolation (pytest-xdist) ---------------------------------------
# xdist runs each worker as its own OS process, so all Python state in this module
# is already per-worker. The shared resources are the Postgres DATABASE and the
# cluster-global ROLES; isolate both per worker so the suite is parallel-safe.
#
# WORKER_ID is xdist's value used VERBATIM ("gw0"/"gw1"/... distributed, "master"
# standalone) — xdist exports PYTEST_XDIST_WORKER into each worker process before
# this module is imported. We don't rename it.
WORKER_ID = os.environ.get("PYTEST_XDIST_WORKER", "master")

# Per-worker, cluster-global role prefix so workers never collide on, or drop,
# each other's roles (test_gw0_guild_<id>, test_gw0_platform_<tier>). Set BEFORE
# any migration/provisioning: the platform-role migration and the routing helpers
# read these at apply time, and guild provisioning is already prefix-aware.
settings.GUILD_ROLE_PREFIX = f"test_{WORKER_ID}_"
settings.PLATFORM_ROLE_PREFIX = f"test_{WORKER_ID}_"

# Per-worker database so a worker's TRUNCATE/DROP never clobbers another's data.
_base_url = settings.DATABASE_URL.rsplit("/", 1)[0]
TEST_DB_NAME = f"initiative_test_{WORKER_ID}"
TEST_DATABASE_URL = f"{_base_url}/{TEST_DB_NAME}"

# Bound any single statement against the test DB so a cross-connection deadlock
# (real-role request connection vs the privileged setup/provisioning connection —
# a wait Postgres can't detect) fails fast and visibly instead of hanging the
# suite. Applied at the DATABASE level so EVERY connection inherits it; set after
# migrations so a slow migration isn't bounded.
TEST_STATEMENT_TIMEOUT = "30s"

BACKEND_DIR = Path(__file__).resolve().parent


async def _ensure_test_database() -> None:
    """Create this worker's test database if it doesn't exist.

    Concurrent xdist workers each ``CREATE DATABASE`` at once; Postgres serializes
    these on a template lock and the losers raise (duplicate / "source database is
    being accessed"), so retry. ``CREATE DATABASE`` can't run inside a transaction,
    hence the autocommit asyncpg connection.
    """
    parsed = urlparse(settings.DATABASE_URL.replace("+asyncpg", ""))
    conn = await asyncpg.connect(
        user=parsed.username,
        password=parsed.password,
        host=parsed.hostname,
        port=parsed.port or 5432,
        database="postgres",
    )
    try:
        for _attempt in range(12):
            exists = await conn.fetchval(
                "SELECT 1 FROM pg_database WHERE datname = $1", TEST_DB_NAME
            )
            if exists:
                return
            try:
                await conn.execute(f'CREATE DATABASE "{TEST_DB_NAME}"')
                return
            except asyncpg.DuplicateDatabaseError:
                return  # another worker won the race; that's fine
            except asyncpg.PostgresError:
                await asyncio.sleep(0.5)  # template locked by a peer; retry
        raise RuntimeError(f"could not create test database {TEST_DB_NAME!r}")
    finally:
        await conn.close()


async def _set_db_statement_timeout() -> None:
    """Apply a DB-level statement_timeout to the worker's test DB (catch-all net
    for cross-connection deadlocks). Affects connections opened afterward."""
    parsed = urlparse(settings.DATABASE_URL.replace("+asyncpg", ""))
    conn = await asyncpg.connect(
        user=parsed.username,
        password=parsed.password,
        host=parsed.hostname,
        port=parsed.port or 5432,
        database="postgres",
    )
    try:
        await conn.execute(
            f'ALTER DATABASE "{TEST_DB_NAME}" SET statement_timeout = '
            f"'{TEST_STATEMENT_TIMEOUT}'"
        )
    finally:
        await conn.close()


# Cross-process lock serializing migrations across xdist workers. The migrations
# touch SHARED cluster-global roles (app_user/app_admin/app_guild_base + GRANTs),
# so concurrent runs collide with "tuple concurrently updated" on the shared pg
# catalog. Workers migrate one at a time under this lock — each still migrates its
# OWN per-worker DB; only the shared role operations are serialized.
_MIGRATION_LOCK = Path(tempfile.gettempdir()) / "initiative_test_migrations.lock"


def _run_test_migrations() -> None:
    """Ensure the worker's test database exists, migrate it, and arm the
    statement_timeout net (after migrations, so a slow migration isn't bounded).

    Serialized across workers via a file lock (see _MIGRATION_LOCK) so the shared
    cluster-global role DDL/GRANTs don't race on the catalog."""
    with open(_MIGRATION_LOCK, "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            asyncio.run(_ensure_test_database())
            config = Config(str(BACKEND_DIR / "alembic.ini"))
            config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
            config.set_main_option("sqlalchemy.url", TEST_DATABASE_URL)
            config.attributes["configure_logger"] = False
            config.attributes["url_configured"] = True
            command.upgrade(config, "head")
            asyncio.run(_set_db_statement_timeout())
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


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


# Guild ids whose schema was provisioned during the CURRENT test. Lets the
# session-teardown SKIP the pg_namespace / pg_roles cleanup scan for the (vast
# majority of) tests that never provision a guild — only a test that actually
# created a guild schema pays for the catalog scan + DROP SCHEMA/ROLE.
_provisioned_guild_ids: set[int] = set()


@pytest.fixture(autouse=True)
def _schema_test_harness(engine, monkeypatch):
    """Make every test schema-per-guild aware.

    - Installs the before_flush router so direct-session (factory) guild-scoped
      writes land in the guild's schema, mirroring what set_rls_context does for
      the request path.
    - Points the (superuser) provisioning engine at the test DB so create_guild /
      the guilds endpoint provision schemas/roles on the test database.
    - Wraps ``provision_guild`` (the universal provisioning choke point — factory,
      guild endpoints, backfill, and conversion all route through it) to record
      which guilds got a schema this test, so teardown can skip its cleanup scan
      when none did.
    """
    import app.db.schema_provisioning as schema_provisioning
    import app.db.session as db_session
    from app.testing.schema_harness import install_guild_routing

    install_guild_routing()
    monkeypatch.setattr(db_session, "provisioning_engine", engine)

    _provisioned_guild_ids.clear()
    _orig_provision_guild = schema_provisioning.provision_guild

    async def _tracking_provision_guild(*args: Any, **kwargs: Any) -> str:
        gid = kwargs.get("guild_id", args[0] if args else None)
        if gid is not None:
            _provisioned_guild_ids.add(int(gid))
        return await _orig_provision_guild(*args, **kwargs)

    monkeypatch.setattr(
        schema_provisioning, "provision_guild", _tracking_provision_guild
    )


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
            # Force ``populate_existing`` on every top-level SELECT this setup
            # session runs. The request path now executes on a SEPARATE connection
            # (real app_user/app_admin), so a read-back assertion here would
            # otherwise return the stale, still-cached instance instead of what the
            # request committed. populate_existing refreshes matched objects' columns
            # from the row (unlike expire_all, it doesn't expire PKs, so building a
            # read-back query from a cached object's id stays a pure in-memory read).
            #
            # BUT only when the session has NO pending writes. The fixture is
            # ``autoflush=False`` (mirrors production), so a service test that mutates
            # in memory without committing — e.g. ``invite.uses += 1`` — and then
            # reads the row back would have its uncommitted change CLOBBERED by a
            # refresh from the (still-0) row. Refreshing is only safe-and-wanted when
            # there's no local pending state to lose; a dirty session keeps the
            # identity-map instance (today's pre-real-role behaviour).
            @event.listens_for(test_session.sync_session, "do_orm_execute")
            def _force_populate_existing(orm_execute_state):
                sess = orm_execute_state.session
                if (
                    orm_execute_state.is_select
                    and not orm_execute_state.is_column_load
                    and not orm_execute_state.is_relationship_load
                    and not (sess.new or sess.dirty or sess.deleted)
                ):
                    orm_execute_state.update_execution_options(populate_existing=True)

            yield test_session

            # Expire all objects to detach them from the session
            test_session.expire_all()

        # Roll back the bound connection explicitly: closing a session bound to an
        # external connection does NOT end that connection's transaction, so the
        # test's trailing reads would keep AccessShare locks on the guild-schema
        # tables — which the teardown's DROP SCHEMA (AccessExclusive) would block on.
        await bound_conn.rollback()
        # Drop any guild/platform role + schema routing the request path's
        # set_rls_context left on this connection, so the superuser cleanup below
        # isn't stuck as a non-superuser role (guild_<id> or platform_<tier>).
        #
        # This reset must be COMMITTED. A write request commits its `SET ROLE`
        # as durable session state; the set_config() below runs in an autobegun
        # transaction that returning the connection to the pool would otherwise
        # roll back — reverting the role to the request's tier. The cleanup then
        # reuses this connection and fails, because `session_replication_role`
        # and TRUNCATE need the superuser. Committing makes the reset stick.
        await bound_conn.exec_driver_sql(
            "SELECT set_config('role', 'none', false), set_config('search_path', 'public', false)"
        )
        await bound_conn.commit()

    # Session is now closed (its rollback released any lock on public.guilds the
    # create-guild endpoint's trailing SELECT left held). Clean up on a fresh
    # connection: drop the per-guild schemas/roles provisioned during the test
    # (cluster-global roles must not leak between tests), then truncate public.
    async with engine.begin() as conn:
        await conn.exec_driver_sql("SET lock_timeout = '10s'")
        # Per-guild schema/role cleanup only matters if THIS test provisioned a
        # guild schema (tracked in _provisioned_guild_ids). Most tests don't, so
        # skip the two catalog scans + DROPs entirely for them.
        roles: list[str] = []
        if _provisioned_guild_ids:
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
        # Truncate all public tables to reset state — one multi-table TRUNCATE
        # (a single round-trip) instead of one statement per table.
        await conn.execute(text("SET session_replication_role = 'replica'"))
        all_tables = ", ".join(
            f'"{table.name}"' for table in SQLModel.metadata.sorted_tables
        )
        await conn.execute(
            text(f"TRUNCATE TABLE {all_tables} RESTART IDENTITY CASCADE")
        )
        await conn.execute(text("SET session_replication_role = 'origin'"))

    # Drop the suite's prefixed roles, each in its own transaction. Prefixed roles
    # are distinct from a co-located dev DB's, so these should succeed — the
    # suppress is belt-and-suspenders so one stuck role can't abort the rest.
    for role in roles:
        with suppress(Exception):
            async with engine.begin() as rconn:
                await rconn.exec_driver_sql("SET lock_timeout = '5s'")
                await rconn.exec_driver_sql(f'DROP OWNED BY "{role}"')
                await rconn.exec_driver_sql(f'DROP ROLE IF EXISTS "{role}"')


# GUC + role reset mirroring the production get_session/get_admin_session
# checkout reset, so each request starts from a clean baseline on the bound
# request connection (a prior request's assumed role can't bleed in).
_REQUEST_RESET_SQL = (
    "SELECT set_config('app.current_user_id', '', false), "
    "set_config('app.current_guild_id', '', false), "
    "set_config('app.current_guild_role', '', false), "
    "set_config('app.is_superadmin', 'false', false), "
    "set_config('app.pam_guild_id', '', false), "
    "set_config('app.pam_read', 'false', false), "
    "set_config('app.pam_write', 'false', false), "
    "set_config('search_path', 'public', false), "
    "set_config('role', 'none', false)"
)


@pytest.fixture
async def client(session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """Async HTTP client whose REQUEST path runs as the REAL ``app_user`` login
    role (RLS-enforced), not the Postgres superuser.

    This is the "no superuser in request execution" model: an authenticated request
    assumes its platform/guild role on top of ``app_user`` (so e.g. a ``member`` is
    bound by member-level RLS), and an unauthenticated request runs as ``app_user`` —
    exactly like production. The superuser-backed ``session`` fixture is still used
    for *data setup* (factories commit, so the request connection sees the rows) and
    for the privileged teardown (TRUNCATE / DROP SCHEMA / DROP ROLE).

    ``AdminSessionDep`` is overridden to a real ``app_admin`` (BYPASSRLS) session,
    mirroring the production admin engine, so bootstrapping endpoints (guild
    creation, background-job style ops) keep their intended RLS bypass instead of
    silently leaning on the superuser.

    Each request/admin session is bound to a single connection so the per-request
    ``SET ROLE`` / ``search_path`` GUCs persist across the request's statements.
    """
    app_engine = create_async_engine(
        _test_url_for_role("app_user"), echo=False, future=True, pool_pre_ping=True
    )
    admin_engine = create_async_engine(
        _test_url_for_role("app_admin"), echo=False, future=True, pool_pre_ping=True
    )
    req_conn = await app_engine.connect()
    admin_conn = await admin_engine.connect()
    # NOTE on deadlocks: the request path (app_user) and admin path (app_admin)
    # are now SEPARATE connections, so an endpoint that locks a row on one and
    # waits on the other can app-level deadlock — a wait Postgres can't detect.
    # The net is the DATABASE-level statement_timeout armed in _run_test_migrations
    # (covers EVERY connection, incl. the privileged setup/provisioning conn that a
    # per-connection SET here would miss — which is what hung admin_test).
    req_session = sessionmaker(
        bind=req_conn, class_=AsyncSession, expire_on_commit=False, autoflush=False
    )()
    admin_session = sessionmaker(
        bind=admin_conn, class_=AsyncSession, expire_on_commit=False, autoflush=False
    )()

    async def _publish_setup_state() -> None:
        """Commit the setup ``session`` so the request — on its OWN real-role
        connection — sees data the test created but had not committed, and so any
        row lock the setup transaction holds is released.

        Before real-role execution, setup and request shared one connection, so
        uncommitted setup was visible to the request. They are now separate
        transactions: factories commit (visible), but a test that sets up via a
        service which defers its commit (e.g. ``ensure_default_statuses``) would
        otherwise leave its rows invisible to the request — or block the request
        on a lock it holds. Flushing+committing at each request boundary mirrors
        production (data must be committed to cross a connection). It is a cheap
        no-op when nothing is pending.
        """
        await session.commit()

    # Mirror production's per-request session lifecycle: ``get_session`` /
    # ``get_admin_session`` yield from ``async with AsyncSessionLocal()``, which
    # rolls back and releases locks when the request ends. The test reuses ONE
    # persistent session per role (bound to a connection so SET ROLE / search_path
    # survive), so it must roll back per request itself — otherwise a handler that
    # leaves an open transaction (e.g. SELECT ... FOR UPDATE then a 4xx without
    # commit) leaks its row locks onto the next request, or onto a follow-up setup
    # write on the SAME row, which then blocks until statement_timeout.
    async def override_get_session() -> AsyncGenerator[AsyncSession, None]:
        await _publish_setup_state()
        await req_session.execute(text(_REQUEST_RESET_SQL))
        try:
            yield req_session
        finally:
            await req_session.rollback()

    async def override_get_admin_session() -> AsyncGenerator[AsyncSession, None]:
        await _publish_setup_state()
        await admin_session.execute(text(_REQUEST_RESET_SQL))
        try:
            yield admin_session
        finally:
            await admin_session.rollback()

    app.dependency_overrides[get_session] = override_get_session
    app.dependency_overrides[get_admin_session] = override_get_admin_session

    # Disable rate limiting in tests
    limiter.enabled = False

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()
        # Release the request/admin connections BEFORE the session-fixture teardown
        # runs its privileged TRUNCATE/DROP SCHEMA (which would block on any lock
        # these idle-in-transaction connections still hold, hanging the NEXT test
        # until its statement_timeout fires).
        #
        # Clean each pair INDEPENDENTLY and best-effort: a failure tearing down the
        # request pair must NOT skip the admin pair (or vice versa) and leak its
        # connection. ``engine.dispose()`` is the guaranteed backstop — it
        # force-closes the pooled connection even if the graceful role-reset above
        # it failed — so it runs for every engine regardless.
        for sess, conn, eng in (
            (req_session, req_conn, app_engine),
            (admin_session, admin_conn, admin_engine),
        ):
            with suppress(Exception):
                await sess.close()
            with suppress(Exception):
                await conn.rollback()
                await conn.exec_driver_sql(
                    "SELECT set_config('role', 'none', false), "
                    "set_config('search_path', 'public', false)"
                )
                await conn.commit()
            with suppress(Exception):
                await conn.close()
            with suppress(Exception):
                await eng.dispose()
        # The create-guild endpoint ends on a SELECT (no commit), so the privileged
        # setup session may hold a lock on public.guilds; release it too.
        with suppress(Exception):
            await session.rollback()


@pytest.fixture
def auth_headers() -> dict[str, str]:
    """
    Base authentication headers.

    Tests that need authentication should use the `acting_user` fixture to mint
    an authenticated user at a chosen platform role.
    """
    return {}


@pytest.fixture
async def acting_user(session):
    """Mint an authenticated test identity with a **required platform role** and an
    **optional guild role** — the single seam for "run this test AS role X".

    The two role dimensions are orthogonal (see the platform-roles design §7):

    * **Platform role — required, defaults to ``owner``.** The platform tier the
      public/platform request path assumes (``platform_<users.role>`` via
      ``get_user_session`` -> ``set_rls_context``). Omit for ``owner`` (most
      privileged, so role-agnostic tests run unblocked); pass a lower tier
      (``member``/``support``/…) to exercise a public-path ceiling. With the
      real-role ``client`` fixture, the request runs AS that platform role on a real
      ``app_user`` connection at the database — RLS enforced, like production.

    * **Guild role — optional, for guild-path testing.** When ``guild_role`` is
      given, the harness also provisions a guild (or uses ``guild=``) and adds the
      user as a member with that ``GuildRole``; the request then routes through
      ``/g/{guild_id}`` and assumes ``guild_<id>`` with ``current_guild_role``.

    Return arity follows the dimensions requested:
        user, headers          = await acting_user()                       # owner, public path
        user, headers          = await acting_user("member")               # member, public path
        user, headers, guild   = await acting_user("member",
                                                   guild_role=GuildRole.admin)  # + guild admin
        await client.get(f"/api/v1/g/{guild.id}/projects", headers=headers)
    """
    from app.models.guild import GuildRole
    from app.models.user import UserRole
    from app.testing import (
        create_guild,
        create_guild_membership,
        create_user,
        get_auth_headers,
    )

    async def _make(
        role: "UserRole | str" = UserRole.owner,
        *,
        guild_role: "GuildRole | str | None" = None,
        guild=None,
        **overrides: Any,
    ):
        if isinstance(role, str):
            role = UserRole(role)
        user = await create_user(session, role=role, **overrides)
        headers = get_auth_headers(user)
        if guild_role is None:
            return user, headers
        if isinstance(guild_role, str):
            guild_role = GuildRole(guild_role)
        if guild is None:
            guild = await create_guild(session)
        await create_guild_membership(session, user=user, guild=guild, role=guild_role)
        return user, headers, guild

    return _make


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
