"""Content that predates the index gets indexed.

The refresh trigger only sees writes that happen after it exists, so a guild's
existing work would be absent from search until each row was next touched. The
sweep walks each source table and writes the same entries the trigger would,
and a generation marker on the guild's ``search_entries`` records what it was
last swept for.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlmodel import select

from app.db import session as db_session
from app.db.schema_provisioning import reindex_guild_search
from app.db.search_index import search_generation
from app.db.session import set_rls_context
from app.models.platform.guild import GuildRole
from app.models.tenant.search_entry import SearchEntry
from app.testing import create_project, create_tag, create_task

pytestmark = pytest.mark.integration


async def _entries(session, guild_id: int, entity_type: str) -> list[SearchEntry]:
    await set_rls_context(session, guild_id=guild_id, guild_role="admin")
    return list(
        await session.exec(
            select(SearchEntry).where(SearchEntry.entity_type == entity_type)
        )
    )


async def _wipe(guild_id: int) -> None:
    """Leave the guild looking like one whose content predates the index.

    Through the provisioning engine: it owns these tables, which commenting on
    them requires.
    """
    async with db_session.provisioning_engine.begin() as conn:
        await conn.exec_driver_sql(f'DELETE FROM "guild_{guild_id}".search_entries')
        await conn.exec_driver_sql(
            f'COMMENT ON TABLE "guild_{guild_id}".search_entries IS NULL'
        )


async def test_it_indexes_content_that_predates_the_index(session, acting_user):
    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)
    task = await create_task(session, a.project, title="vendor renewal terms")
    tag = await create_tag(session, a.guild, name="urgent")
    await _wipe(a.guild.id)
    assert await _entries(session, a.guild.id, "task") == []

    written = await reindex_guild_search(
        db_session.provisioning_engine, f"guild_{a.guild.id}"
    )
    assert written > 0

    tasks = await _entries(session, a.guild.id, "task")
    assert [r.title for r in tasks if r.entity_id == task.id] == [
        "vendor renewal terms"
    ]
    tags = await _entries(session, a.guild.id, "tag")
    assert [r.title for r in tags if r.entity_id == tag.id] == ["urgent"]


async def test_the_swept_rows_carry_the_same_identity_the_trigger_writes(
    session, acting_user
):
    """A swept row and a trigger-written row must be interchangeable, or search
    would rank and gate them differently."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)
    task = await create_task(session, a.project, title="quarterly report")
    before = next(
        r for r in await _entries(session, a.guild.id, "task") if r.entity_id == task.id
    )
    fields = (before.initiative_id, before.dac_tool, before.dac_id, before.title)

    await _wipe(a.guild.id)
    await reindex_guild_search(db_session.provisioning_engine, f"guild_{a.guild.id}")

    after = next(
        r for r in await _entries(session, a.guild.id, "task") if r.entity_id == task.id
    )
    assert (after.initiative_id, after.dac_tool, after.dac_id, after.title) == fields


async def test_soft_deleted_content_is_not_swept_in(session, acting_user):
    from datetime import datetime, timezone

    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)
    task = await create_task(session, a.project, title="trashed")
    task.deleted_at = datetime.now(timezone.utc)
    session.add(task)
    await session.commit()
    await _wipe(a.guild.id)

    await reindex_guild_search(db_session.provisioning_engine, f"guild_{a.guild.id}")
    assert [
        r for r in await _entries(session, a.guild.id, "task") if r.entity_id == task.id
    ] == []


async def test_a_current_guild_is_left_alone(session, acting_user):
    """The marker is what keeps a boot from rewriting every guild's index."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)
    await create_task(session, a.project, title="already indexed")
    await _wipe(a.guild.id)

    first = await reindex_guild_search(
        db_session.provisioning_engine, f"guild_{a.guild.id}"
    )
    assert first > 0
    second = await reindex_guild_search(
        db_session.provisioning_engine, f"guild_{a.guild.id}"
    )
    assert second == 0, "a guild already at the current generation was swept again"


async def test_the_marker_records_the_generation(session, acting_user):
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await create_project(session, a.initiative, a.user, name="p")
    await _wipe(a.guild.id)
    await reindex_guild_search(db_session.provisioning_engine, f"guild_{a.guild.id}")

    await set_rls_context(session, guild_id=a.guild.id, guild_role="admin")
    marker = (
        await session.exec(
            text("SELECT obj_description(to_regclass(:t), 'pg_class')").bindparams(
                t=f"guild_{a.guild.id}.search_entries"
            )
        )
    ).one()[0]
    assert marker == search_generation()
