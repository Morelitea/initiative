"""Every permission key must be reachable by a backfill migration.

A tool that ships adds two ``PermissionKey`` members, and every role created
before that release keeps storing the twelve it already had. Nothing is
mis-authorized — an absent row reads as its default — but the stored role no
longer matches the role the code describes.

The guard is the union of the ``_DEFAULTS`` maps across every migration that
calls :func:`backfill_role_permissions`: if a new tool's keys are in none of
them, the tool shipped without a backfill and this fails with the missing
names.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from sqlalchemy import text

from app.db.role_permission_backfill import role_permission_backfill_sql
from app.models.tenant.initiative import (
    DEFAULT_PERMISSION_VALUES,
    PermissionKey,
)
from app.testing import create_guild, create_initiative, create_user

VERSIONS_DIR = Path(__file__).resolve().parents[2] / "alembic" / "versions"

pytestmark = pytest.mark.unit


def _backfilled_keys() -> set[str]:
    """The permission keys named by some migration's ``_DEFAULTS`` map."""
    keys: set[str] = set()
    for path in VERSIONS_DIR.glob("*.py"):
        source = path.read_text()
        if "backfill_role_permissions" not in source:
            continue
        module = ast.parse(source)
        for node in ast.walk(module):
            if not isinstance(node, ast.AnnAssign | ast.Assign):
                continue
            targets = (
                [node.target] if isinstance(node, ast.AnnAssign) else list(node.targets)
            )
            named = any(
                isinstance(t, ast.Name) and t.id == "_DEFAULTS" for t in targets
            )
            if named and isinstance(node.value, ast.Dict):
                keys.update(
                    k.value
                    for k in node.value.keys
                    if isinstance(k, ast.Constant) and isinstance(k.value, str)
                )
    return keys


def test_every_permission_key_has_a_backfill_migration() -> None:
    missing = {key.value for key in PermissionKey} - _backfilled_keys()
    assert not missing, (
        "These permission keys were added without backfilling the roles that "
        f"predate them: {sorted(missing)}. Add a guild-scoped migration calling "
        "app.db.role_permission_backfill.backfill_role_permissions with a "
        "_DEFAULTS map naming them."
    )


def test_defaults_map_is_exhaustive_and_matches_the_documented_defaults() -> None:
    """The declared defaults cover every key and agree with the model's."""
    assert set(DEFAULT_PERMISSION_VALUES) == set(PermissionKey)


@pytest.mark.integration
async def test_backfill_writes_only_the_missing_rows(session) -> None:
    """A role stripped of a key gets it back at the documented default, and a
    row that already exists is left alone — including one an operator turned
    off."""
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    initiative = await create_initiative(session, guild, user)

    defaults = {key.value: value for key, value in DEFAULT_PERMISSION_VALUES.items()}
    schema = f"guild_{guild.id}"
    await session.exec(text(f'SET LOCAL search_path TO "{schema}", public'))

    roles = (
        await session.exec(
            text(
                "SELECT id, name, is_builtin FROM initiative_roles "
                "WHERE initiative_id = :iid"
            ).bindparams(iid=initiative.id)
        )
    ).all()
    pm = next(r for r in roles if r.name == "project_manager")
    member = next(r for r in roles if r.name == "member")

    # Simulate a tool that shipped after these roles were created: drop the
    # posts rows from both. Then turn a surviving row off, to prove the
    # backfill does not rewrite it.
    await session.exec(
        text(
            "DELETE FROM initiative_role_permissions "
            "WHERE initiative_role_id IN (:pm, :member) "
            "AND permission_key IN ('posts_enabled', 'create_posts')"
        ).bindparams(pm=pm.id, member=member.id)
    )
    await session.exec(
        text(
            "UPDATE initiative_role_permissions SET enabled = false "
            "WHERE initiative_role_id = :pm AND permission_key = 'projects_enabled'"
        ).bindparams(pm=pm.id)
    )

    await session.exec(text(role_permission_backfill_sql(defaults)))

    stored = {
        (row.initiative_role_id, row.permission_key): row.enabled
        for row in (
            await session.exec(
                text(
                    "SELECT initiative_role_id, permission_key, enabled "
                    "FROM initiative_role_permissions "
                    "WHERE initiative_role_id IN (:pm, :member)"
                ).bindparams(pm=pm.id, member=member.id)
            )
        ).all()
    }

    # Restored: the PM gets everything, an ordinary role gets the default.
    assert stored[(pm.id, "posts_enabled")] is True
    assert stored[(pm.id, "create_posts")] is True
    assert stored[(member.id, "posts_enabled")] is False
    assert stored[(member.id, "create_posts")] is False
    # Untouched: the row an operator turned off is still off.
    assert stored[(pm.id, "projects_enabled")] is False
    # Every key now has a row on every role.
    for role_id in (pm.id, member.id):
        assert {k for (r, k) in stored if r == role_id} == set(defaults)
