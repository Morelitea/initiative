from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Iterable

from sqlalchemy import func
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.initiative import Initiative, InitiativeMember, InitiativeRole
from app.models.user import User, UserRole
from app.schemas.user import UserInitiativeRole

DEFAULT_INITIATIVE_NAME = "Default Initiative"
DEFAULT_INITIATIVE_COLOR = "#2563eb"


async def ensure_default_initiative(session: AsyncSession, admin_user: User) -> Initiative:
    statement = select(Initiative).where(Initiative.is_default.is_(True))
    result = await session.exec(statement)
    default_initiative = result.one_or_none()
    if default_initiative:
        await _ensure_membership_with_role(
            session,
            initiative_id=default_initiative.id,
            user_id=admin_user.id,
            role=InitiativeRole.project_manager,
        )
        await session.refresh(default_initiative, attribute_names=["memberships"])
        return default_initiative

    now = datetime.now(timezone.utc)
    default_initiative = Initiative(
        name=DEFAULT_INITIATIVE_NAME,
        description="Automatically created default initiative",
        color=DEFAULT_INITIATIVE_COLOR,
        is_default=True,
        created_at=now,
        updated_at=now,
    )
    session.add(default_initiative)
    await session.flush()
    session.add(
        InitiativeMember(
            initiative_id=default_initiative.id,
            user_id=admin_user.id,
            role=InitiativeRole.project_manager,
        )
    )
    await session.flush()
    await session.refresh(default_initiative, attribute_names=["memberships"])
    return default_initiative


async def load_user_initiative_roles(session: AsyncSession, users: Sequence[User]) -> None:
    user_ids = [user.id for user in users if user.id is not None]
    if not user_ids:
        return
    stmt = (
        select(
            InitiativeMember.user_id,
            InitiativeMember.role,
            Initiative.id,
            Initiative.name,
        )
        .join(Initiative, Initiative.id == InitiativeMember.initiative_id)
        .where(InitiativeMember.user_id.in_(tuple(user_ids)))
    )
    result = await session.exec(stmt)
    assignments: dict[int, list[UserInitiativeRole]] = {user_id: [] for user_id in user_ids}
    for user_id, role, initiative_id, initiative_name in result.all():
        assignments.setdefault(user_id, []).append(
            UserInitiativeRole(initiative_id=initiative_id, initiative_name=initiative_name, role=role)
        )
    for user in users:
        user_assignments = assignments.get(user.id or 0, [])
        object.__setattr__(user, "initiative_roles", user_assignments)


async def _ensure_membership_with_role(
    session: AsyncSession,
    *,
    initiative_id: int,
    user_id: int,
    role: InitiativeRole,
) -> None:
    stmt = select(InitiativeMember).where(
        InitiativeMember.initiative_id == initiative_id,
        InitiativeMember.user_id == user_id,
    )
    result = await session.exec(stmt)
    membership = result.one_or_none()
    if membership:
        if membership.role != role:
            membership.role = role
            session.add(membership)
            await session.flush()
        return
    session.add(
        InitiativeMember(
            initiative_id=initiative_id,
            user_id=user_id,
            role=role,
        )
    )
    await session.flush()


async def get_initiative_membership(
    session: AsyncSession,
    *,
    initiative_id: int,
    user_id: int,
) -> InitiativeMember | None:
    stmt = select(InitiativeMember).where(
        InitiativeMember.initiative_id == initiative_id,
        InitiativeMember.user_id == user_id,
    )
    result = await session.exec(stmt)
    return result.one_or_none()


async def is_initiative_manager(
    session: AsyncSession,
    *,
    initiative_id: int,
    user: User,
) -> bool:
    if user.role == UserRole.admin:
        return True
    membership = await get_initiative_membership(session, initiative_id=initiative_id, user_id=user.id)
    return bool(membership and membership.role == InitiativeRole.project_manager)


async def assert_initiative_manager(
    session: AsyncSession,
    *,
    initiative_id: int,
    user: User,
) -> None:
    if await is_initiative_manager(session, initiative_id=initiative_id, user=user):
        return
    raise PermissionError("Initiative manager role required")


async def ensure_managers_remain(
    session: AsyncSession,
    *,
    initiative_id: int,
    excluded_user_ids: Iterable[int] | None = None,
) -> None:
    excluded = set(excluded_user_ids or [])
    stmt = select(InitiativeMember).where(
        InitiativeMember.initiative_id == initiative_id,
        InitiativeMember.role == InitiativeRole.project_manager,
    )
    result = await session.exec(stmt)
    managers = [membership for membership in result.all() if membership.user_id not in excluded]
    if not managers:
        raise ValueError("Initiative must have at least one project manager")


async def initiatives_requiring_new_pm(session: AsyncSession, user_id: int) -> list[Initiative]:
    subquery = (
        select(
            InitiativeMember.initiative_id,
            func.count().label("pm_count"),
        )
        .where(InitiativeMember.role == InitiativeRole.project_manager)
        .group_by(InitiativeMember.initiative_id)
        .subquery()
    )

    stmt = (
        select(Initiative)
        .join(InitiativeMember, InitiativeMember.initiative_id == Initiative.id)
        .join(subquery, subquery.c.initiative_id == Initiative.id)
        .where(
            InitiativeMember.user_id == user_id,
            InitiativeMember.role == InitiativeRole.project_manager,
            subquery.c.pm_count == 1,
        )
    )
    result = await session.exec(stmt)
    return result.all()


async def ensure_user_not_sole_pm(session: AsyncSession, user_id: int) -> None:
    initiatives = await initiatives_requiring_new_pm(session, user_id)
    if initiatives:
        names = ", ".join(initiative.name for initiative in initiatives)
        raise ValueError(f"User is the sole project manager for: {names}")
