"""Reading what a badge currently shows.

A badge stores nothing. The document holds a reference — ``task:12:status`` —
and this reads the row that reference names, every time, so a chip is never
older than the last request.

One entry per ``(kind, aspect)`` in :data:`BADGE_SOURCES`, and each entry reads
its whole set of ids in ONE query. A document with thirty task badges makes one
request, and that request makes one query per aspect it uses — not one per chip.

Every read goes through the session it is handed, which is the request's
RLS-scoped one, so a reference to something the caller cannot see comes back
absent rather than as an error or a row.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import Select, func
from sqlmodel import select

from app.core.document_badges import (
    BadgeAspect,
    BadgeKind,
    BadgeTone,
    REF_SEPARATOR,
    kind_value,
)
from app.core.search import SearchEntityType
from app.core.tools import Tool
from app.core.user_display import display_name
from app.models.platform.user import User
from app.models.tenant.calendar import Calendar
from app.models.tenant.calendar_event import CalendarEvent
from app.models.tenant.counter import Counter, CounterGroup
from app.models.tenant.project import Project
from app.models.tenant.task import (
    Task,
    TaskAssignee,
    TaskPriority,
    TaskStatus,
    TaskStatusCategory,
)
from app.schemas.tenant.document_badge import BadgeState

#: Ceiling on one request. A document that names more things than this is not a
#: document, and the cost of a page is bounded either way.
MAX_REFS = 100


@dataclass(frozen=True)
class BadgeValue:
    """What one chip reads, before it is paired back to its reference."""

    text: str
    tone: BadgeTone = BadgeTone.neutral
    color: Optional[str] = None
    date: Optional[datetime] = None
    number: Optional[Decimal] = None


#: A reader takes the ids wanted and answers for the ones it can see.
Reader = Callable[[AsyncSession, list[int]], Awaitable[dict[int, BadgeValue]]]

#: Where a task sits, in the colour its own column carries. ``done`` is the one
#: category with a meaning every project shares, so it is the one that gets a
#: tone of its own; the rest are whatever the project called them.
_STATUS_TONES = {
    TaskStatusCategory.done: BadgeTone.good,
    TaskStatusCategory.in_progress: BadgeTone.warn,
}

_PRIORITY_TONES = {
    TaskPriority.urgent: BadgeTone.danger,
    TaskPriority.high: BadgeTone.warn,
    TaskPriority.low: BadgeTone.muted,
}


async def _task_status(session: AsyncSession, ids: list[int]) -> dict[int, BadgeValue]:
    rows = (
        await session.exec(
            select(Task.id, TaskStatus.name, TaskStatus.color, TaskStatus.category)
            .join(TaskStatus, TaskStatus.id == Task.task_status_id)
            .where(Task.id.in_(ids), Task.deleted_at.is_(None))
        )
    ).all()
    return {
        task_id: BadgeValue(
            text=name,
            tone=_STATUS_TONES.get(category, BadgeTone.neutral),
            color=color,
        )
        for task_id, name, color, category in rows
    }


async def _task_assignee(
    session: AsyncSession, ids: list[int]
) -> dict[int, BadgeValue]:
    """Who holds a task. Several people can, so the chip names the first and
    counts the rest rather than growing with the list."""
    rows = (
        await session.exec(
            select(TaskAssignee.task_id, User)
            .join(User, User.id == TaskAssignee.user_id)
            .where(TaskAssignee.task_id.in_(ids))
            .order_by(TaskAssignee.task_id, User.id)
        )
    ).all()
    holders: dict[int, list[User]] = {}
    for task_id, user in rows:
        holders.setdefault(task_id, []).append(user)

    values: dict[int, BadgeValue] = {}
    for task_id in ids:
        people = holders.get(task_id)
        if not people:
            # Answered, not missing: an unassigned task is a fact worth showing.
            values[task_id] = BadgeValue(text="", tone=BadgeTone.muted)
            continue
        # ``display_name`` reads the guild's own name-visibility setting, so a
        # badge shows exactly what every other surface here shows.
        first = display_name(people[0])
        extra = len(people) - 1
        values[task_id] = BadgeValue(text=f"{first} +{extra}" if extra else first)
    return values


async def _task_due(session: AsyncSession, ids: list[int]) -> dict[int, BadgeValue]:
    """When a task is due. Late is only late while it is unfinished — a job
    delivered a day after its date is done, not overdue."""
    rows = (
        await session.exec(
            select(Task.id, Task.due_date, TaskStatus.category)
            .join(TaskStatus, TaskStatus.id == Task.task_status_id)
            .where(Task.id.in_(ids), Task.deleted_at.is_(None))
        )
    ).all()
    now = datetime.now(timezone.utc)
    values: dict[int, BadgeValue] = {}
    for task_id, due, category in rows:
        if due is None:
            values[task_id] = BadgeValue(text="", tone=BadgeTone.muted)
            continue
        moment = due if due.tzinfo else due.replace(tzinfo=timezone.utc)
        late = moment < now and category != TaskStatusCategory.done
        values[task_id] = BadgeValue(
            text=moment.date().isoformat(),
            tone=BadgeTone.danger if late else BadgeTone.neutral,
            date=moment,
        )
    return values


async def _task_priority(
    session: AsyncSession, ids: list[int]
) -> dict[int, BadgeValue]:
    rows = (
        await session.exec(
            select(Task.id, Task.priority).where(
                Task.id.in_(ids), Task.deleted_at.is_(None)
            )
        )
    ).all()
    return {
        task_id: BadgeValue(
            text=priority.value,
            tone=_PRIORITY_TONES.get(priority, BadgeTone.neutral),
        )
        for task_id, priority in rows
    }


async def _counter_value(
    session: AsyncSession, ids: list[int]
) -> dict[int, BadgeValue]:
    """A counter's reading. Where it has a ceiling the chip says so, because a
    number is worth more against the number it is heading for."""
    rows = (
        await session.exec(
            select(Counter.id, Counter.count, Counter.max).where(
                Counter.id.in_(ids), Counter.deleted_at.is_(None)
            )
        )
    ).all()
    values: dict[int, BadgeValue] = {}
    for counter_id, count, ceiling in rows:
        reached = ceiling is not None and count >= ceiling
        values[counter_id] = BadgeValue(
            text=f"{_plain(count)} / {_plain(ceiling)}" if ceiling else _plain(count),
            tone=BadgeTone.good if reached else BadgeTone.neutral,
            number=count,
        )
    return values


async def _event_when(session: AsyncSession, ids: list[int]) -> dict[int, BadgeValue]:
    rows = (
        await session.exec(
            select(CalendarEvent.id, CalendarEvent.start_at).where(
                CalendarEvent.id.in_(ids), CalendarEvent.deleted_at.is_(None)
            )
        )
    ).all()
    now = datetime.now(timezone.utc)
    values: dict[int, BadgeValue] = {}
    for event_id, start in rows:
        moment = start if start.tzinfo else start.replace(tzinfo=timezone.utc)
        values[event_id] = BadgeValue(
            text=moment.date().isoformat(),
            tone=BadgeTone.muted if moment < now else BadgeTone.neutral,
            date=moment,
        )
    return values


def _plain(value: Decimal) -> str:
    """A stored number as a person writes it — ``7`` rather than ``7.0000``."""
    trimmed = value.normalize()
    return format(trimmed, "f")


#: (kind, aspect) -> how to read it. Adding a badge is one entry here: the
#: endpoint, the accepted refs and the menu the editor offers all derive from
#: this, so none of them is a second list to keep in step.
BADGE_SOURCES: dict[tuple[SearchEntityType, BadgeAspect], Reader] = {
    (SearchEntityType.task, BadgeAspect.status): _task_status,
    (SearchEntityType.task, BadgeAspect.assignee): _task_assignee,
    (SearchEntityType.task, BadgeAspect.due): _task_due,
    (SearchEntityType.task, BadgeAspect.priority): _task_priority,
    (SearchEntityType.counter, BadgeAspect.value): _counter_value,
    (SearchEntityType.calendar_event, BadgeAspect.when): _event_when,
}


def reader_for(entity_type: SearchEntityType, aspect: BadgeAspect) -> Reader:
    """The reader for one pair. Raises for a pair with none, which
    ``document_badges_test`` proves cannot happen."""
    return BADGE_SOURCES[(entity_type, aspect)]


def parse_ref(ref: str) -> Optional[tuple[SearchEntityType, int, BadgeAspect]]:
    """``task:12:status`` as its three parts, or ``None`` if it names no badge.

    A reference that does not parse is dropped rather than refused: a document
    can outlive a build that stopped offering one of these, and a chip that
    cannot be read falls back to the words already stored beside it.
    """
    parts = ref.split(REF_SEPARATOR)
    if len(parts) != 3:
        return None
    kind, raw_id, aspect = parts
    if not raw_id.isdigit():
        return None
    try:
        pair = (SearchEntityType(kind), BadgeAspect(aspect))
    except ValueError:
        return None
    if pair not in BADGE_SOURCES:
        return None
    return pair[0], int(raw_id), pair[1]


def format_ref(kind: SearchEntityType, entity_id: int, aspect: BadgeAspect) -> str:
    """The reference a document stores for one chip."""
    return REF_SEPARATOR.join((kind.value, str(entity_id), aspect.value))


#: How each badgeable thing answers the sharing gate: the resource that governs
#: it, and the initiative that resource sits in.
#:
#: ``public.resource_access`` is the same function the tables' own RLS policies
#: call, so a badge is allowed exactly what opening the thing is allowed. One
#: entry per kind rather than per aspect — sharing is a property of the thing,
#: not of the fact being read about it.
_ACCESS: dict[SearchEntityType, Callable[[int], Select]] = {
    SearchEntityType.task: lambda user_id: (
        select(Task.id)
        .join(Project, Project.id == Task.project_id)
        .where(
            func.resource_access(
                Tool.project.value, Project.id, user_id, Project.initiative_id, False
            )
        )
    ),
    SearchEntityType.counter: lambda user_id: (
        select(Counter.id)
        .join(CounterGroup, CounterGroup.id == Counter.counter_group_id)
        .where(
            func.resource_access(
                Tool.counter_group.value,
                CounterGroup.id,
                user_id,
                CounterGroup.initiative_id,
                False,
            )
        )
    ),
    SearchEntityType.calendar_event: lambda user_id: (
        select(CalendarEvent.id)
        .join(Calendar, Calendar.id == CalendarEvent.calendar_id)
        .where(
            func.resource_access(
                Tool.calendar.value,
                Calendar.id,
                user_id,
                Calendar.initiative_id,
                False,
            )
        )
    ),
}


async def _visible(
    session: AsyncSession, *, user_id: int, wanted: dict[SearchEntityType, set[int]]
) -> dict[SearchEntityType, set[int]]:
    """Which of the things asked about this request may actually open.

    Being routed into the guild and being in the initiative is not the whole
    answer — a tool is shared per resource, and that is the gate this applies.

    Done here rather than inside each reader on purpose: a badge added later
    cannot forget it, because a reader is never handed an id that did not come
    back from this. ``document_badges_test`` walks every declared badge and
    proves each one stops here.
    """
    seen: dict[SearchEntityType, set[int]] = {}
    for entity_type, ids in wanted.items():
        statement = _ACCESS[entity_type](user_id).where(
            _ID_COLUMNS[entity_type].in_(ids)
        )
        seen[entity_type] = set((await session.exec(statement)).all())
    return seen


#: The id each gate selects, for narrowing it to what was asked about.
_ID_COLUMNS: dict[SearchEntityType, Any] = {
    SearchEntityType.task: Task.id,
    SearchEntityType.counter: Counter.id,
    SearchEntityType.calendar_event: CalendarEvent.id,
}


async def read_badges(
    session: AsyncSession, *, user_id: int, refs: list[str]
) -> list[BadgeState]:
    """Current state for every reference that resolves, in the order asked.

    Grouped by ``(kind, aspect)`` so each reader runs once over its whole set of
    ids. A reference naming something that is gone, or that this caller cannot
    see, is left out of the answer.
    """
    wanted: dict[tuple[SearchEntityType, BadgeAspect], list[int]] = {}
    parsed: list[tuple[str, tuple[SearchEntityType, BadgeAspect], int]] = []
    for ref in dict.fromkeys(refs[:MAX_REFS]):
        resolved = parse_ref(ref)
        if resolved is None:
            continue
        kind, entity_id, aspect = resolved
        wanted.setdefault((kind, aspect), []).append(entity_id)
        parsed.append((ref, (kind, aspect), entity_id))

    by_type: dict[SearchEntityType, set[int]] = {}
    for (entity_type, _aspect), ids in wanted.items():
        by_type.setdefault(entity_type, set()).update(ids)
    visible = await _visible(session, user_id=user_id, wanted=by_type)

    read: dict[tuple[SearchEntityType, BadgeAspect], dict[int, BadgeValue]] = {}
    for pair, ids in wanted.items():
        allowed = [i for i in ids if i in visible.get(pair[0], ())]
        read[pair] = await BADGE_SOURCES[pair](session, allowed) if allowed else {}

    states: list[BadgeState] = []
    for ref, pair, entity_id in parsed:
        value = read.get(pair, {}).get(entity_id)
        if value is None:
            continue
        states.append(
            BadgeState(
                ref=ref,
                kind=BadgeKind(kind_value(*pair)),
                text=value.text,
                tone=value.tone,
                color=value.color,
                date=value.date,
                number=value.number,
            )
        )
    return states
