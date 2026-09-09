"""The change log reaching the rooms watching it.

The sink is the only thing that puts a frame on the ``/events/updates`` bus, so
these pin what it will and will not send: the tenancy boundary it inherits from
the room key, the envelope staying identifiers-only, and the two ways it reads
the log covering for each other.
"""

from __future__ import annotations

import pytest

from app.models.platform.guild import GuildRole
from app.models.tenant.event_outbox import EventOutbox
from app.services.realtime import manager
from app.services.realtime_test import FakeWebSocket
from app.services.tenant import room_sink
from app.testing import create_comment, create_document, create_tag, create_task

pytestmark = pytest.mark.integration


class _Watcher:
    """A socket in one room, brought up to the log on entry."""

    def __init__(self, guild_id: int, *initiative_ids: int) -> None:
        self._guild_id = guild_id
        self._initiative_ids = initiative_ids
        self.socket = FakeWebSocket()

    async def __aenter__(self) -> "_Watcher":
        await manager.connect(
            self._guild_id, list(self._initiative_ids), self.socket, user_id=1
        )
        await room_sink.process_room_sweep()
        return self

    async def __aexit__(self, *exc) -> None:
        await manager.disconnect(self.socket)
        room_sink._delivered.pop(self._guild_id, None)

    async def catch_up(self) -> None:
        await room_sink.process_room_sweep()

    @property
    def changes(self) -> list[dict]:
        return [c for frame in self.socket.sent for c in frame.get("changes", [])]

    def named(self, resource_type: str) -> list[dict]:
        return [c for c in self.changes if c["resource"]["type"] == resource_type]


async def test_a_write_reaches_the_room_it_belongs_to(session, acting_user):
    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)

    async with _Watcher(a.guild.id, a.initiative.id) as watcher:
        task = await create_task(session, a.project)
        await watcher.catch_up()

        tasks = watcher.named("tasks")
        assert tasks, f"the room heard nothing; got {watcher.changes}"
        assert tasks[-1]["resource"] == {"type": "tasks", "id": task.id}
        assert tasks[-1]["parents"] == [{"type": "projects", "id": a.project.id}]


async def test_the_frame_carries_identifiers_and_nothing_else(session, acting_user):
    """Identifiers and an action, and nothing a reader would not fetch anyway."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)

    async with _Watcher(a.guild.id, a.initiative.id) as watcher:
        task = await create_task(session, a.project, title="Move the session")
        await create_comment(session, a.user, task=task, content="secret text")
        await watcher.catch_up()

        assert watcher.changes, "the room heard nothing"
        for change in watcher.changes:
            assert set(change) == {"resource", "parents", "action"}
            assert set(change["resource"]) == {"type", "id"}
            assert all(set(p) == {"type", "id"} for p in change["parents"])


async def test_a_comment_names_its_thread_and_the_project(session, acting_user):
    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)

    async with _Watcher(a.guild.id, a.initiative.id) as watcher:
        task = await create_task(session, a.project)
        comment = await create_comment(session, a.user, task=task)
        await watcher.catch_up()

        comments = watcher.named("comments")
        assert comments, f"no comment change; got {watcher.changes}"
        assert comments[-1]["resource"]["id"] == comment.id
        assert comments[-1]["parents"] == [
            {"type": "tasks", "id": task.id},
            {"type": "projects", "id": a.project.id},
        ]


async def test_another_initiatives_room_hears_nothing(session, acting_user):
    """The room key is (guild, initiative), and the sink routes by it."""
    from app.testing import create_initiative

    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)
    elsewhere = await create_initiative(session, a.guild, a.user)

    async with _Watcher(a.guild.id, elsewhere.id) as watcher:
        await create_task(session, a.project)
        await watcher.catch_up()

        assert watcher.named("tasks") == []


async def test_a_guild_wide_change_reaches_a_member_of_no_initiative(
    session, acting_user
):
    """A tag belongs to no initiative and every member can already read it, so
    it goes to the guild's sockets rather than to a room."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)

    async with _Watcher(a.guild.id) as watcher:
        tag = await create_tag(session, a.guild)
        await watcher.catch_up()

        tags = watcher.named("tags")
        assert tags, f"the guild heard nothing; got {watcher.changes}"
        assert tags[-1]["resource"] == {"type": "tags", "id": tag.id}


