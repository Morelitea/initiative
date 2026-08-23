"""Database tests for Alembic migrations.

These tests actually exercise every migration on a dedicated Postgres
database to confirm:

* a fresh database can be migrated up to ``head`` end-to-end
* each revision can be applied step-by-step from base to head (so a
  silent failure inside one migration can't be papered over by alembic
  collapsing several into a single transaction)
* the chain can be walked downward from head back to the first
  reversible boundary, then re-applied forward again — this is the
  high-value test for release rollbacks
* the alembic_version stamp matches the script directory's head
* the *most-recent* revision (head) specifically can be applied,
  rolled back, and re-applied — this is the test that fires when
  you just wrote a broken migration

These tests use a separate ``initiative_migrations_test`` database so
they don't disturb the schema-stamped ``initiative_test`` database used
by the rest of the suite. Roles (``app_user`` / ``app_admin``) are
PostgreSQL cluster-global and reused — the baseline migration's role
helpers are idempotent.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Iterator
from urllib.parse import urlparse

import asyncpg
import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

from app.core.config import settings
from conftest import connect_su_postgres
from app.db.tenancy import GUILD_SCOPED_TABLES


ALEMBIC_SCRIPT_LOCATION = Path(__file__).resolve().parent
BACKEND_DIR = ALEMBIC_SCRIPT_LOCATION.parent
ALEMBIC_INI_PATH = BACKEND_DIR / "alembic.ini"

# The baseline is the new root: anything before it was squashed into
# this migration (the v0.53.5 snapshot) and cannot be reached, so its
# ``downgrade()`` is a permanent ``NotImplementedError``.
BASELINE_REVISION = "20260626_0125"

# Migrations whose ``downgrade()`` intentionally raises
# ``NotImplementedError`` and which therefore have to be skipped when
# walking the chain backwards. Add new entries (with a justification
# comment) when introducing other irreversible migrations.
INTENTIONALLY_IRREVERSIBLE = frozenset(
    {
        BASELINE_REVISION,
        # post_squash_reconcile: folds the (never-shipped) 0126–0130 chain —
        # legacy healing + policy strips + grant matrices. It reconciles
        # pre-collapse states that no longer have code paths; roll forward only.
        "20260702_0126",
        # drop_frozen_public_guild_copies: the dropped rows can't be restored,
        # so stamping 0162 back would leave the revision disagreeing with the
        # physical schema. One-way door; restore from a backup instead.
        "20260811_0163",
    }
)

# 20260820_0188 (one author column across the guild schema) and the revision it
# starts from. Named here because the regression test below replays that one
# revision over a hand-made database state.
AUTHOR_RENAME_REVISION = "20260820_0188"
PRE_AUTHOR_RENAME_REVISION = "20260815_0187"

# The guild-content tables whose foreign key into ``public.users`` is named after
# the author column 0188 renames — (table, pre-0188 column name).
AUTHOR_FOREIGN_KEY_TABLES = (
    ("calendars", "created_by_id"),
    ("dashboards", "created_by_id"),
    ("export_jobs", "created_by_id"),
    ("guild_ai_connections", "created_by_user_id"),
    ("guild_apps", "installed_by_id"),
    ("import_jobs", "created_by_id"),
)

# Per-worker so parallel xdist workers don't drop/recreate the same DB. xdist's
# worker id is used verbatim ("gw0"/… distributed, "master" standalone).
_WORKER = os.environ.get("PYTEST_XDIST_WORKER", "master")
MIGRATIONS_DB_NAME = f"initiative_migrations_test_{_WORKER}"
_BASE_DB_URL = settings.DATABASE_URL.rsplit("/", 1)[0]
MIGRATIONS_TEST_DATABASE_URL = f"{_BASE_DB_URL}/{MIGRATIONS_DB_NAME}"

# These tests exercise migration up *and down*, so they CREATE and DROP the
# cluster-global app roles. Use a role prefix distinct from the main suite's
# (conftest sets ``test_{worker}_``) so this file's downgrades never drop the
# roles the rest of the suite depends on. Per-worker too, to stay parallel-safe.
_MIGRATIONS_ROLE_PREFIX = f"migtest_{_WORKER}_"

# Same advisory-lock KEY as conftest._run_test_migrations — a cluster-wide
# pg_advisory_lock serializes ALL migration runs across xdist workers (and across
# both files) so the shared cluster-global role DDL never races. Must stay equal
# to conftest's _MIGRATION_LOCK_KEY. (Portable; replaces a POSIX file lock.)
_MIGRATION_LOCK_KEY = 0x1417A7E5


# ---------------------------------------------------------------------------
# Alembic plumbing
# ---------------------------------------------------------------------------


def _alembic_config(database_url: str) -> Config:
    config = Config(str(ALEMBIC_INI_PATH))
    config.set_main_option("script_location", str(ALEMBIC_SCRIPT_LOCATION))
    config.set_main_option("sqlalchemy.url", database_url)
    config.attributes["url_configured"] = True
    config.attributes["configure_logger"] = False
    return config


def _script_directory() -> ScriptDirectory:
    """Inspect-only ScriptDirectory; uses the test DB url as a placeholder
    because we never actually connect through it."""
    return ScriptDirectory.from_config(_alembic_config(MIGRATIONS_TEST_DATABASE_URL))


def _run_alembic(action: str, revision: str) -> None:
    """Run ``alembic upgrade <revision>`` or ``alembic downgrade <revision>``.

    A fresh Config is built every call so we never reuse a closed engine
    after a previous step.

    The app role prefixes are swapped to this file's dedicated namespace for the
    duration of the migration (the platform-role migration reads them at apply
    time), then restored — so up/down here churns ``migtest_*`` roles, never the
    main suite's ``test_*`` roles.
    """
    asyncio.run(_run_alembic_async(action, revision))


def _alembic_command(action: str, revision: str) -> None:
    """Run the (synchronous) alembic command. Alembic's env.py spins its own event
    loop, so this must run OUTSIDE a running loop — invoked via asyncio.to_thread."""
    config = _alembic_config(MIGRATIONS_TEST_DATABASE_URL)
    if action == "upgrade":
        command.upgrade(config, revision)
    elif action == "downgrade":
        command.downgrade(config, revision)
    else:  # pragma: no cover — guard against typos in test bodies
        raise ValueError(f"Unknown alembic action: {action!r}")


async def _run_alembic_async(action: str, revision: str) -> None:
    # Serialize with the suite's migration advisory lock: even with a distinct role
    # prefix, the baseline still touches SHARED cluster-global roles (e.g. ALTER
    # ROLE app_user), which races ("tuple concurrently updated") against a
    # concurrent worker's migration. The lock rides a dedicated 'postgres'
    # connection (held for the whole migration); the alembic command runs in a
    # worker thread (where it can spin its own loop). Same key as conftest.
    lock_conn = await asyncpg.connect(**_parse_admin_url(), database="postgres")
    try:
        await lock_conn.execute("SELECT pg_advisory_lock($1)", _MIGRATION_LOCK_KEY)
        saved = (settings.GUILD_ROLE_PREFIX, settings.PLATFORM_ROLE_PREFIX)
        settings.GUILD_ROLE_PREFIX = _MIGRATIONS_ROLE_PREFIX
        settings.PLATFORM_ROLE_PREFIX = _MIGRATIONS_ROLE_PREFIX
        try:
            await asyncio.to_thread(_alembic_command, action, revision)
        finally:
            settings.GUILD_ROLE_PREFIX, settings.PLATFORM_ROLE_PREFIX = saved
    finally:
        await lock_conn.close()  # closing the connection releases the advisory lock


async def _run_upgrade_chain_locked_async(revisions: list[str]) -> None:
    """Apply ``revisions`` in order while holding the migration lock for the WHOLE
    chain, asserting the stamp after each step.

    Stepping that releases the lock between revisions (the obvious loop of
    ``_run_alembic`` calls) leaves this worker mid-chain after 0068 created the
    cluster-global ``automation_engine`` role + tables but before 0077 drops them.
    A concurrent worker that grabs the lock and runs ``upgrade head`` then hits
    0077's ``DROP ROLE``, which fails because this DB still has automation tables
    depending on the shared role (``DROP ROLE`` consults the cluster-wide
    ``pg_shdepend``). Holding the lock across the chain keeps that transient window
    invisible to other workers — the only place the suite walks *through* the
    0068→0077 window one step at a time.
    """
    lock_conn = await asyncpg.connect(**_parse_admin_url(), database="postgres")
    try:
        await lock_conn.execute("SELECT pg_advisory_lock($1)", _MIGRATION_LOCK_KEY)
        saved = (settings.GUILD_ROLE_PREFIX, settings.PLATFORM_ROLE_PREFIX)
        settings.GUILD_ROLE_PREFIX = _MIGRATIONS_ROLE_PREFIX
        settings.PLATFORM_ROLE_PREFIX = _MIGRATIONS_ROLE_PREFIX
        try:
            for rev in revisions:
                await asyncio.to_thread(_alembic_command, "upgrade", rev)
                stamp = await _fetch_current_revision_async()
                assert stamp == rev, (
                    f"After upgrading to {rev}, alembic_version is {stamp!r}. "
                    "A migration likely failed silently or skipped a step."
                )
        finally:
            settings.GUILD_ROLE_PREFIX, settings.PLATFORM_ROLE_PREFIX = saved
    finally:
        await lock_conn.close()  # closing the connection releases the advisory lock


def _ordered_revisions_base_to_head() -> list[str]:
    """Return every revision id in apply order (base first, head last)."""
    script = _script_directory()
    return [r.revision for r in list(script.walk_revisions())[::-1]]


# ---------------------------------------------------------------------------
# Direct asyncpg helpers (no sync postgres driver is installed in this repo)
# ---------------------------------------------------------------------------


def _parse_admin_url() -> dict:
    """Connection kwargs for the app's provisioning role (``DATABASE_URL``).

    Everything these tests do *inside* the database runs as this role, exactly
    as migrations do in production. Creating and dropping the database itself
    does not: that is cluster-level, and the provisioning role is deliberately
    ``NOCREATEDB``. ``connect_su_postgres`` covers those two statements.
    """
    parsed = urlparse(settings.DATABASE_URL.replace("+asyncpg", ""))
    return {
        "user": parsed.username,
        "password": parsed.password,
        "host": parsed.hostname,
        "port": parsed.port or 5432,
    }


async def _drop_prefixed_roles(conn: asyncpg.Connection) -> None:
    """Drop this worker's cluster-global roles.

    Roles outlive the database that used them, so a crashed run leaves them
    behind — and a CREATEROLE role holds ADMIN OPTION only on roles it created
    itself, so the provisioning role cannot re-grant a leftover it did not
    make. Clearing them alongside the database keeps each run creating its own.
    Safe to run before the database exists; call it *after* dropping the
    database so no privileges still depend on them.
    """
    rows = await conn.fetch(
        "SELECT rolname FROM pg_roles WHERE rolname LIKE $1",
        f"{_MIGRATIONS_ROLE_PREFIX}%",
    )
    if rows:
        names = ", ".join(f'"{row["rolname"]}"' for row in rows)
        await conn.execute(f"DROP ROLE IF EXISTS {names}")


async def _drop_db() -> None:
    """Drop the dedicated migrations test database and this worker's roles.

    ``DROP DATABASE`` requires no other sessions to be connected. We use
    ``WITH (FORCE)`` (PG 13+) to evict any leftover connections from a
    crashed prior run.
    """
    conn = await connect_su_postgres()
    try:
        await conn.execute(
            f'DROP DATABASE IF EXISTS "{MIGRATIONS_DB_NAME}" WITH (FORCE)'
        )
        await _drop_prefixed_roles(conn)
    finally:
        await conn.close()


async def _drop_and_create_db() -> None:
    """Drop+recreate the dedicated migrations test database.

    Owned by the provisioning role so the migration chain runs against objects
    it owns, the way a real deployment does.
    """
    owner = _parse_admin_url()["user"]
    conn = await connect_su_postgres()
    try:
        await conn.execute(
            f'DROP DATABASE IF EXISTS "{MIGRATIONS_DB_NAME}" WITH (FORCE)'
        )
        await _drop_prefixed_roles(conn)
        await conn.execute(f'CREATE DATABASE "{MIGRATIONS_DB_NAME}" OWNER "{owner}"')
    finally:
        await conn.close()


async def _connect_test_db() -> asyncpg.Connection:
    return await asyncpg.connect(database=MIGRATIONS_DB_NAME, **_parse_admin_url())


async def _fetch_current_revision_async() -> str | None:
    conn = await _connect_test_db()
    try:
        exists = await conn.fetchval(
            "SELECT EXISTS ("
            "  SELECT 1 FROM information_schema.tables "
            "  WHERE table_schema = 'public' AND table_name = 'alembic_version'"
            ")"
        )
        if not exists:
            return None
        return await conn.fetchval("SELECT version_num FROM alembic_version")
    finally:
        await conn.close()


def _current_alembic_revision() -> str | None:
    return asyncio.run(_fetch_current_revision_async())


async def _table_exists_async(table_name: str, schema: str = "public") -> bool:
    conn = await _connect_test_db()
    try:
        return bool(
            await conn.fetchval(
                "SELECT EXISTS ("
                "  SELECT 1 FROM information_schema.tables "
                "  WHERE table_schema = $2 AND table_name = $1"
                ")",
                table_name,
                schema,
            )
        )
    finally:
        await conn.close()


def _table_exists(table_name: str, schema: str = "public") -> bool:
    return asyncio.run(_table_exists_async(table_name, schema))


async def _sequence_exists_async(name: str, schema: str = "public") -> bool:
    conn = await _connect_test_db()
    try:
        return bool(
            await conn.fetchval(
                "SELECT EXISTS ("
                "  SELECT 1 FROM information_schema.sequences "
                "  WHERE sequence_schema = $2 AND sequence_name = $1"
                ")",
                name,
                schema,
            )
        )
    finally:
        await conn.close()


def _sequence_exists(name: str, schema: str = "public") -> bool:
    return asyncio.run(_sequence_exists_async(name, schema))


async def _relation_exists_async(name: str, schema: str = "public") -> bool:
    """Any relation (table, index, sequence, view) by name."""
    conn = await _connect_test_db()
    try:
        return (
            await conn.fetchval("SELECT to_regclass($1)", f"{schema}.{name}")
        ) is not None
    finally:
        await conn.close()


def _relation_exists(name: str, schema: str = "public") -> bool:
    return asyncio.run(_relation_exists_async(name, schema))


async def _constraint_exists_async(table: str, name: str, schema: str = "public"):
    conn = await _connect_test_db()
    try:
        return bool(
            await conn.fetchval(
                "SELECT EXISTS (SELECT 1 FROM pg_constraint "
                "WHERE conname = $1 AND conrelid = to_regclass($2))",
                name,
                f"{schema}.{table}",
            )
        )
    finally:
        await conn.close()


def _constraint_exists(table: str, name: str, schema: str = "public") -> bool:
    return asyncio.run(_constraint_exists_async(table, name, schema))


async def _column_exists_async(table: str, column: str, schema: str) -> bool:
    conn = await _connect_test_db()
    try:
        return bool(
            await conn.fetchval(
                "SELECT EXISTS ("
                "  SELECT 1 FROM information_schema.columns "
                "  WHERE table_schema = $1 AND table_name = $2 AND column_name = $3"
                ")",
                schema,
                table,
                column,
            )
        )
    finally:
        await conn.close()


def _column_exists(table: str, column: str, schema: str = "public") -> bool:
    return asyncio.run(_column_exists_async(table, column, schema))


async def _execute_sql_async(sql: str) -> None:
    conn = await _connect_test_db()
    try:
        await conn.execute(sql)
    finally:
        await conn.close()


def _execute_sql(sql: str) -> None:
    """Run a statement against the migrations test DB (fabricating legacy
    state a fresh database can't produce on its own)."""
    asyncio.run(_execute_sql_async(sql))


async def _alembic_version_row_count_async() -> int:
    conn = await _connect_test_db()
    try:
        return await conn.fetchval("SELECT count(*) FROM alembic_version")
    finally:
        await conn.close()


def _alembic_version_row_count() -> int:
    return asyncio.run(_alembic_version_row_count_async())


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def migrations_db() -> Iterator[str]:
    """Module-scoped fixture: create a clean Postgres database for the
    migration round-trip tests and drop it at teardown."""
    asyncio.run(_drop_and_create_db())
    yield MIGRATIONS_TEST_DATABASE_URL
    try:
        asyncio.run(_drop_db())
    except Exception:
        pass


@pytest.fixture
def fresh_migrations_db(migrations_db: str) -> Iterator[str]:
    """Function-scoped fixture: each test gets a freshly recreated DB so
    state from other tests can never leak in."""
    asyncio.run(_drop_and_create_db())
    yield migrations_db


# ---------------------------------------------------------------------------
# Database tests
# ---------------------------------------------------------------------------


@pytest.mark.database
@pytest.mark.slow
class TestMigrationsAgainstDatabase:
    """End-to-end migration runs against a real Postgres instance."""

    def test_upgrade_to_head_on_fresh_database(self, fresh_migrations_db: str) -> None:
        """The full chain applies cleanly from an empty database."""
        _run_alembic("upgrade", "head")

        head = _script_directory().get_current_head()
        assert _current_alembic_revision() == head, (
            "alembic_version stamp must equal script_directory().get_current_head() "
            "after a successful upgrade"
        )

        # Sanity-check the layout: shared tables in public, tenant content in
        # guild_template — and no tenant table anywhere in public. The whole
        # set, not a sample: public holding one is the bug 20260811_0163 ended.
        for table in ("users", "guilds", "access_grants", "alembic_version"):
            assert _table_exists(table), f"expected table {table!r} after upgrade head"
        for table in ("initiatives", "projects", "tasks", "documents"):
            assert _table_exists(table, schema="guild_template"), (
                f"expected table {table!r} in guild_template after upgrade head"
            )
        for table in sorted(GUILD_SCOPED_TABLES):
            assert not _table_exists(table), (
                f"tenant table {table!r} must not exist in public — guild "
                "content lives only in guild schemas"
            )

    def test_upgrade_head_is_idempotent(self, fresh_migrations_db: str) -> None:
        """Running ``upgrade head`` twice must not raise. Catches
        accidental non-idempotent DDL."""
        _run_alembic("upgrade", "head")
        rev_after_first = _current_alembic_revision()
        _run_alembic("upgrade", "head")
        rev_after_second = _current_alembic_revision()
        assert rev_after_first == rev_after_second, (
            "Repeated `alembic upgrade head` changed the version stamp — "
            "a migration is not idempotent."
        )

    def test_api_key_objects_carry_the_current_table_name(
        self, fresh_migrations_db: str
    ) -> None:
        """20260811_0163 finishes the ``admin_api_keys`` -> ``user_api_keys``
        rename its constraints, indexes and id sequence were left out of — a
        state the baseline froze, so fresh installs have it too.

        The sequence matters most: while it read ``admin_api_keys_id_seq`` on a
        table called ``user_api_keys``, it looked like a leftover the drop
        should sweep, and it is not — it is live.
        """
        _run_alembic("upgrade", "head")

        for name in (
            "user_api_keys_pkey",
            "user_api_keys_token_hash_key",
            "user_api_keys_user_id_fkey",
        ):
            assert _constraint_exists("user_api_keys", name), (
                f"constraint {name!r} must carry the table's current name"
            )
        for old, new in (
            ("ix_admin_api_keys_token_prefix", "ix_user_api_keys_token_prefix"),
            ("ix_admin_api_keys_user_id", "ix_user_api_keys_user_id"),
            ("admin_api_keys_id_seq", "user_api_keys_id_seq"),
        ):
            assert _relation_exists(new), f"{new!r} must exist after the rename"
            assert not _relation_exists(old), f"{old!r} must be gone after the rename"

        # The id sequence is still the live one behind the column.
        assert _sequence_exists("user_api_keys_id_seq")

    def test_drop_removes_a_legacy_public_copy(self, fresh_migrations_db: str) -> None:
        """20260811_0163 drops a frozen pre-squash copy where one exists.

        A fresh database has none (the migration is a no-op there, which the
        other tests cover), so fabricate one — a ``public.tasks`` shell like the
        legacy backstop — and replay the revision over it.
        """
        _run_alembic("upgrade", "head")

        _execute_sql(
            "CREATE TABLE public.tasks "
            "(id serial PRIMARY KEY, guild_id integer NOT NULL)"
        )
        assert _table_exists("tasks")

        # Rewind the stamp rather than downgrading: 0163 is a one-way door, and
        # this is the state it exists for — a database at 0162 still carrying a
        # frozen copy.
        #
        # Replay to 0163 specifically, not to head: the stamp moved but the
        # schema did not, so anything after 0163 would be re-applied over the
        # objects it already created. 0163 is the revision under test; the rest
        # of the chain is covered by the other cases here.
        _execute_sql("UPDATE alembic_version SET version_num = '20260811_0162'")
        _run_alembic("upgrade", "20260811_0163")

        assert not _table_exists("tasks"), (
            "20260811_0163 must drop a frozen public copy of a guild-content table"
        )
        assert not _sequence_exists("tasks_id_seq"), (
            "the dropped copy's owned sequence must go with it"
        )
        assert _sequence_exists("user_api_keys_id_seq"), (
            "the shared user_api_keys id sequence must survive the drop"
        )

    def test_author_rename_skips_foreign_keys_a_guild_schema_lacks(
        self, fresh_migrations_db: str
    ) -> None:
        """20260820_0188 renames the foreign keys named after the author column,
        and a guild schema built by the app's provisioner has none of them.

        ``app.db.guild_ddl`` renders intra-schema references only — a reference
        to ``public.users`` is left soft, because the schema is the tenant
        boundary — so a guild created that way carries the author column without
        the key, while ``guild_template`` and the guilds provisioned before that
        renderer carry both. Both shapes are live in the field, so the rename has
        to ask rather than assume: it stopped every upgrade that had one of the
        first kind (issue #1218).

        A fresh database has only ``guild_template``, which does carry the keys,
        so the other shape is fabricated here — drop them, then replay the
        revision over it, in both directions.
        """
        _run_alembic("upgrade", "head")
        _run_alembic("downgrade", PRE_AUTHOR_RENAME_REVISION)

        for table, column in AUTHOR_FOREIGN_KEY_TABLES:
            name = f"{table}_{column}_fkey"
            assert _constraint_exists(table, name, schema="guild_template"), (
                f"expected {name!r} before the fabrication — the shape this test "
                "removes must be the one the migration chain produces"
            )
            _execute_sql(f"ALTER TABLE guild_template.{table} DROP CONSTRAINT {name}")

        _run_alembic("upgrade", "head")

        for table, _column in AUTHOR_FOREIGN_KEY_TABLES:
            assert _column_exists(table, "created_by", schema="guild_template"), (
                f"{table}.created_by must be renamed whether or not a foreign "
                "key carries the old name"
            )
            assert not _constraint_exists(
                table, f"{table}_created_by_fkey", schema="guild_template"
            ), "a key that wasn't there must not be conjured by the rename"

        # The reverse has the same two shapes to survive.
        _run_alembic("downgrade", PRE_AUTHOR_RENAME_REVISION)
        for table, column in AUTHOR_FOREIGN_KEY_TABLES:
            assert _column_exists(table, column, schema="guild_template")

    def test_step_by_step_upgrade_from_base_to_head(
        self, fresh_migrations_db: str
    ) -> None:
        """Apply each revision one at a time and check the stamp after
        every step. Catches partial failures that ``upgrade head``
        might paper over."""
        revisions = _ordered_revisions_base_to_head()
        # Make the chain-order invariant explicit: revisions[0] must be
        # the baseline. Without this, a misconfigured chain that placed
        # something before the baseline would cause the slice below to
        # silently skip a real migration.
        assert revisions[0] == BASELINE_REVISION, (
            f"Expected first revision to be the baseline {BASELINE_REVISION!r}, "
            f"got {revisions[0]!r}. The migration chain is misconfigured."
        )

        # Hold the migration lock across the whole chain (not per step) so the
        # transient cluster-global automation_engine role (0068→0077) is never
        # exposed to a concurrent worker's DROP ROLE. See the helper's docstring.
        asyncio.run(_run_upgrade_chain_locked_async(revisions))

    def test_full_round_trip_down_to_first_reversible_then_back(
        self, fresh_migrations_db: str
    ) -> None:
        """Walks: base → head → (down across every reversible migration) → head.

        Stops the downgrade at the first migration above an irreversible
        boundary. Every reversible downgrade actually runs; missing or
        broken downgrades are the main cause of broken release
        rollbacks, so this is the single highest-value DB test here.
        """
        script = _script_directory()
        head = script.get_current_head()

        # The reversible walk normally starts at the head. But when the head
        # (or a run of revisions below it) is intentionally irreversible — its
        # own ``downgrade()`` raises — we can't descend through it, so anchor
        # the walk at the highest reversible revision by stepping down past
        # every irreversible one at the top. Every reachable reversible
        # downgrade below the boundary still runs; the irreversible heads' own
        # upgrades are covered by the TestMostRecentRevision tests.
        anchor = head
        while anchor in INTENTIONALLY_IRREVERSIBLE:
            parent = script.get_revision(anchor).down_revision
            if parent is None:
                # Walked off the base: the entire chain is irreversible (e.g.
                # right after a squash — only the baseline + reconciler exist,
                # both roll-forward-only). Nothing reversible to round-trip;
                # TestMostRecentRevision covers the head's own upgrade.
                pytest.skip("no reversible migration above the irreversible baseline")
            assert isinstance(parent, str), (
                f"Irreversible revision {anchor!r} has multiple parents "
                f"{parent!r}; the round-trip walk only handles linear chains."
            )
            anchor = parent

        _run_alembic("upgrade", anchor)
        assert _current_alembic_revision() == anchor

        steps_taken = 0
        while True:
            current = _current_alembic_revision()
            assert current is not None
            if current in INTENTIONALLY_IRREVERSIBLE:
                # We're now at an irreversible revision — its own
                # ``downgrade()`` would raise. Stop here.
                break
            rev_obj = script.get_revision(current)
            parent = rev_obj.down_revision
            if parent is None:
                break  # at base
            # Fail loud on merge revisions (down_revision is a tuple) — the
            # stamp-equality check below would silently false-fail otherwise.
            assert isinstance(parent, str), (
                f"Revision {current} has multiple parents {parent!r}; the "
                "round-trip walk only handles linear chains. If a merge "
                "migration is intentional, extend this loop to handle it."
            )
            _run_alembic("downgrade", "-1")
            steps_taken += 1
            stamp = _current_alembic_revision()
            assert stamp == parent, (
                f"downgrade -1 from {current} should land on {parent}, got {stamp!r}"
            )

        assert steps_taken > 0, (
            "Expected at least one reversible migration above the "
            "irreversible boundary; took zero steps. Check "
            "INTENTIONALLY_IRREVERSIBLE."
        )

        _run_alembic("upgrade", anchor)
        assert _current_alembic_revision() == anchor

    def test_baseline_downgrade_raises(self, fresh_migrations_db: str) -> None:
        """The baseline cannot be downgraded — verify it actually raises
        rather than silently succeeding."""
        _run_alembic("upgrade", BASELINE_REVISION)
        with pytest.raises(NotImplementedError):
            _run_alembic("downgrade", "base")

    def test_alembic_version_table_has_single_row_after_upgrade(
        self, fresh_migrations_db: str
    ) -> None:
        """A common corruption mode is multiple rows in
        ``alembic_version`` after a botched merge. ``upgrade head`` must
        keep the table at exactly one row."""
        _run_alembic("upgrade", "head")
        assert _alembic_version_row_count() == 1


@pytest.mark.database
@pytest.mark.slow
class TestMostRecentRevision:
    """Targeted tests against the most-recent (head) revision.

    These give a tight signal when *the migration you just wrote* is
    broken. They run faster than the full chain walk because they only
    exercise the head revision in isolation: bring the database to
    head's parent, then upgrade by one step and (if the head is
    reversible) downgrade and re-upgrade.

    Failures here mean the newest migration on the chain — the one
    most likely to be wrong because it's the one you just changed —
    cannot be applied, cannot be rolled back, or cannot be re-applied
    after a rollback.
    """

    def test_head_upgrade_from_parent(self, fresh_migrations_db: str) -> None:
        """Upgrade to the head's parent, then apply the head. Isolates
        failures in the newest migration from failures earlier in the
        chain."""
        script = _script_directory()
        head = script.get_current_head()
        assert head is not None, "alembic could not determine a head revision"

        head_rev = script.get_revision(head)
        parent = head_rev.down_revision
        assert isinstance(parent, str) and parent, (
            f"Head revision {head!r} has no single parent (down_revision={parent!r}); "
            "the chain may have branched."
        )

        _run_alembic("upgrade", parent)
        assert _current_alembic_revision() == parent, (
            f"Could not stage the database at head's parent {parent!r}"
        )

        _run_alembic("upgrade", head)
        assert _current_alembic_revision() == head, (
            f"Applying the head revision {head!r} did not advance the stamp "
            "as expected — the newest migration's upgrade() is broken."
        )

    def test_head_downgrade_then_reapply(self, fresh_migrations_db: str) -> None:
        """If the head is reversible, downgrading by one step from head
        and re-applying must round-trip cleanly. Exercises the newest
        migration's downgrade() and proves a release rollback would
        work right now."""
        script = _script_directory()
        head = script.get_current_head()
        assert head is not None

        if head in INTENTIONALLY_IRREVERSIBLE:
            pytest.skip(
                f"Head revision {head} is intentionally irreversible; "
                "cannot test downgrade round-trip."
            )

        head_rev = script.get_revision(head)
        parent = head_rev.down_revision
        assert isinstance(parent, str) and parent

        _run_alembic("upgrade", "head")
        assert _current_alembic_revision() == head

        _run_alembic("downgrade", "-1")
        assert _current_alembic_revision() == parent, (
            f"Downgrading from head {head!r} should land on {parent!r}, "
            f"got {_current_alembic_revision()!r}. The newest migration's "
            "downgrade() is broken or incomplete."
        )

        _run_alembic("upgrade", head)
        assert _current_alembic_revision() == head, (
            f"Re-upgrading to head {head!r} after downgrade failed. The "
            "newest migration is not reversible end-to-end (downgrade may "
            "leave behind state that the upgrade does not expect)."
        )

    def test_head_upgrade_is_idempotent(self, fresh_migrations_db: str) -> None:
        """Re-running the head migration after it's already applied
        must be a no-op. Catches accidental ``CREATE`` / ``ADD COLUMN``
        without ``IF NOT EXISTS`` guards on the newest migration."""
        _run_alembic("upgrade", "head")
        head_first = _current_alembic_revision()
        _run_alembic("upgrade", "head")
        head_second = _current_alembic_revision()
        assert head_first == head_second
        assert head_second == _script_directory().get_current_head()
