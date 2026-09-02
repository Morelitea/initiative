"""Reading live smart chip state through the API.

A chip stores nothing, so what these assert is that the chip reflects the row
it points at right now — including after the row changes — and that it answers
under the same gates as the thing it is about.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.core.smart_chips import SMART_CHIP_KINDS, SmartChipKind, kind_value
from app.models.platform.guild import GuildRole
from sqlmodel import select

from app.models.tenant.task import TaskPriority, TaskStatus, TaskStatusCategory
from app.core.references import NOT_REFERENCEABLE, REFERENCEABLE_TYPES
from app.db.reference_targets import referenceable_types
from app.services.tenant.smart_chips import MAX_REFS, SMART_CHIP_SOURCES
from app.testing import (
    Actor,
    create_calendar,
    create_calendar_event,
    create_counter,
    create_comment,
    create_counter_group,
    create_queue,
    create_queue_item,
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


async def _chips(client, actor: Actor, *refs: str) -> dict[str, dict]:
    response = await client.get(
        actor.g("/smart-chips/"), headers=actor.headers, params={"ref": list(refs)}
    )
    assert response.status_code == 200, response.text
    return {item["ref"]: item for item in response.json()["items"]}


async def test_a_task_chip_shows_the_column_it_sits_in(
    client, session, acting_user: ActingUser
) -> None:
    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)
    task = await create_task(
        session,
        a.project,
        title="Ship it",
        status_category=TaskStatusCategory.in_progress,
    )

    body = await _chips(client, a, f"task:{task.id}:status")
    assert body[f"task:{task.id}:status"]["text"]
    assert body[f"task:{task.id}:status"]["tone"] == "warn"


async def test_moving_the_card_moves_the_chip(
    client, session, acting_user: ActingUser
) -> None:
    """The document is not edited and the chip still changes — which is the
    whole point of a chip over a mention."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)
    task = await create_task(session, a.project, title="Ship it")
    ref = f"task:{task.id}:status"
    before = (await _chips(client, a, ref))[ref]
    assert before["tone"] != "good"

    await _move_to(session, task, a.project, TaskStatusCategory.done)

    after = (await _chips(client, a, ref))[ref]
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

    body = await _chips(client, a, f"task:{task.id}:status")
    assert body[f"task:{task.id}:status"]["color"] == "#FF00AA"


async def test_a_date_is_late_only_while_the_work_is_not_done(
    client, session, acting_user: ActingUser
) -> None:
    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)
    yesterday = datetime.now(timezone.utc) - timedelta(days=1)
    task = await create_task(session, a.project, title="Overdue", due_date=yesterday)

    ref = f"task:{task.id}:due"
    assert (await _chips(client, a, ref))[ref]["tone"] == "danger"

    await _move_to(session, task, a.project, TaskStatusCategory.done)

    # Delivered late is delivered, not overdue.
    assert (await _chips(client, a, ref))[ref]["tone"] == "neutral"


