"""The write path fills in who wrote a row and who last changed it.

``AuthorshipMixin`` puts ``created_by_id``/``updated_by_id`` on every guild
content table; the ``before_flush`` hook in ``app.db.session`` is what keeps
them true, since the alternative is stamping them at every call site.
"""

import pytest
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.session import set_rls_context
from app.models.tenant.task import Subtask
from app.testing.factories import (
    create_guild,
    create_guild_membership,
    create_initiative,
    create_project,
    create_task,
    create_user,
)

pytestmark = [pytest.mark.integration, pytest.mark.service]


async def _workspace(session: AsyncSession):
    """A guild with a task in it, plus a second member to act as."""
    creator = await create_user(session)
    guild = await create_guild(session, creator=creator)
    initiative = await create_initiative(session, guild=guild, creator=creator)
    project = await create_project(session, initiative=initiative, owner=creator)
    task = await create_task(session, project=project)
    actor = await create_user(session)
    await create_guild_membership(session, user=actor, guild=guild)
    return guild, task, actor


async def _route(session: AsyncSession, guild_id: int, user_id: int | None) -> None:
    session.expunge_all()
    await set_rls_context(
        session, user_id=user_id, guild_id=guild_id, guild_role="admin"
    )


async def test_insert_records_the_acting_user(session: AsyncSession):
    guild, task, actor = await _workspace(session)

    await _route(session, guild.id, actor.id)
    subtask = Subtask(task_id=task.id, guild_id=guild.id, content="check the wiring")
    session.add(subtask)
    await session.flush()

    assert subtask.created_by_id == actor.id
    assert subtask.updated_by_id == actor.id


async def test_an_explicit_author_is_kept(session: AsyncSession):
    """A caller restoring original authorship (backup import) keeps it."""
    guild, task, actor = await _workspace(session)
    original = await create_user(session)

    await _route(session, guild.id, actor.id)
    subtask = Subtask(
        task_id=task.id,
        guild_id=guild.id,
        content="imported",
        created_by_id=original.id,
    )
    session.add(subtask)
    await session.flush()

    assert subtask.created_by_id == original.id


async def test_update_moves_updated_by_and_leaves_the_author(session: AsyncSession):
    guild, task, author = await _workspace(session)
    editor = await create_user(session)
    await create_guild_membership(session, user=editor, guild=guild)

    await _route(session, guild.id, author.id)
    subtask = Subtask(task_id=task.id, guild_id=guild.id, content="first draft")
    session.add(subtask)
    await session.flush()
    subtask_id = subtask.id

    await _route(session, guild.id, editor.id)
    row = (await session.exec(select(Subtask).where(Subtask.id == subtask_id))).one()
    row.content = "second draft"
    await session.flush()

    assert row.created_by_id == author.id
    assert row.updated_by_id == editor.id


async def test_a_system_session_stamps_nothing(session: AsyncSession):
    """Background work and seeding have no one to name, so they name no one."""
    guild, task, _ = await _workspace(session)

    await _route(session, guild.id, None)
    subtask = Subtask(task_id=task.id, guild_id=guild.id, content="swept up by a job")
    session.add(subtask)
    await session.flush()

    assert subtask.created_by_id is None
    assert subtask.updated_by_id is None
