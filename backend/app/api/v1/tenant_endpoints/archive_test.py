"""One pair of endpoints, every archivable kind.

The kinds are derived from the mixin, so what is worth testing is not each of
the ten in turn but the things that differ: a tool that could not be archived
before this existed, the two non-tools, and what a repeat of the same call does.
"""

from datetime import datetime

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.guild import GuildRole
from app.testing import create_document, create_queue, create_task

pytestmark = pytest.mark.integration


async def test_a_tool_that_could_not_be_archived_before_can_be_now(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(guild_role=GuildRole.member, initiative=True)
    queue = await create_queue(session, a.initiative, a.user)

    response = await client.post(a.g(f"/archive/queue/{queue.id}"), headers=a.headers)

    assert response.status_code == 200
    assert response.json()["archived_at"] is not None


async def test_archiving_twice_answers_with_the_stamp_it_has(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The second call is a repeat, not a conflict — an archived row is
    read-only, and this is the write that made it so."""
    a = await acting_user(guild_role=GuildRole.member, initiative=True)
    document = await create_document(session, a.initiative, a.user)

    first = await client.post(
        a.g(f"/archive/document/{document.id}"), headers=a.headers
    )
    assert first.status_code == 200

    again = await client.post(
        a.g(f"/archive/document/{document.id}"), headers=a.headers
    )
    assert again.status_code == 200
    assert again.json()["archived_at"] == first.json()["archived_at"]


async def test_unarchiving_something_live_is_a_repeat_too(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(guild_role=GuildRole.member, initiative=True)
    document = await create_document(session, a.initiative, a.user)

    response = await client.post(
        a.g(f"/unarchive/document/{document.id}"), headers=a.headers
    )

    assert response.status_code == 200
    assert response.json()["archived_at"] is None


async def test_an_archived_tool_goes_back(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(guild_role=GuildRole.member, initiative=True)
    queue = await create_queue(session, a.initiative, a.user)

    await client.post(a.g(f"/archive/queue/{queue.id}"), headers=a.headers)
    back = await client.post(a.g(f"/unarchive/queue/{queue.id}"), headers=a.headers)

    assert back.status_code == 200
    assert back.json()["archived_at"] is None


async def test_archiving_an_initiative_archives_what_is_inside_it(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Finished is finished all the way down, and with one stamp, so a list
    filtering live work reads one column and gets the same answer everywhere."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)
    queue = await create_queue(session, a.initiative, a.user)
    task = await create_task(session, a.project)

    response = await client.post(
        a.g(f"/archive/initiative/{a.initiative.id}"), headers=a.headers
    )
    assert response.status_code == 200
    stamp = response.json()["archived_at"]

    await session.refresh(a.project)
    await session.refresh(queue)
    await session.refresh(task)
    assert a.project.archived_at is not None
    assert queue.archived_at is not None
    assert task.archived_at is not None
    # One stamp, shared — including the one the endpoint answered with.
    assert a.project.archived_at == queue.archived_at == task.archived_at
    assert a.project.archived_at == datetime.fromisoformat(stamp.replace("Z", "+00:00"))


async def test_unarchiving_leaves_what_was_archived_on_its_own(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The shared stamp is what tells the two apart: a queue put away earlier
    carries a different one and keeps it."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)
    queue = await create_queue(session, a.initiative, a.user)

    await client.post(a.g(f"/archive/queue/{queue.id}"), headers=a.headers)
    await client.post(a.g(f"/archive/initiative/{a.initiative.id}"), headers=a.headers)
    await client.post(
        a.g(f"/unarchive/initiative/{a.initiative.id}"), headers=a.headers
    )

    await session.refresh(a.initiative)
    await session.refresh(a.project)
    await session.refresh(queue)
    assert a.initiative.archived_at is None
    assert a.project.archived_at is None
    assert queue.archived_at is not None
