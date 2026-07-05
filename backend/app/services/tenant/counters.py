"""Counter service layer — DAC, query helpers, and value operations.

Mirrors the queues service. CounterGroups are owned containers under an
Initiative; Counters are independent numeric values clamped to optional
[min, max] bounds.
"""

from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlmodel.ext.asyncio.session import AsyncSession
from sqlalchemy.orm import selectinload
from sqlmodel import select

from app.services import permissions as permissions_service
from app.services.permissions import (
    DAC_RESOURCES,
    compute_permission,
    require_access,
)
from app.models.tenant.counter import (
    Counter,
    CounterGroup,
)
from app.models.tenant.initiative import Initiative
from app.models.tenant.resource_grant import ResourceAccessLevel, ResourceGrant
from app.models.platform.user import User
from app.schemas.tenant.counter import CounterSortDirection, CounterSortField


# ---------------------------------------------------------------------------
# Visibility subquery
# ---------------------------------------------------------------------------


def visible_counter_group_ids_subquery(user_id: int):
    """Return a subquery of counter-group IDs the user can access (DAC only)."""
    return permissions_service.visible_resource_ids_subquery("counter_group", user_id)


# DAC — thin wrappers over the registry engine (the "counter_group" row).


def compute_counter_group_permission(group: CounterGroup, user_id: int) -> str | None:
    return compute_permission(DAC_RESOURCES["counter_group"], group, user_id)


def require_counter_group_access(
    group: CounterGroup,
    user: User,
    *,
    access: str = "read",
    require_owner: bool = False,
) -> None:
    require_access(
        DAC_RESOURCES["counter_group"],
        group,
        user,
        access=access,
        require_owner=require_owner,
    )


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------


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
            selectinload(CounterGroup.initiative).selectinload(Initiative.memberships),
        )
    )
    if populate_existing:
        stmt = stmt.execution_options(populate_existing=True)
    result = await session.exec(stmt)
    return result.one_or_none()


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


async def duplicate_counter_group(
    session: AsyncSession,
    source: CounterGroup,
    *,
    name: str,
    user_id: int,
    guild_id: int,
) -> CounterGroup:
    """Create a copy of ``source`` within the same initiative.

    Copies every live counter (values, bounds, view mode, position) and the
    source's role + user permissions, then makes ``user_id`` the owner of the
    copy. Adds the new rows to the session and flushes; the caller commits.
    """
    new_group = CounterGroup(
        guild_id=guild_id,
        initiative_id=source.initiative_id,
        created_by_id=user_id,
        name=name,
        description=source.description,
    )
    session.add(new_group)
    await session.flush()

    session.add(
        ResourceGrant(
            resource_type="counter_group",
            resource_id=new_group.id,
            user_id=user_id,
            role_id=None,
            level=ResourceAccessLevel.owner,
            guild_id=guild_id,
            initiative_id=new_group.initiative_id,
        )
    )

    for grant in getattr(source, "grants", None) or []:
        if grant.level == ResourceAccessLevel.owner:
            continue
        if grant.role_id is not None:
            session.add(
                ResourceGrant(
                    resource_type="counter_group",
                    resource_id=new_group.id,
                    user_id=None,
                    role_id=grant.role_id,
                    level=grant.level,
                    guild_id=guild_id,
                    initiative_id=new_group.initiative_id,
                )
            )
        elif grant.user_id is not None and grant.user_id != user_id:
            session.add(
                ResourceGrant(
                    resource_type="counter_group",
                    resource_id=new_group.id,
                    user_id=grant.user_id,
                    role_id=None,
                    level=grant.level,
                    guild_id=guild_id,
                    initiative_id=new_group.initiative_id,
                )
            )

    for counter in getattr(source, "counters", None) or []:
        if counter.deleted_at is not None:
            continue
        session.add(
            Counter(
                guild_id=guild_id,
                counter_group_id=new_group.id,
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

    return new_group


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
