"""Reading live badge state through the API.

A badge stores nothing, so what these assert is that the chip reflects the row
it points at right now — including after the row changes — and that it answers
under the same gates as the thing it is about.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.core.document_badges import BADGE_KINDS, BadgeKind, kind_value
from app.models.platform.guild import GuildRole
from sqlmodel import select

from app.models.tenant.task import TaskPriority, TaskStatus, TaskStatusCategory
from app.services.tenant.document_badges import _ACCESS, _ID_COLUMNS, BADGE_SOURCES
from app.testing import (
    Actor,
    create_calendar,
    create_calendar_event,
    create_counter,
    create_counter_group,
    create_task,
    create_task_status,
    create_user,
)

pytestmark = pytest.mark.integration

ActingUser = Callable[..., Awaitable[Actor]]


async def _status_of(session, task) -> TaskStatus:
    """The column a task currently sits in."""
    return (
        await session.exec(
            select(TaskStatus).where(TaskStatus.id == task.task_status_id)
        )
    ).one()


async def _move_to(session, task, project, category: TaskStatusCategory) -> None:
    """Move a card, the way a person would — the document is not touched."""
    status = await create_task_status(
        session, project, name=category.value.title(), category=category
    )
    task.task_status_id = status.id
    session.add(task)
    await session.commit()


async def _badges(client, actor: Actor, *refs: str) -> dict[str, dict]:
    response = await client.get(
        actor.g("/document-badges/"), headers=actor.headers, params={"ref": list(refs)}
    )
    assert response.status_code == 200, response.text
    return {item["ref"]: item for item in response.json()["items"]}


async def test_a_task_badge_shows_the_column_it_sits_in(
    client, session, acting_user: ActingUser
) -> None:
    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)
    task = await create_task(
        session,
        a.project,
        title="Ship it",
        status_category=TaskStatusCategory.in_progress,
    )

    body = await _badges(client, a, f"task:{task.id}:status")
    assert body[f"task:{task.id}:status"]["text"]
    assert body[f"task:{task.id}:status"]["tone"] == "warn"


async def test_moving_the_card_moves_the_badge(
    client, session, acting_user: ActingUser
) -> None:
    """The document is not edited and the chip still changes — which is the
    whole point of a badge over a mention."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)
    task = await create_task(session, a.project, title="Ship it")
    ref = f"task:{task.id}:status"
    before = (await _badges(client, a, ref))[ref]
    assert before["tone"] != "good"

    await _move_to(session, task, a.project, TaskStatusCategory.done)

    after = (await _badges(client, a, ref))[ref]
    assert after["tone"] == "good"
    assert after["text"] != before["text"]


async def test_a_status_sends_its_own_colour(
    client, session, acting_user: ActingUser
) -> None:
    """A project picks its own colours, so the chip wears them rather than a
    tone this end invented."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)
    task = await create_task(session, a.project, title="Waiting")
    status = await _status_of(session, task)
    status.color = "#FF00AA"
    session.add(status)
    await session.commit()

    body = await _badges(client, a, f"task:{task.id}:status")
    assert body[f"task:{task.id}:status"]["color"] == "#FF00AA"


async def test_a_date_is_late_only_while_the_work_is_not_done(
    client, session, acting_user: ActingUser
) -> None:
    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)
    yesterday = datetime.now(timezone.utc) - timedelta(days=1)
    task = await create_task(session, a.project, title="Overdue", due_date=yesterday)

    ref = f"task:{task.id}:due"
    assert (await _badges(client, a, ref))[ref]["tone"] == "danger"

    await _move_to(session, task, a.project, TaskStatusCategory.done)

    # Delivered late is delivered, not overdue.
    assert (await _badges(client, a, ref))[ref]["tone"] == "neutral"


async def test_the_date_itself_comes_back_for_the_reader_to_format(
    client, session, acting_user: ActingUser
) -> None:
    """A date belongs in the reader's locale, which only their browser knows."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)
    due = datetime.now(timezone.utc) + timedelta(days=3)
    task = await create_task(session, a.project, title="Soon", due_date=due)

    body = await _badges(client, a, f"task:{task.id}:due")
    assert body[f"task:{task.id}:due"]["date"] is not None


