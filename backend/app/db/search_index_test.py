"""The refresh trigger indexes what the registry declares.

These assert the seam between ``SEARCH_SOURCES`` and a real Postgres: that an
ordinary write lands in ``search_entries`` at all, that the row carries the
initiative and sharing identity the query layer will filter on, and that the
three shapes the design turns on — trash leaving the index, an unrelated update
costing nothing, and long text chunking — hold against the database rather than
against the rendering code.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from sqlmodel import SQLModel

from app.db.search_index import (
    NOT_SEARCHABLE,
    SEARCH_SOURCES,
    addressable_tables,
    entity_types,
    render_guild_search_ddl,
)
from app.db.session import set_rls_context
from app.db.tenancy import INITIATIVE_SCOPED_TABLES
from app.models.platform.guild import GuildRole
from app.models.tenant.search_entry import SearchEntry
from app.testing import create_project, create_tag, create_task

pytestmark = pytest.mark.integration


async def _entries(
    session: AsyncSession,
    guild_id: int,
    entity_type: str,
    entity_id: int,
    *,
    user_id: int | None = None,
    guild_role: str = "admin",
) -> list[SearchEntry]:
    await set_rls_context(
        session, user_id=user_id, guild_id=guild_id, guild_role=guild_role
    )
    rows = await session.exec(
        select(SearchEntry)
        .where(
            SearchEntry.entity_type == entity_type,
            SearchEntry.entity_id == entity_id,
        )
        .order_by(SearchEntry.chunk_ix.asc())
    )
    return list(rows)


# --- registry -------------------------------------------------------------


@pytest.mark.unit
def test_every_initiative_scoped_table_is_placed():
    """A new content table is searchable or says why not — never silently
    absent, which would ship a tool no one can find."""
    placed = set(SEARCH_SOURCES) | set(NOT_SEARCHABLE)
    # Junctions carry no id to address and no text of their own, so they are
    # out by construction rather than by 22 entries saying the same thing.
    addressable = addressable_tables(SQLModel.metadata)
    missing = (set(INITIATIVE_SCOPED_TABLES) & addressable) - placed
    assert not missing, (
        f"add to SEARCH_SOURCES or NOT_SEARCHABLE in app/db/search_index.py: "
        f"{sorted(missing)}"
    )


@pytest.mark.unit
def test_a_table_is_not_placed_twice():
    assert not (set(SEARCH_SOURCES) & set(NOT_SEARCHABLE))


@pytest.mark.unit
def test_entity_types_are_unique():
    values = [s.entity_type for s in SEARCH_SOURCES.values()]
    assert len(values) == len(set(values))


@pytest.mark.unit
def test_update_trigger_carries_a_when_clause():
    """The clause is the write-path design: an update touching none of the
    indexed columns never enters the function."""
    ddl = render_guild_search_ddl()
    block = next(b for b in ddl.split("\n\n") if "search_task_upd" in b)
    assert "FOR EACH ROW WHEN (" in block
    assert "OLD.title IS DISTINCT FROM NEW.title" in block
    # ...and the insert trigger cannot carry one (OLD is not bound on INSERT).
    ins = next(b for b in ddl.split("\n\n") if "search_task_ins" in b)
    assert "WHEN (" not in ins


@pytest.mark.unit
def test_default_scope_is_the_indexed_set_for_now():
    assert entity_types(default_scope_only=True) == entity_types()


# --- the trigger ----------------------------------------------------------


async def test_creating_a_task_is_indexed(session, acting_user):
    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)
    task = await create_task(session, a.project, title="vendor renewal terms")

    rows = await _entries(session, a.guild.id, "task", task.id)
    assert rows, "creating a task produced no search entry"
    row = rows[0]
    assert row.title == "vendor renewal terms"
    assert row.initiative_id == a.initiative.id
    # A task is governed by its project's sharing, not its own id.
    assert row.dac_tool == "project"
    assert row.dac_id == a.project.id


async def test_the_entry_is_full_text_searchable(session, acting_user):
    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)
    await create_task(session, a.project, title="quarterly vendor renewal")

    await set_rls_context(session, guild_id=a.guild.id, guild_role="admin")
    found = await session.exec(
        text(
            "SELECT title FROM search_entries "
            "WHERE tsv @@ websearch_to_tsquery('simple', :q)"
        ).bindparams(q="vendor renewal")
    )
    assert [r[0] for r in found] == ["quarterly vendor renewal"]


async def test_renaming_reindexes_in_place(session, acting_user):
    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)
    task = await create_task(session, a.project, title="before")

    task.title = "after"
    session.add(task)
    await session.commit()

    rows = await _entries(session, a.guild.id, "task", task.id)
    assert [r.title for r in rows] == ["after"]


async def test_soft_delete_removes_it_from_the_index(session, acting_user):
    """Trash is browsed through the trash surface, not found by searching."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)
    task = await create_task(session, a.project, title="gone")
    assert await _entries(session, a.guild.id, "task", task.id)

    from datetime import datetime, timezone

    task.deleted_at = datetime.now(timezone.utc)
    session.add(task)
    await session.commit()

    assert await _entries(session, a.guild.id, "task", task.id) == []


