"""The moderator backfill, run against a schema shaped like a real upgrade.

A fresh install has no guilds when the migration runs, so its own loop never
meets an initiative — CI would be green on a statement that reaches nothing.
This builds the shape an existing deployment has (roles as they were before the
moderator existed, a community admin sitting on the project manager role, and an
initiative that already used the name) and runs the statements the migration
itself carries, forwards and back.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest
from sqlalchemy import text

from app.models.platform.guild import GuildRole
from app.models.tenant.initiative import PermissionKey
from app.testing import (
    create_guild,
    create_guild_membership,
    create_initiative,
    create_user,
)

MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "20260913_0265_moderator_is_a_built_in_role.py"
)

pytestmark = pytest.mark.integration


def _load(path: Path) -> ModuleType:
    """Import a migration by path — they are not on the import path."""
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def _roles(session, initiative_id: int) -> dict[str, dict]:
    rows = (
        await session.exec(
            text(
                "SELECT id, name, display_name, is_builtin, is_manager, "
                '"position", override_share_restrictions '
                "FROM initiative_roles WHERE initiative_id = :iid"
            ).bindparams(iid=initiative_id)
        )
    ).all()
    return {row.name: row._mapping for row in rows}


async def _role_name_of(session, initiative_id: int, user_id: int) -> str:
    return (
        await session.exec(
            text(
                "SELECT r.name FROM initiative_members m "
                "JOIN initiative_roles r ON r.id = m.role_id "
                "WHERE m.initiative_id = :iid AND m.user_id = :uid"
            ).bindparams(iid=initiative_id, uid=user_id)
        )
    ).one()[0]


async def _wind_back(session, initiative_id: int, admin_id: int) -> None:
    """Undo what the app now creates, leaving the pre-moderator shape: no
    moderator role, Full access on the project manager, and the community admin
    sitting on it."""
    await session.exec(
        text(
            "DELETE FROM initiative_roles "
            "WHERE initiative_id = :iid AND name = 'moderator'"
        ).bindparams(iid=initiative_id)
    )
    await session.exec(
        text(
            'UPDATE initiative_roles SET "position" = "position" - 1, '
            "override_share_restrictions = (name = 'project_manager') "
            "WHERE initiative_id = :iid"
        ).bindparams(iid=initiative_id)
    )
    await session.exec(
        text(
            "UPDATE initiative_members SET role_id = "
            "(SELECT id FROM initiative_roles WHERE initiative_id = :iid "
            "AND name = 'project_manager') "
            "WHERE initiative_id = :iid AND user_id = :uid"
        ).bindparams(iid=initiative_id, uid=admin_id)
    )


async def test_the_backfill_creates_the_role_and_moves_the_admins(session) -> None:
    migration = _load(MIGRATION)

    admin = await create_user(session)
    guild = await create_guild(session, creator=admin)
    await create_guild_membership(
        session, user=admin, guild=guild, role=GuildRole.admin
    )
    initiative = await create_initiative(session, guild, admin)

    await session.exec(text(f'SET LOCAL search_path TO "guild_{guild.id}", public'))
    await _wind_back(session, initiative.id, admin.id)

    # An initiative that spent the name on a role of its own — and that also
    # holds the name the rename reaches for first.
    await session.exec(
        text(
            "INSERT INTO initiative_roles "
            '(initiative_id, name, display_name, is_builtin, is_manager, "position") '
            "VALUES (:iid, 'moderator', 'Room mods', false, false, 9)"
        ).bindparams(iid=initiative.id)
    )
    taken = (
        await session.exec(
            text(
                "SELECT id FROM initiative_roles "
                "WHERE initiative_id = :iid AND name = 'moderator'"
            ).bindparams(iid=initiative.id)
        )
    ).one()[0]
    await session.exec(
        text(
            "INSERT INTO initiative_roles "
            '(initiative_id, name, display_name, is_builtin, is_manager, "position") '
            "VALUES (:iid, :name, 'Already called that', false, false, 10)"
        ).bindparams(iid=initiative.id, name=f"moderator_{taken}")
    )

    # Somebody who is not a community admin, holding the project manager role
    # while it carried Full access.
    lead = await create_user(session, email="lead@example.com")
    await create_guild_membership(session, user=lead, guild=guild)
    await session.exec(
        text(
            "INSERT INTO initiative_members (initiative_id, user_id, guild_id, "
            "role_id, joined_at) SELECT :iid, :uid, :gid, id, now() "
            "FROM initiative_roles "
            "WHERE initiative_id = :iid AND name = 'project_manager'"
        ).bindparams(iid=initiative.id, uid=lead.id, gid=guild.id)
    )

    connection = await session.connection()
    created, moved = await connection.run_sync(
        lambda sync_connection: migration.apply_to_routed_schema(
            sync_connection, f"guild_{guild.id}"
        )
    )
    assert (created, moved) == (1, 2)

    roles = await _roles(session, initiative.id)
    moderator = roles["moderator"]
    assert moderator["is_builtin"] is True
    assert moderator["is_manager"] is True
    assert moderator["override_share_restrictions"] is True
    assert moderator["position"] == 0

    # The roles that were already there moved down to make room.
    assert roles["project_manager"]["position"] == 1
    assert roles["member"]["position"] == 2

    # Full access left the project manager.
    assert roles["project_manager"]["override_share_restrictions"] is False

    # The role that had the name kept everything but the name, and the role
    # already called what the rename reaches for first kept its own.
    assert roles[f"moderator_{taken}"]["display_name"] == "Already called that"
    assert roles[f"moderator_{taken}_1"]["display_name"] == "Room mods"

    # Every tool, as the project manager holds them.
    granted = (
        await session.exec(
            text(
                "SELECT permission_key FROM initiative_role_permissions "
                "WHERE initiative_role_id = :rid AND enabled"
            ).bindparams(rid=moderator["id"])
        )
    ).all()
    assert {row[0] for row in granted} == {key.value for key in PermissionKey}

    assert await _role_name_of(session, initiative.id, admin.id) == "moderator"
    # Nobody's reach narrows: the project manager who had Full access holds it
    # on the role that carries it now.
    assert await _role_name_of(session, initiative.id, lead.id) == "moderator"


async def test_the_backfill_reverses(session) -> None:
    """The downgrade puts Full access back where the older shape can hold it.

    An initiative whose only moderator is a community admin does not get it: the
    admin's reach comes from their community standing, and the switch would hand
    Full access to every project manager there as well.
    """
    migration = _load(MIGRATION)

    admin = await create_user(session)
    guild = await create_guild(session, creator=admin)
    await create_guild_membership(
        session, user=admin, guild=guild, role=GuildRole.admin
    )
    admin_only = await create_initiative(session, guild, admin, name="Admin only")
    shared = await create_initiative(session, guild, admin, name="Shared")

    lead = await create_user(session, email="lead@example.com")
    await create_guild_membership(session, user=lead, guild=guild)

    await session.exec(text(f'SET LOCAL search_path TO "guild_{guild.id}", public'))
    for initiative in (admin_only, shared):
        await _wind_back(session, initiative.id, admin.id)
    await session.exec(
        text(
            "INSERT INTO initiative_members (initiative_id, user_id, guild_id, "
            "role_id, joined_at) SELECT :iid, :uid, :gid, id, now() "
            "FROM initiative_roles "
            "WHERE initiative_id = :iid AND name = 'project_manager'"
        ).bindparams(iid=shared.id, uid=lead.id, gid=guild.id)
    )

    connection = await session.connection()
    await connection.run_sync(
        lambda sync_connection: migration.apply_to_routed_schema(
            sync_connection, f"guild_{guild.id}"
        )
    )
    await connection.run_sync(migration.revert_in_routed_schema)

    for initiative in (admin_only, shared):
        roles = await _roles(session, initiative.id)
        assert "moderator" not in roles
        assert roles["project_manager"]["position"] == 0
        assert roles["member"]["position"] == 1
        assert (
            await _role_name_of(session, initiative.id, admin.id) == "project_manager"
        )

    assert (await _roles(session, shared.id))["project_manager"][
        "override_share_restrictions"
    ] is True
    assert (await _roles(session, admin_only.id))["project_manager"][
        "override_share_restrictions"
    ] is False