async def test_an_unassigned_task_says_so_rather_than_going_missing(
    client, session, acting_user: ActingUser
) -> None:
    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)
    task = await create_task(session, a.project, title="Nobody's")

    body = await _badges(client, a, f"task:{task.id}:assignee")
    assert body[f"task:{task.id}:assignee"]["tone"] == "muted"


async def test_several_holders_are_named_by_the_first_and_counted(
    client, session, acting_user: ActingUser
) -> None:
    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)
    second = await create_user(session)
    task = await create_task(
        session, a.project, title="Shared", assignees=[a.user, second]
    )

    body = await _badges(client, a, f"task:{task.id}:assignee")
    assert body[f"task:{task.id}:assignee"]["text"].endswith("+1")


async def test_a_priority_carries_its_own_urgency(
    client, session, acting_user: ActingUser
) -> None:
    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)
    task = await create_task(
        session, a.project, title="Now", priority=TaskPriority.urgent
    )

    body = await _badges(client, a, f"task:{task.id}:priority")
    assert body[f"task:{task.id}:priority"]["tone"] == "danger"


async def test_a_counter_reads_its_number_and_its_ceiling(
    client, session, acting_user: ActingUser
) -> None:
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    group = await create_counter_group(session, a.initiative, a.user)
    counter = await create_counter(session, group)
    counter.count = Decimal("7")
    counter.max = Decimal("10")
    session.add(counter)
    await session.commit()

    body = await _badges(client, a, f"counter:{counter.id}:value")
    state = body[f"counter:{counter.id}:value"]
    # Trailing zeros are storage, not something to read.
    assert state["text"] == "7 / 10"
    assert state["tone"] == "neutral"


async def test_a_counter_at_its_ceiling_reads_as_arrived(
    client, session, acting_user: ActingUser
) -> None:
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    group = await create_counter_group(session, a.initiative, a.user)
    counter = await create_counter(session, group)
    counter.count = Decimal("10")
    counter.max = Decimal("10")
    session.add(counter)
    await session.commit()

    body = await _badges(client, a, f"counter:{counter.id}:value")
    assert body[f"counter:{counter.id}:value"]["tone"] == "good"


async def test_an_event_dims_once_it_has_happened(
    client, session, acting_user: ActingUser
) -> None:
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    calendar = await create_calendar(session, a.initiative, a.user)
    past = await create_calendar_event(
        session,
        calendar,
        a.user,
        start_at=datetime.now(timezone.utc) - timedelta(days=2),
    )
    soon = await create_calendar_event(
        session,
        calendar,
        a.user,
        start_at=datetime.now(timezone.utc) + timedelta(days=2),
    )

    body = await _badges(
        client,
        a,
        f"calendar_event:{past.id}:when",
        f"calendar_event:{soon.id}:when",
    )
    assert body[f"calendar_event:{past.id}:when"]["tone"] == "muted"
    assert body[f"calendar_event:{soon.id}:when"]["tone"] == "neutral"


async def test_a_page_of_chips_is_read_together(
    client, session, acting_user: ActingUser
) -> None:
    """Two aspects of one task, and a second thing entirely, in one request."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)
    task = await create_task(session, a.project, title="Ship it")
    group = await create_counter_group(session, a.initiative, a.user)
    counter = await create_counter(session, group)

    body = await _badges(
        client,
        a,
        f"task:{task.id}:status",
        f"task:{task.id}:priority",
        f"counter:{counter.id}:value",
    )
    assert len(body) == 3


async def test_a_reference_naming_nothing_is_simply_absent(
    client, session, acting_user: ActingUser
) -> None:
    """A build that stopped offering a badge leaves references behind in
    documents; they read as nothing rather than as an error."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)
    task = await create_task(session, a.project, title="Ship it")

    body = await _badges(
        client,
        a,
        f"task:{task.id}:status",
        "task:999999:status",
        "document:1:status",
        "not-a-ref",
        "task:abc:status",
    )
    assert list(body) == [f"task:{task.id}:status"]