async def test_a_guild_level_tag_is_indexed_without_an_initiative(session, acting_user):
    a = await acting_user(guild_role=GuildRole.admin)
    tag = await create_tag(session, a.guild, name="urgent")

    rows = await _entries(session, a.guild.id, "tag", tag.id)
    assert rows, "creating a tag produced no search entry"
    # Guild-level vocabulary: no initiative to gate on, and no sharing gate.
    assert rows[0].initiative_id is None
    assert rows[0].dac_tool is None


async def test_long_text_is_chunked(session, acting_user):
    """Chunking is a length rule: the cap cannot be reached because a row's
    text is bounded by construction."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    body = " ".join(f"word{n}" for n in range(6000))
    project = await create_project(
        session, a.initiative, a.user, name="big", description=body
    )

    rows = await _entries(session, a.guild.id, "project", project.id)
    assert len(rows) > 1, "a long description produced a single chunk"
    assert [r.chunk_ix for r in rows] == list(range(len(rows)))
    # Every chunk carries the title, so a title match ranks the entity whichever
    # chunk it lands in.
    assert {r.title for r in rows} == {"big"}


async def test_short_text_is_exactly_one_chunk(session, acting_user):
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    project = await create_project(
        session, a.initiative, a.user, name="small", description="one line"
    )
    rows = await _entries(session, a.guild.id, "project", project.id)
    assert len(rows) == 1
    assert rows[0].chunk_ix == 0


async def test_a_guild_member_outside_the_initiative_sees_nothing(session, acting_user):
    """The initiative gate this table registers, proven against the database.

    A guild member who is not in the initiative gets no rows — the same answer
    the content tables give, from the same ``initiative_access`` call.
    """
    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)
    # Both actors up front: reading routes the session into a guild role, which
    # the factories cannot run under.
    outsider = await acting_user(guild_role=GuildRole.member, guild=a.guild)
    task = await create_task(session, a.project, title="quarterly vendor renewal")

    assert await _entries(session, a.guild.id, "task", task.id)
    assert (
        await _entries(
            session,
            a.guild.id,
            "task",
            task.id,
            user_id=outsider.user.id,
            guild_role="member",
        )
        == []
    )


async def test_a_guild_level_tag_is_visible_to_any_member(session, acting_user):
    """The NULL-initiative leg: guild vocabulary every member already sees in
    every picker is not hidden from them in search."""
    a = await acting_user(guild_role=GuildRole.admin)
    member = await acting_user(guild_role=GuildRole.member, guild=a.guild)
    tag = await create_tag(session, a.guild, name="urgent")

    rows = await _entries(
        session,
        a.guild.id,
        "tag",
        tag.id,
        user_id=member.user.id,
        guild_role="member",
    )
    assert [r.title for r in rows] == ["urgent"]
