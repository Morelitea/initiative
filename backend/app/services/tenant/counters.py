"""Counter service layer — DAC, query helpers, and value operations.

Mirrors the queues service. CounterGroups are owned containers under an
Initiative; Counters are independent numeric values clamped to optional
[min, max] bounds.
"""

from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlmodel.ext.asyncio.session import AsyncSession
from sqlalchemy.orm import selectinload, undefer
from sqlalchemy import func, literal, update
from sqlmodel import select

from app.models.tenant.counter import (
    COUNTER_LIMIT,
    Counter,
    CounterGroup,
)
from app.models.tenant.initiative import Initiative
from app.models.tenant.resource_grant import ResourceGrant
from app.schemas.tenant.counter import CounterSortDirection, CounterSortField
from app.services.tenant import properties as properties_service
from app.services.tenant import tags as tags_service


# ---------------------------------------------------------------------------
# Visibility subquery
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------


def list_loader_options() -> list:
    """Eager-load what a counter-group *list* row needs: its sharing, the level
    the request holds on it and its tags."""
    return [
        selectinload(CounterGroup.grants).selectinload(ResourceGrant.role),
        selectinload(CounterGroup.initiative),
        undefer(CounterGroup.actions),
    ]


async def get_counter_group(
    session: AsyncSession,
    group_id: int,
    *,
    populate_existing: bool = False,
) -> CounterGroup | None:
    stmt = (
        select(CounterGroup)
        .where(CounterGroup.id == group_id)
        .options(
            selectinload(CounterGroup.counters),
            selectinload(CounterGroup.grants).selectinload(ResourceGrant.role),
            selectinload(CounterGroup.initiative),
            undefer(CounterGroup.actions),
        )
    )
    if populate_existing:
        stmt = stmt.execution_options(populate_existing=True)
    result = await session.exec(stmt)
    group = result.one_or_none()
    if group is not None:
        await tags_service.annotate_tags(session, [group])
        await properties_service.annotate_properties(session, [group])
        await properties_service.annotate_properties(session, group.counters or [])
    return group


async def list_counter_group_ids_for_export(
    session: AsyncSession,
    current_user,
    guild_id: int,
    *,
    initiative_ids: list[int],
) -> list[int]:
    """Ids of every counter group the user may export in the given initiatives —
    DAC-visible to the user (a request that reaches the whole guild sees all),
    feature-flag respected. Deterministic order for stable backup output."""

    if not initiative_ids:
        return []
    conditions = [
        CounterGroup.initiative_id.in_(initiative_ids),
        Initiative.counter_groups_enabled == True,  # noqa: E712
    ]
    statement = (
        select(CounterGroup.id)
        .join(Initiative, Initiative.id == CounterGroup.initiative_id)
        .where(*conditions)
        .order_by(CounterGroup.id.asc())
    )
    return list(await session.exec(statement))


async def get_counter(
    session: AsyncSession,
    counter_id: int,
    *,
    populate_existing: bool = False,
) -> Counter | None:
    stmt = select(Counter).where(Counter.id == counter_id)
    if populate_existing:
        stmt = stmt.execution_options(populate_existing=True)
    counter = (await session.exec(stmt)).one_or_none()
    await properties_service.annotate_properties(session, [counter])
    return counter


# ---------------------------------------------------------------------------
# Value operations (pure: caller commits)
# ---------------------------------------------------------------------------


def clamp(value: Decimal, lo: Optional[Decimal], hi: Optional[Decimal]) -> Decimal:
    if lo is not None and value < lo:
        value = lo
    if hi is not None and value > hi:
        value = hi
    return value


def _touch(counter: Counter) -> None:
    counter.updated_at = datetime.now(timezone.utc)


async def set_count(session: AsyncSession, counter: Counter, value: Decimal) -> Counter:
    counter.count = clamp(value, counter.min, counter.max)
    _touch(counter)
    session.add(counter)
    return counter


async def step_counter(
    session: AsyncSession,
    counter_id: int,
    *,
    up: bool,
    amount: Optional[Decimal] = None,
) -> None:
    """Move a counter by ``amount``, or by its own step, within its bounds.

    One statement, so two steps landing together each count: the new value is
    computed from the row as the database holds it, not from a copy read
    earlier. ``GREATEST`` and ``LEAST`` skip a NULL bound, so an open side needs
    no case of its own, and the largest number a counter can store bounds both
    sides, so an open counter stops there rather than overflowing.
    """
    by = Counter.step if amount is None else literal(amount)
    moved = Counter.count + by if up else Counter.count - by
    await session.exec(
        update(Counter)
        .where(Counter.id == counter_id)
        .values(
            count=func.least(
                func.greatest(moved, Counter.min, -COUNTER_LIMIT),
                Counter.max,
                COUNTER_LIMIT,
            ),
            updated_at=datetime.now(timezone.utc),
        )
    )


async def reset_counter(session: AsyncSession, counter: Counter) -> Counter:
    counter.count = clamp(counter.initial_count, counter.min, counter.max)
    _touch(counter)
    session.add(counter)
    return counter


async def reset_all_counters(
    session: AsyncSession, group: CounterGroup
) -> CounterGroup:
    counters = getattr(group, "counters", None) or []
    now = datetime.now(timezone.utc)
    for counter in counters:
        if counter.deleted_at is not None:
            continue
        counter.count = clamp(counter.initial_count, counter.min, counter.max)
        counter.updated_at = now
        session.add(counter)
    group.updated_at = now
    session.add(group)
    return group


async def sort_counters(
    session: AsyncSession,
    group: CounterGroup,
    *,
    field: CounterSortField,
    direction: CounterSortDirection,
) -> CounterGroup:
    """Reassign every live counter's position to a clean ``1..N`` sequence.

    The sort key always appends ``id`` as a final tie-break so the order is
    deterministic and repeatable — descending is the exact reverse of
    ascending, and re-sorting an already-sorted group is idempotent.
    """
    counters = [
        c for c in (getattr(group, "counters", None) or []) if c.deleted_at is None
    ]

    if field == CounterSortField.name:

        def key(c: Counter):
            return (c.name.casefold(), c.id)
    else:

        def key(c: Counter):
            return (c.count, c.name.casefold(), c.id)

    counters.sort(key=key, reverse=direction == CounterSortDirection.desc)

    now = datetime.now(timezone.utc)
    for index, counter in enumerate(counters):
        counter.position = Decimal(index + 1)
        counter.updated_at = now
        session.add(counter)
    group.updated_at = now
    session.add(group)
    return group
