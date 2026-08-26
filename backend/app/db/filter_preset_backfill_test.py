"""The seed backfill in migration 0195 reaches projects that already exist."""

import importlib.util
import pathlib

import pytest
from sqlalchemy import text
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.session import set_rls_context
from app.services.tenant import filter_presets as filter_presets_service
from app.testing.factories import (
    create_guild,
    create_initiative,
    create_project,
    create_user,
)

pytestmark = [pytest.mark.integration, pytest.mark.service]

MIGRATION = (
    pathlib.Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "20260826_0195_add_project_filter_presets.py"
)


def _seed_sql() -> str:
    """The backfill statement, read from the migration that ships it.

    Loaded by path rather than by name: a revision file starts with a digit, so
    it is not an importable module. Importing it is safe — the module only
    binds ``op`` at import time and never calls it at module level.
    """
    spec = importlib.util.spec_from_file_location("migration_0195", MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module._DEFAULT_PRESETS_SQL


async def test_backfill_seeds_an_existing_project_once(session: AsyncSession):
    seed_sql = _seed_sql()

    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    initiative = await create_initiative(session, guild, user)
    project = await create_project(session, initiative, user)
    await session.commit()

    # A project from before presets existed: no rows at all.
    await set_rls_context(
        session, user_id=user.id, guild_id=guild.id, guild_role="admin"
    )
    await session.exec(text("DELETE FROM project_filter_presets"))
    await session.commit()
    assert await filter_presets_service.list_presets(session, project.id) == []

    await session.exec(text(seed_sql))
    await session.commit()

    presets = await filter_presets_service.list_presets(session, project.id)
    assert [p.slug for p in presets] == ["all", "incomplete", "unassigned", "mine"]
    assert [p.is_default for p in presets] == [True, False, False, False]
    assert presets[1].filters == {
        "status_categories": ["backlog", "todo", "in_progress"]
    }
    # guild_id is filled by the trigger, not by the statement's SELECT alone.
    assert all(p.guild_id == guild.id for p in presets)

    # Re-running it is a no-op (WHERE NOT EXISTS).
    await session.exec(text(seed_sql))
    await session.commit()
    assert len(await filter_presets_service.list_presets(session, project.id)) == 4