async def test_the_date_itself_comes_back_for_the_reader_to_format(
    client, session, acting_user: ActingUser
) -> None:
    """A date belongs in the reader's locale, which only their browser knows."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)
    due = datetime.now(timezone.utc) + timedelta(days=3)
    task = await create_task(session, a.project, title="Soon", due_date=due)

    body = await _chips(client, a, f"task:{task.id}:due")
    assert body[f"task:{task.id}:due"]["date"] is not None


async def test_an_unassigned_task_says_so_rather_than_going_missing(
    client, session, acting_user: ActingUser
) -> None:
    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)
    task = await create_task(session, a.project, title="Nobody's")

    body = await _chips(client, a, f"task:{task.id}:assignee")
    assert body[f"task:{task.id}:assignee"]["tone"] == "muted"


async def test_several_holders_are_named_by_the_first_and_counted(
    client, session, acting_user: ActingUser
) -> None:
    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)
    second = await create_user(session)
    task = await create_task(
        session, a.project, title="Shared", assignees=[a.user, second]
    )

    body = await _chips(client, a, f"task:{task.id}:assignee")
    assert body[f"task:{task.id}:assignee"]["text"].endswith("+1")


async def test_a_priority_carries_its_own_urgency(
    client, session, acting_user: ActingUser
) -> None:
    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)
    task = await create_task(
        session, a.project, title="Now", priority=TaskPriority.urgent
    )

    body = await _chips(client, a, f"task:{task.id}:priority")
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

    body = await _chips(client, a, f"counter:{counter.id}:value")
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

    body = await _chips(client, a, f"counter:{counter.id}:value")
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

    body = await _chips(
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

    body = await _chips(
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
    """A build that stopped offering a chip leaves references behind in
    documents; they read as nothing rather than as an error."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)
    task = await create_task(session, a.project, title="Ship it")

    body = await _chips(
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
    body = await _chips(client, outsider, f"task:{task.id}:status")
    assert body == {}


def test_every_declared_chip_has_a_reader():
    """The vocabulary and the readers are two lists in two layers; this is what
    keeps them the same list. Titles are not here — one reader answers those
    for every kind."""
    assert set(SMART_CHIP_SOURCES) == set(SMART_CHIP_KINDS)


def test_the_pairs_the_api_declares_are_the_pairs_that_exist():
    """The editor builds its insert menu from this enum, so it must not be able
    to offer a chip nothing reads."""
    assert {kind.value for kind in SmartChipKind} == {
        kind_value(entity_type, aspect) for entity_type, aspect in SMART_CHIP_KINDS
    }


async def test_a_chip_stops_at_the_sharing_gate_not_just_the_initiative(
    client, session, acting_user: ActingUser
) -> None:
    """Being in the initiative is not being given the project.

    A chip is live state, so it answers under every gate the thing itself
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

    assert (await _chips(client, a, f"task:{task.id}:status")) != {}
    assert await _chips(client, b, f"task:{task.id}:status") == {}


def test_every_chippable_thing_can_be_gated():
    """A chip reads live state, so its kind must resolve to a gate. Those are
    derived from the search registry, so this is what proves the derivation
    covers everything a chip can be about."""
    referenceable = set(referenceable_types())
    assert {entity_type for entity_type, _aspect in SMART_CHIP_KINDS} <= referenceable


def test_the_reference_surface_is_everything_indexed_but_a_comment():
    """Referenceable is derived, not listed. A tool added to the search
    registry becomes linkable, resolvable and gated with no edit here."""
    from app.db.search_index import SEARCH_SOURCES

    indexed = {source.entity_type for source in SEARCH_SOURCES.values()}
    assert set(referenceable_types()) == indexed - NOT_REFERENCEABLE


def test_what_can_be_referred_to_and_what_can_be_resolved_are_the_same_set():
    """One is declared from the kinds a reference may name, the other derived
    from the tables that can answer. A tool in one and not the other would be
    linkable and unresolvable, or resolvable and unreachable."""
    assert set(REFERENCEABLE_TYPES) == set(referenceable_types())


@pytest.mark.parametrize("aspect", ["status", "assignee", "due", "priority"])
async def test_no_task_chip_answers_without_the_project(
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

    assert await _chips(client, b, f"task:{task.id}:{aspect}") == {}


async def test_a_chip_follows_the_thing_own_sharing_either_way(
    client, session, acting_user: ActingUser
) -> None:
    """The gate is the resource's own sharing, not a rule chips invented.

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
    body = await _chips(
        client,
        b,
        f"counter:{counter.id}:value",
        f"calendar_event:{event.id}:when",
    )
    assert f"counter:{counter.id}:value" not in body
    assert f"calendar_event:{event.id}:when" in body


async def test_the_ceiling_is_refused_rather_than_quietly_trimmed(
    client, session, acting_user: ActingUser
) -> None:
    """A page asking about more than one request carries is told so.

    Answering the first ``MAX_REFS`` and dropping the rest would look exactly
    like a page whose remaining things had all been deleted, which is a worse
    answer than none: the client batches to this number instead.
    """
    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)
    task = await create_task(session, a.project, title="Ship it")

    at_the_line = [f"task:{task.id}:status"] * 1 + [
        f"task:{9000 + i}:status" for i in range(MAX_REFS - 1)
    ]
    response = await client.get(
        a.g("/smart-chips/"), headers=a.headers, params={"ref": at_the_line}
    )
    assert response.status_code == 200

    over = [*at_the_line, f"task:{9999}:status"]
    response = await client.get(
        a.g("/smart-chips/"), headers=a.headers, params={"ref": over}
    )
    assert response.status_code == 422


async def test_a_chip_names_what_its_reading_is_about(
    client, session, acting_user: ActingUser
) -> None:
    """A chip answers with the thing's current name beside the fact, so showing
    a fact costs one reference rather than two — and the name is as live as the
    reading is."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)
    task = await create_task(session, a.project, title="Old name")
    ref = f"task:{task.id}:status"

    assert (await _chips(client, a, ref))[ref]["title"] == "Old name"

    task.title = "New name"
    session.add(task)
    await session.commit()

    answer = (await _chips(client, a, ref))[ref]
    assert answer["title"] == "New name"
    # The reading itself is still the column, not the name.
    assert answer["text"] != "New name"


async def test_a_reference_reads_the_current_name(
    client, session, acting_user: ActingUser
) -> None:
    """The point of the whole thing: rename it, and what points at it says the
    new name without being touched."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)
    task = await create_task(session, a.project, title="Old name")
    ref = f"task:{task.id}"

    assert (await _chips(client, a, ref))[ref]["text"] == "Old name"

    task.title = "New name"
    session.add(task)
    await session.commit()

    assert (await _chips(client, a, ref))[ref]["text"] == "New name"


async def test_every_kind_answers_with_whatever_it_calls_its_name(
    client, session, acting_user: ActingUser
) -> None:
    """A queue item has a label, a task a title, a project a name. The column is
    derived from the search registry, so none of them is written down twice."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)
    task = await create_task(session, a.project, title="A task")
    queue = await create_queue(session, a.initiative, a.user)
    item = await create_queue_item(session, queue, label="An item")

    body = await _chips(
        client,
        a,
        f"task:{task.id}",
        f"project:{a.project.id}",
        f"queue:{queue.id}",
        f"queue_item:{item.id}",
    )
    assert body[f"task:{task.id}"]["text"] == "A task"
    assert body[f"project:{a.project.id}"]["text"] == a.project.name
    assert body[f"queue:{queue.id}"]["text"] == queue.name
    assert body[f"queue_item:{item.id}"]["text"] == "An item"


async def test_a_title_stops_at_the_same_gate_a_chip_does(
    client, session, acting_user: ActingUser
) -> None:
    """A name is content. Reading one is gated exactly as reading a status is."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)
    b = await acting_user(
        guild_role=GuildRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )
    task = await create_task(session, a.project, title="restricted")

    assert await _chips(client, b, f"task:{task.id}") == {}


async def test_a_comment_is_not_something_you_point_at(
    client, session, acting_user: ActingUser
) -> None:
    """Comments are indexed but not referenceable — the thing a remark is on is
    what a reader wants, and a comment has no name to render."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)
    task = await create_task(session, a.project, title="Ship it")
    comment = await create_comment(session, a.user, task=task)

    assert await _chips(client, a, f"comment:{comment.id}") == {}
