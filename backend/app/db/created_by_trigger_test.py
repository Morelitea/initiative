"""The database fills in who made a row.

``public.fn_set_created_by`` is a BEFORE INSERT trigger on every guild-content
table, reading ``app.current_user_id`` — the GUC the request already sets for
RLS. Doing it here rather than in the ORM is what makes it unconditional: the
same shape as the ``fn_*_set_guild_id`` triggers beside it, and it covers writes
that never pass through a flush.
"""

from datetime import datetime, timezone

import pytest
from sqlalchemy import insert
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.session import set_rls_context
from app.models.tenant.queue import QueueItem
from app.testing.factories import (
    create_guild,
    create_guild_membership,
    create_initiative,
    create_queue,
    create_user,
)

pytestmark = [pytest.mark.integration, pytest.mark.service]


async def _workspace(session: AsyncSession):
    """A guild with a queue in it, plus a second member to act as."""
    creator = await create_user(session)
    guild = await create_guild(session, creator=creator)
    initiative = await create_initiative(session, guild=guild, creator=creator)
    queue = await create_queue(session, initiative=initiative, creator=creator)
    actor = await create_user(session)
    await create_guild_membership(session, user=actor, guild=guild)
    return guild, queue, actor


async def _route(session: AsyncSession, guild_id: int, user_id: int | None) -> None:
    session.expunge_all()
    await set_rls_context(
        session, user_id=user_id, guild_id=guild_id, guild_role="admin"
    )


async def _reload(session: AsyncSession, item_id: int) -> QueueItem:
    """Read the row back. The trigger writes to the row, not to the identity
    map, so a freshly flushed object still holds None until it is refreshed."""
    session.expunge_all()
    return (await session.exec(select(QueueItem).where(QueueItem.id == item_id))).one()


async def test_insert_records_the_acting_user(session: AsyncSession):
    guild, queue, actor = await _workspace(session)

    await _route(session, guild.id, actor.id)
    item = QueueItem(queue_id=queue.id, guild_id=guild.id, label="check the wiring")
    session.add(item)
    await session.flush()

    assert (await _reload(session, item.id)).created_by == actor.id


async def test_a_write_that_skips_the_orm_is_stamped_too(session: AsyncSession):
    """The reason this is a trigger and not a flush hook.

    A bulk ``insert()`` never reaches the ORM's unit of work, so an app-layer
    hook could not see it. The database does not care how the row arrived.
    """
    guild, queue, actor = await _workspace(session)

    await _route(session, guild.id, actor.id)
    # A Core insert also skips the Python-side column defaults, so the
    # timestamp is supplied here; ``created_by`` is the database's job.
    await session.exec(
        insert(QueueItem).values(
            queue_id=queue.id,
            guild_id=guild.id,
            label="written by statement",
            created_at=datetime.now(timezone.utc),
        )
    )

    row = (
        await session.exec(
            select(QueueItem).where(QueueItem.label == "written by statement")
        )
    ).one()
    assert row.created_by == actor.id


async def test_an_explicit_author_is_kept(session: AsyncSession):
    """A caller restoring original authorship (backup import) keeps it."""
    guild, queue, actor = await _workspace(session)
    original = await create_user(session)

    await _route(session, guild.id, actor.id)
    item = QueueItem(
        queue_id=queue.id,
        guild_id=guild.id,
        label="imported",
        created_by=original.id,
    )
    session.add(item)
    await session.flush()

    assert (await _reload(session, item.id)).created_by == original.id


async def test_an_edit_by_someone_else_leaves_the_author(session: AsyncSession):
    """Authorship is a historical fact: the trigger is INSERT-only."""
    guild, queue, author = await _workspace(session)
    editor = await create_user(session)
    await create_guild_membership(session, user=editor, guild=guild)

    await _route(session, guild.id, author.id)
    item = QueueItem(queue_id=queue.id, guild_id=guild.id, label="first draft")
    session.add(item)
    await session.flush()
    item_id = item.id

    await _route(session, guild.id, editor.id)
    row = await _reload(session, item_id)
    row.label = "second draft"
    await session.flush()

    assert (await _reload(session, item_id)).created_by == author.id


async def test_a_system_session_stamps_nothing(session: AsyncSession):
    """Background work and seeding have no one to name, so they name no one."""
    guild, queue, _ = await _workspace(session)

    await _route(session, guild.id, None)
    item = QueueItem(queue_id=queue.id, guild_id=guild.id, label="swept up by a job")
    session.add(item)
    await session.flush()

    assert (await _reload(session, item.id)).created_by is None