async def test_a_chip_reads_nothing_the_caller_could_not_open(
    client, session, acting_user: ActingUser
) -> None:
    """The reference is in a document, which anyone in the initiative may read.
    What it points at is gated separately, and this is that gate."""
    owner = await acting_user(
        guild_role=GuildRole.member, initiative=True, project=True
    )
    task = await create_task(session, owner.project, title="Private work")

    outsider = await acting_user(guild_role=GuildRole.member, guild=owner.guild)
    body = await _badges(client, outsider, f"task:{task.id}:status")
    assert body == {}


def test_every_declared_badge_has_a_reader():
    """The vocabulary and the readers are two lists in two layers; this is what
    keeps them the same list."""
    assert set(BADGE_SOURCES) == set(BADGE_KINDS)


def test_the_pairs_the_api_declares_are_the_pairs_that_exist():
    """The editor builds its insert menu from this enum, so it must not be able
    to offer a badge nothing reads."""
    assert {kind.value for kind in BadgeKind} == {
        kind_value(entity_type, aspect) for entity_type, aspect in BADGE_KINDS
    }


async def test_a_chip_stops_at_the_sharing_gate_not_just_the_initiative(
    client, session, acting_user: ActingUser
) -> None:
    """Being in the initiative is not being given the project.

    A badge is live state, so it answers under every gate the thing itself
    answers under — the same reading the search index takes.
    """
    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)
    b = await acting_user(
        guild_role=GuildRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )
    task = await create_task(session, a.project, title="restricted renewal")

    assert (await _badges(client, a, f"task:{task.id}:status")) != {}
    assert await _badges(client, b, f"task:{task.id}:status") == {}


def test_every_badgeable_thing_declares_how_it_is_gated():
    """A badge reads live state, so every kind must say which resource governs
    it. A kind with no entry here would be answered ungated."""
    assert set(_ACCESS) == {entity_type for entity_type, _aspect in BADGE_KINDS}
    assert set(_ACCESS) == set(_ID_COLUMNS)


@pytest.mark.parametrize("aspect", ["status", "assignee", "due", "priority"])
async def test_no_task_badge_answers_without_the_project(
    client, session, acting_user: ActingUser, aspect: str
) -> None:
    """Walked per aspect: the gate is applied once for the thing, so adding a
    fifth fact about a task cannot open a hole."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)
    b = await acting_user(
        guild_role=GuildRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )
    task = await create_task(session, a.project, title="restricted")

    assert await _badges(client, b, f"task:{task.id}:{aspect}") == {}


async def test_a_chip_follows_the_thing_own_sharing_either_way(
    client, session, acting_user: ActingUser
) -> None:
    """The gate is the resource's own sharing, not a rule badges invented.

    Both of these are made by a factory, which shares a calendar with the
    initiative and leaves a counter group to its owner. Whichever way the
    sharing goes, the chip follows it — which is the thing being asserted. (The
    create endpoints both default to Viewer for the initiative; the factories
    are not trying to mirror them.)
    """
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    group = await create_counter_group(session, a.initiative, a.user)
    counter = await create_counter(session, group)
    calendar = await create_calendar(session, a.initiative, a.user)
    event = await create_calendar_event(session, calendar, a.user)

    b = await acting_user(
        guild_role=GuildRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )
    body = await _badges(
        client,
        b,
        f"counter:{counter.id}:value",
        f"calendar_event:{event.id}:when",
    )
    assert f"counter:{counter.id}:value" not in body
    assert f"calendar_event:{event.id}:when" in body
