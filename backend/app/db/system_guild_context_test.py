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

pytestmark = pytest.mark.integration


def _load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location(MIGRATION.stem, MIGRATION)
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

    expected = {
        (table, verb)
        for table, verbs in migration.SYSTEM_GUILD_MAINTENANCE_GRANTS.items()
        for verb in verbs.split(", ")
    }
    assert expected <= await direct_table_grants()

    async with engine.begin() as connection:
        await connection.run_sync(
            lambda sync: migration._revoke_from_schema(sync, schema)
        )

    remaining = await direct_table_grants()
    assert expected.isdisjoint(remaining)
    assert ("uploads", "SELECT") in remaining
