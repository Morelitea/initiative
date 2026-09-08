"""The board's realtime signals — a notice reaches a second window on its own.

Every write that changes what a board shows emits one content-free ``post``
envelope into that initiative's room, so somebody with the board open sees it
without reloading. These tests drive the real endpoints through the real
``manager``, so a broadcast that is missing, mis-scoped or carrying content
fails here.

Publication is the case worth stating twice: a draft says nothing, and the
moment it goes up — posted outright, or stamped later by the scheduler — is the
moment the room hears about it.
"""

from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.guild import GuildRole
from app.models.tenant.post import Post
from app.services.realtime import manager
from app.services.realtime_test import FakeWebSocket
from app.services.tenant.post_publication import publish_due_posts
from app.testing import (
    create_guild,
    create_guild_membership,
    create_initiative,
    create_initiative_member,
    create_post,
    create_user,
    lexical_body,
    route_session_to_guild,
)

pytestmark = pytest.mark.integration


async def _posts_enabled(session: AsyncSession, initiative) -> None:
    initiative.posts_enabled = True
    session.add(initiative)
    await session.commit()
    await session.refresh(initiative)


class _Room:
    """A socket joined to one initiative's room, cleaned up on exit."""

    def __init__(self, guild_id: int, initiative_id: int) -> None:
        self._guild_id = guild_id
        self._initiative_id = initiative_id
        self.socket = FakeWebSocket()

    async def __aenter__(self) -> "_Room":
        await manager.connect(
            self._guild_id, [self._initiative_id], self.socket, user_id=1
        )
        return self

    async def __aexit__(self, *exc) -> None:
        await manager.disconnect(self.socket)

    def posts(self) -> list[dict]:
        return [frame for frame in self.socket.sent if frame["resource"] == "post"]


