"""Counter service layer — DAC, query helpers, and value operations.

Mirrors the queues service. CounterGroups are owned containers under an
Initiative; Counters are independent numeric values clamped to optional
[min, max] bounds.
"""

from datetime import datetime, timezone
from app.db import session as db_session
from app.core.tools import Tool
from decimal import Decimal
from typing import Optional

from sqlmodel.ext.asyncio.session import AsyncSession
from sqlalchemy.orm import selectinload, undefer
from sqlmodel import select

from app.services.permissions import (
    DAC_RESOURCES,
    require_export_access,
)
from app.models.tenant.counter import (
    Counter,
    CounterGroup,
)
from app.models.tenant.initiative import Initiative
from app.models.tenant.resource_grant import ResourceGrant
from app.models.platform.user import User
from app.schemas.tenant.counter import CounterSortDirection, CounterSortField
from app.services.tenant import tags as tags_service


# ---------------------------------------------------------------------------
# Visibility subquery
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------


def list_loader_options() -> list:
    """Eager-load what a counter-group *list* row needs: its counters (for the
    count), its sharing, the level the request holds on it and its tags."""
    return [
        selectinload(CounterGroup.counters),
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
    return group


async def get_counter_group_for_export(
    session: AsyncSession,
    current_user: User,
    guild_id: int,
    *,
    group_id: int,
    access: str = "owner",
) -> CounterGroup:
    """The counter-export adapter's seam: fetch + authorize in one place so the
    rule holds on the worker's render-time replay too. It takes the owner rung,
    or ``access="read"`` from an initiative or community backup
    (``permissions.require_export_access``). The guild role is resolved here
    rather than taken from a request context, so the seam works transport-free."""
    from fastapi import HTTPException, status as http_status

    group = await get_counter_group(session, group_id)
    if group is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail=Tool.counter_group.not_found_code,
        )
    if group.initiative is not None and not group.initiative.counter_groups_enabled:
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail=Tool.counter_group.feature_disabled_code,
        )
    require_export_access(
        DAC_RESOURCES[Tool.counter_group],
        group,
        context=db_session.guild_context(session),
        access=access,
    )
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
    result = await session.exec(stmt)
    return result.one_or_none()


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


async def increment_counter(session: AsyncSession, counter: Counter) -> Counter:
    counter.count = clamp(counter.count + counter.step, counter.min, counter.max)
    _touch(counter)
    session.add(counter)
    return counter


async def decrement_counter(session: AsyncSession, counter: Counter) -> Counter:
    counter.count = clamp(counter.count - counter.step, counter.min, counter.max)
    _touch(counter)
    session.add(counter)
    return counter


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


async def copy_counters(
    session: AsyncSession, source: CounterGroup, target: CounterGroup
) -> None:
    """Copy every live counter of ``source`` (values, bounds, view mode,
    position) into ``target``, a duplicate whose sharing is already in the
    session. Adds the rows; the caller commits.
    """
    # The sharing has to be IN the database before the counters are, because a
    # counter is reached through its group: adding it to the session is not
    # enough, since a flush orders its statements by table rather than by the
    # order things were added.
    await session.flush()

    for counter in source.counters:
        if counter.deleted_at is not None:
            continue
        session.add(
            Counter(
                counter_group_id=target.id,
                name=counter.name,
                color=counter.color,
                count=counter.count,
                min=counter.min,
                max=counter.max,
                step=counter.step,
                initial_count=counter.initial_count,
                view_mode=counter.view_mode,
                position=counter.position,
            )
        )


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