async def test_a_first_connect_is_told_nothing(session, acting_user):
    """Whoever just arrived fetched as they mounted; the log before that is not
    theirs to hear."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)
    await create_task(session, a.project)
    await create_document(session, a.initiative, a.user)

    async with _Watcher(a.guild.id, a.initiative.id) as watcher:
        assert watcher.changes == []


async def test_nothing_is_read_for_a_guild_nobody_is_watching(session, acting_user):
    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)
    await create_task(session, a.project)

    room_sink._delivered.pop(a.guild.id, None)
    await room_sink.process_room_sweep()

    assert a.guild.id not in room_sink._delivered


async def test_leaving_drops_the_mark(session, acting_user):
    """So the next socket to arrive is brought up to the log's end rather than
    told everything that happened while nobody was looking."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)

    async with _Watcher(a.guild.id, a.initiative.id):
        assert a.guild.id in room_sink._delivered

    await room_sink.process_room_sweep()
    assert a.guild.id not in room_sink._delivered


async def test_the_same_change_is_not_sent_twice_by_the_sweep(session, acting_user):
    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)

    async with _Watcher(a.guild.id, a.initiative.id) as watcher:
        await create_task(session, a.project)
        await watcher.catch_up()
        first = len(watcher.named("tasks"))
        assert first

        await watcher.catch_up()
        assert len(watcher.named("tasks")) == first


async def test_a_hint_names_the_transaction_it_is_raised_for(session, acting_user):
    """The prompt path: no watermark, just the rows that transaction wrote."""
    from app.db.session import set_rls_context
    from sqlmodel import select

    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)

    async with _Watcher(a.guild.id, a.initiative.id) as watcher:
        task = await create_task(session, a.project)
        await set_rls_context(session, guild_id=a.guild.id, guild_role="admin")
        row = (
            await session.exec(
                select(EventOutbox)
                .where(EventOutbox.resource_id == task.id)
                .where(EventOutbox.resource_type == "tasks")
            )
        ).first()
        assert row is not None

        await room_sink.deliver(f"guild_{a.guild.id}:{row.txn_id}")

        assert [c["resource"]["id"] for c in watcher.named("tasks")] == [task.id]


@pytest.mark.unit
async def test_an_unreadable_hint_is_dropped() -> None:
    """Nothing on the bus is load-bearing enough to raise over."""
    await room_sink.deliver("not-a-schema")
    await room_sink.deliver("guild_x:1")
    await room_sink.deliver("guild_1:not-a-txn")


@pytest.mark.unit
def test_a_transaction_too_large_to_name_says_so_instead() -> None:
    """A bulk write would otherwise send every id it touched to every socket."""
    rows = [
        EventOutbox(
            id=i,
            txn_id=1,
            actor_user_id=None,
            initiative_id=1,
            resource_type="tasks",
            resource_id=i,
            action="created",
            changed=[],
            parents=[],
        )
        for i in range(room_sink.MAX_CHANGES + 1)
    ]
    frame = room_sink._frame(rows)

    assert frame == {"changes": [], "more": True}


@pytest.mark.unit
def test_one_row_written_repeatedly_is_one_change() -> None:
    rows = [
        EventOutbox(
            id=i,
            txn_id=1,
            actor_user_id=None,
            initiative_id=1,
            resource_type="tasks",
            resource_id=4,
            action="updated",
            changed=["title"],
            parents=[{"type": "projects", "id": 7}],
        )
        for i in range(1, 4)
    ]

    frame = room_sink._frame(rows)

    assert frame["changes"] == [
        {
            "resource": {"type": "tasks", "id": 4},
            "parents": [{"type": "projects", "id": 7}],
            "action": "updated",
        }
    ]