@pytest.mark.asyncio
async def test_posting_a_notice_tells_the_room(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _posts_enabled(session, a.initiative)

    async with _Room(a.guild.id, a.initiative.id) as room:
        response = await client.post(
            a.g("/posts/"),
            headers=a.headers,
            json={
                "initiative_id": a.initiative.id,
                "name": "Session moved",
                "body": lexical_body("We are on Thursday now."),
            },
        )
        assert response.status_code == 201
        post_id = response.json()["id"]

        frames = room.posts()
        assert len(frames) == 1
        assert frames[0]["action"] == "created"
        assert frames[0]["ids"] == {"post_id": post_id}
        # The bus carries ids, never the notice itself.
        assert "data" not in frames[0]
        assert "body" not in frames[0]["ids"]


@pytest.mark.asyncio
async def test_a_scheduled_draft_says_nothing_until_it_goes_up(
    client: AsyncClient, acting_user, session
):
    """A draft is nobody else's business, so no board is told to refetch."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _posts_enabled(session, a.initiative)
    later = datetime.now(timezone.utc) + timedelta(days=1)

    async with _Room(a.guild.id, a.initiative.id) as room:
        response = await client.post(
            a.g("/posts/"),
            headers=a.headers,
            json={
                "initiative_id": a.initiative.id,
                "name": "Not yet",
                "body": lexical_body("Draft."),
                "scheduled_for": later.isoformat(),
            },
        )
        assert response.status_code == 201
        assert room.posts() == []


@pytest.mark.asyncio
async def test_publishing_a_draft_now_tells_the_room(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _posts_enabled(session, a.initiative)
    later = datetime.now(timezone.utc) + timedelta(days=1)
    created = await client.post(
        a.g("/posts/"),
        headers=a.headers,
        json={
            "initiative_id": a.initiative.id,
            "name": "Held back",
            "body": lexical_body("Draft."),
            "scheduled_for": later.isoformat(),
        },
    )
    post_id = created.json()["id"]

    async with _Room(a.guild.id, a.initiative.id) as room:
        # Clearing the schedule is how "post it now" is expressed.
        response = await client.patch(
            a.g(f"/posts/{post_id}"),
            headers=a.headers,
            json={"scheduled_for": None},
        )
        assert response.status_code == 200

        frames = room.posts()
        assert len(frames) == 1
        assert frames[0]["action"] == "published"
        assert frames[0]["ids"] == {"post_id": post_id}


@pytest.mark.asyncio
async def test_editing_pinning_and_deleting_each_tell_the_room(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _posts_enabled(session, a.initiative)
    post = await create_post(session, a.initiative, a.user)

    async with _Room(a.guild.id, a.initiative.id) as room:
        edited = await client.patch(
            a.g(f"/posts/{post.id}"), headers=a.headers, json={"name": "Renamed"}
        )
        assert edited.status_code == 200

        pinned = await client.put(
            a.g(f"/posts/{post.id}/pin"), headers=a.headers, json={"pinned": True}
        )
        assert pinned.status_code == 200

        removed = await client.delete(a.g(f"/posts/{post.id}"), headers=a.headers)
        assert removed.status_code == 204

    assert [frame["action"] for frame in room.posts()] == [
        "updated",
        "pinned",
        "deleted",
    ]


@pytest.mark.asyncio
async def test_answering_a_poll_tells_the_room_the_tallies_moved(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _posts_enabled(session, a.initiative)
    post = await create_post(session, a.initiative, a.user)
    written = await client.put(
        a.g(f"/posts/{post.id}/poll"),
        headers=a.headers,
        json={"question": "Thursday?", "options": [{"text": "Yes"}, {"text": "No"}]},
    )
    assert written.status_code == 200
    option_id = written.json()["poll"]["options"][0]["id"]

    async with _Room(a.guild.id, a.initiative.id) as room:
        voted = await client.put(
            a.g(f"/posts/{post.id}/poll/vote"),
            headers=a.headers,
            json={"option_ids": [option_id]},
        )
        assert voted.status_code == 200

        retracted = await client.delete(
            a.g(f"/posts/{post.id}/poll/vote"), headers=a.headers
        )
        assert retracted.status_code == 200

    assert [frame["action"] for frame in room.posts()] == ["voted", "voted"]


@pytest.mark.asyncio
async def test_a_notice_never_reaches_another_initiatives_room(
    client: AsyncClient, acting_user, session
):
    """The room key is (guild, initiative): a board next door hears nothing."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _posts_enabled(session, a.initiative)
    elsewhere = await create_initiative(session, a.guild, a.user)

    async with _Room(a.guild.id, elsewhere.id) as room:
        response = await client.post(
            a.g("/posts/"),
            headers=a.headers,
            json={
                "initiative_id": a.initiative.id,
                "name": "Ours only",
                "body": lexical_body("Not yours."),
            },
        )
        assert response.status_code == 201
        assert room.posts() == []


async def test_the_scheduler_tells_the_room_when_a_draft_comes_due(
    session: AsyncSession,
):
    """The other way a notice goes up: no request, same signal."""
    author = await create_user(session)
    guild = await create_guild(session, creator=author)
    reader = await create_user(session)
    await create_guild_membership(session, user=reader, guild=guild)
    initiative = await create_initiative(session, guild, author)
    await create_initiative_member(session, initiative, reader)
    await _posts_enabled(session, initiative)

    post = await create_post(session, initiative, author)
    post.published_at = None
    post.scheduled_for = datetime.now(timezone.utc) - timedelta(minutes=1)
    session.add(post)
    await session.commit()
    post_id, guild_id, initiative_id = post.id, guild.id, initiative.id

    async with _Room(guild_id, initiative_id) as room:
        await route_session_to_guild(session, guild_id)
        assert await publish_due_posts(session, now=datetime.now(timezone.utc)) == [
            post_id
        ]
        await session.commit()

        frames = room.posts()
        assert len(frames) == 1
        assert frames[0]["action"] == "published"
        assert frames[0]["ids"] == {"post_id": post_id}

    published = (await session.exec(select(Post).where(Post.id == post_id))).one()
    assert published.published_at is not None
