"""Counter service layer — DAC, query helpers, and value operations.

Mirrors the queues service. CounterGroups are owned containers under an
Initiative; Counters are independent numeric values clamped to optional
[min, max] bounds.
"""

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlmodel import select

from app.core.messages import CounterMessages
from app.core.pam_context import grant_satisfies
from app.services.permissions import lift_level_for_grant
from app.models.counter import (
    Counter,
    CounterGroup,
    CounterGroupPermission,
    CounterGroupRolePermission,
    CounterPermissionLevel,
)
from app.models.initiative import Initiative, InitiativeMember
from app.models.user import User
from app.schemas.counter import CounterSortDirection, CounterSortField
from app.services.permissions import effective_permission_level, role_permission_level


# ---------------------------------------------------------------------------
# DAC constants
# ---------------------------------------------------------------------------

COUNTER_LEVEL_ORDER: dict[CounterPermissionLevel, int] = {
    CounterPermissionLevel.read: 0,
    CounterPermissionLevel.write: 1,
    CounterPermissionLevel.owner: 2,
}


# ---------------------------------------------------------------------------
# Visibility subquery
# ---------------------------------------------------------------------------


def visible_counter_group_ids_subquery(user_id: int):
    """Return a subquery of counter-group IDs the user can access (DAC only)."""
    user_perm_subq = select(CounterGroupPermission.counter_group_id).where(
        CounterGroupPermission.user_id == user_id
    )
    role_perm_subq = select(CounterGroupRolePermission.counter_group_id).join(
        InitiativeMember,
        (InitiativeMember.role_id == CounterGroupRolePermission.initiative_role_id)
        & (InitiativeMember.user_id == user_id),
    )
    return user_perm_subq.union(role_perm_subq)


# ---------------------------------------------------------------------------
# DAC helpers
# ---------------------------------------------------------------------------


def counter_group_role_permission_level(
    group: Any,
    user_id: int,
) -> CounterPermissionLevel | None:
    role_perms = getattr(group, "role_permissions", None)
    initiative = getattr(group, "initiative", None)
    memberships = getattr(initiative, "memberships", None) if initiative else None
    return role_permission_level(role_perms, memberships, user_id, COUNTER_LEVEL_ORDER)


def effective_counter_group_permission(
    user_level: CounterPermissionLevel | None,
    role_level: CounterPermissionLevel | None,
) -> CounterPermissionLevel | None:
    return effective_permission_level(user_level, role_level, COUNTER_LEVEL_ORDER)


def compute_counter_group_permission(
    group: CounterGroup,
    user_id: int,
) -> str | None:
    user_level: CounterPermissionLevel | None = None
    perms = getattr(group, "permissions", None) or []
    for perm in perms:
        if perm.user_id == user_id:
            user_level = perm.level
            break

    role_level = counter_group_role_permission_level(group, user_id)
    effective = effective_counter_group_permission(user_level, role_level)
    return lift_level_for_grant(
        effective.value if effective else None, getattr(group, "guild_id", None)
    )


def _effective_level(group: CounterGroup, user: User) -> CounterPermissionLevel | None:
    user_level: CounterPermissionLevel | None = None
    perms = getattr(group, "permissions", None) or []
    for perm in perms:
        if perm.user_id == user.id:
            user_level = perm.level
            break
    role_level = counter_group_role_permission_level(group, user.id)
    return effective_counter_group_permission(user_level, role_level)


def require_counter_group_access(
    group: CounterGroup,
    user: User,
    *,
    access: str = "read",
    require_owner: bool = False,
) -> None:
    # A live PAM grant covering the group's guild satisfies read/write.
    if grant_satisfies(group.guild_id, access=access, require_owner=require_owner):
        return
    effective = _effective_level(group, user)

    if require_owner:
        if effective != CounterPermissionLevel.owner:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=CounterMessages.OWNER_REQUIRED,
            )
        return

    if effective is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=CounterMessages.PERMISSION_REQUIRED,
        )

    if access == "write" and effective == CounterPermissionLevel.read:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=CounterMessages.WRITE_ACCESS_REQUIRED,
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
            selectinload(CounterGroup.permissions),
            selectinload(CounterGroup.role_permissions).selectinload(
                CounterGroupRolePermission.role
            ),
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
        CounterGroupPermission(
            counter_group_id=new_group.id,
            user_id=user_id,
            guild_id=guild_id,
            level=CounterPermissionLevel.owner,
        )
    )

    for rp in getattr(source, "role_permissions", None) or []:
        if rp.level == CounterPermissionLevel.owner:
            continue
        session.add(
            CounterGroupRolePermission(
                counter_group_id=new_group.id,
                initiative_role_id=rp.initiative_role_id,
                guild_id=guild_id,
                level=rp.level,
            )
        )

    for perm in getattr(source, "permissions", None) or []:
        if perm.level == CounterPermissionLevel.owner or perm.user_id == user_id:
            continue
        session.add(
            CounterGroupPermission(
                counter_group_id=new_group.id,
                user_id=perm.user_id,
                guild_id=guild_id,
                level=perm.level,
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
