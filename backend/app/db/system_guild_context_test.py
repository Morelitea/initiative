"""The narrow, fail-closed guild route used by account erasure."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest
from sqlalchemy import text

from app.db.session import set_system_guild_context
from app.testing.factories import (
    create_comment,
    create_guild,
    create_initiative,
    create_project,
    create_task,
    create_user,
)

MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "20260916_0278_system_account_erasure_route.py"
)

OUTBOX_SCAN_MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "20260921_0346_the_poller_scans_the_log_as_the_system.py"
)

pytestmark = pytest.mark.integration

_EXPECTED_TABLE_GRANTS = {
    ("comments", "SELECT"),
    ("comments", "UPDATE"),
    ("documents", "SELECT"),
    ("documents", "UPDATE"),
    ("projects", "SELECT"),
    ("posts", "SELECT"),
    ("posts", "UPDATE"),
    ("queues", "SELECT"),
    ("search_entries", "DELETE"),
    ("task_assignment_digest_items", "SELECT"),
    ("task_assignment_digest_items", "UPDATE"),
    ("tasks", "SELECT"),
    ("counter_groups", "SELECT"),
    ("calendars", "SELECT"),
    ("dashboards", "SELECT"),
    ("galleries", "SELECT"),
    ("initiatives", "SELECT"),
}

_EXPECTED_COLUMN_GRANTS = {
    ("event_outbox", "txn_id", "INSERT"),
    ("event_outbox", "occurred_at", "INSERT"),
    ("event_outbox", "actor_user_id", "INSERT"),
    ("event_outbox", "initiative_id", "INSERT"),
    ("event_outbox", "resource_type", "INSERT"),
    ("event_outbox", "resource_id", "INSERT"),
    ("event_outbox", "action", "INSERT"),
    ("event_outbox", "changed", "INSERT"),
    ("event_outbox", "parents", "INSERT"),
    ("search_entries", "entity_type", "SELECT"),
    ("search_entries", "entity_id", "SELECT"),
    ("search_entries", "entity_type", "INSERT"),
    ("search_entries", "entity_id", "INSERT"),
    ("search_entries", "chunk_ix", "INSERT"),
    ("search_entries", "initiative_id", "INSERT"),
    ("search_entries", "dac_tool", "INSERT"),
    ("search_entries", "dac_id", "INSERT"),
    ("search_entries", "title", "INSERT"),
    ("search_entries", "body", "INSERT"),
    ("search_entries", "archived", "INSERT"),
    ("search_entries", "template", "INSERT"),
    ("search_entries", "updated_at", "INSERT"),
    ("search_entries", "tsv", "INSERT"),
}

_EXPECTED_SEQUENCE_GRANTS = {("event_outbox_id_seq", "USAGE")}


_EXPECTED_OUTBOX_SCAN_COLUMN_GRANTS = {
    ("event_outbox", "id", "SELECT"),
    ("event_outbox", "txn_id", "SELECT"),
    ("webhook_deliveries", "subscription_id", "SELECT"),
    ("webhook_deliveries", "txn_id", "SELECT"),
    ("webhook_deliveries", "delivered_at", "SELECT"),
    ("webhook_deliveries", "dead_lettered_at", "SELECT"),
    ("webhook_deliveries", "next_attempt_at", "SELECT"),
}


def _load_migration(path: Path = MIGRATION) -> ModuleType:
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def test_system_guild_route_keeps_app_admin_bypass_and_denies_app_user(
    session, role_session
) -> None:
    owner = await create_user(session)
    guild = await create_guild(session, creator=owner)
    initiative = await create_initiative(session, guild, owner)
    project = await create_project(session, initiative, owner)
    task = await create_task(session, project)
    await create_comment(session, owner, task=task, content="private")

    admin = await role_session("app_admin")
    await set_system_guild_context(admin, guild_id=guild.id)
    identity = (
        await admin.exec(
            text(
                "SELECT current_user, session_user, rolbypassrls, current_schema() "
                "FROM pg_roles WHERE rolname = current_user"
            )
        )
    ).one()
    assert identity == ("app_admin", "app_admin", True, f"guild_{guild.id}")
    assert (await admin.exec(text("SELECT count(*) FROM comments"))).one()[0] == 1

    request_session = await role_session("app_user")
    with pytest.raises(
        PermissionError,
        match="system guild routing requires the configured system login",
    ):
        await set_system_guild_context(request_session, guild_id=guild.id)


async def test_migration_backfills_and_reverses_only_its_direct_grants(
    session, engine
) -> None:
    migration = _load_migration()
    owner = await create_user(session)
    guild = await create_guild(session, creator=owner)
    schema = f"guild_{guild.id}"

    async with engine.begin() as connection:
        await connection.run_sync(
            lambda sync: migration._revoke_from_schema(sync, schema)
        )
        # An unrelated direct grant proves downgrade does not use a broad
        # REVOKE over the schema's tables.
        await connection.execute(
            text(f'GRANT SELECT ON TABLE "{schema}".uploads TO app_admin')
        )
        await connection.run_sync(lambda sync: migration._grant_to_schema(sync, schema))

    async def direct_table_grants() -> set[tuple[str, str]]:
        rows = (
            await session.exec(
                text(
                    "SELECT table_name, privilege_type "
                    "FROM information_schema.role_table_grants "
                    "WHERE grantee = 'app_admin' AND table_schema = :schema"
                ),
                params={"schema": schema},
            )
        ).all()
        return {(str(row[0]), str(row[1])) for row in rows}

    async def direct_column_grants() -> set[tuple[str, str, str]]:
        rows = (
            await session.exec(
                text(
                    "SELECT table_name, column_name, privilege_type "
                    "FROM information_schema.role_column_grants "
                    "WHERE grantee = 'app_admin' AND table_schema = :schema"
                ),
                params={"schema": schema},
            )
        ).all()
        return {(str(row[0]), str(row[1]), str(row[2])) for row in rows}

    async def direct_sequence_grants() -> set[tuple[str, str]]:
        rows = (
            await session.exec(
                text(
                    "SELECT object_name, privilege_type "
                    "FROM information_schema.role_usage_grants "
                    "WHERE grantee = 'app_admin' AND object_schema = :schema "
                    "AND object_type = 'SEQUENCE'"
                ),
                params={"schema": schema},
            )
        ).all()
        return {(str(row[0]), str(row[1])) for row in rows}

    assert _EXPECTED_TABLE_GRANTS <= await direct_table_grants()
    assert _EXPECTED_COLUMN_GRANTS <= await direct_column_grants()
    assert _EXPECTED_SEQUENCE_GRANTS <= await direct_sequence_grants()

    async with engine.begin() as connection:
        await connection.run_sync(
            lambda sync: migration._revoke_from_schema(sync, schema)
        )

    remaining_tables = await direct_table_grants()
    assert _EXPECTED_TABLE_GRANTS.isdisjoint(remaining_tables)
    assert _EXPECTED_COLUMN_GRANTS.isdisjoint(await direct_column_grants())
    assert _EXPECTED_SEQUENCE_GRANTS.isdisjoint(await direct_sequence_grants())
    assert ("uploads", "SELECT") in remaining_tables


async def test_outbox_scan_migration_grants_only_its_columns(session, engine) -> None:
    """The poller's candidate scan keeps BYPASSRLS on exactly the columns it
    reads. The migration adds those, and reversing it removes those and nothing
    else — the erasure route's grants from 0278 are left standing."""
    migration = _load_migration(OUTBOX_SCAN_MIGRATION)
    owner = await create_user(session)
    guild = await create_guild(session, creator=owner)
    schema = f"guild_{guild.id}"

    async def direct_column_grants() -> set[tuple[str, str, str]]:
        rows = (
            await session.exec(
                text(
                    "SELECT table_name, column_name, privilege_type "
                    "FROM information_schema.role_column_grants "
                    "WHERE grantee = 'app_admin' AND table_schema = :schema"
                ),
                params={"schema": schema},
            )
        ).all()
        return {(str(row[0]), str(row[1]), str(row[2])) for row in rows}

    async with engine.begin() as connection:
        await connection.run_sync(
            lambda sync: migration._revoke_from_schema(sync, schema)
        )
    assert _EXPECTED_OUTBOX_SCAN_COLUMN_GRANTS.isdisjoint(await direct_column_grants())

    async with engine.begin() as connection:
        await connection.run_sync(lambda sync: migration._grant_to_schema(sync, schema))
    after_upgrade = await direct_column_grants()
    assert _EXPECTED_OUTBOX_SCAN_COLUMN_GRANTS <= after_upgrade
    # The erasure route's INSERT grants on the same table are untouched.
    assert ("event_outbox", "txn_id", "INSERT") in after_upgrade

    async with engine.begin() as connection:
        await connection.run_sync(
            lambda sync: migration._revoke_from_schema(sync, schema)
        )
    after_downgrade = await direct_column_grants()
    assert _EXPECTED_OUTBOX_SCAN_COLUMN_GRANTS.isdisjoint(after_downgrade)
    assert ("event_outbox", "txn_id", "INSERT") in after_downgrade
