from datetime import datetime, timezone
from typing import Annotated, List
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import select, delete

from app.api.deps import (
    SessionDep,
    get_current_active_user,
    get_guild_membership,
    GuildContext,
    require_guild_roles,
)
from app.core.security import get_password_hash
from app.models.task import TaskAssignee
from app.models.guild import GuildRole, GuildMembership
from app.models.user import User, UserRole
from app.schemas.user import UserCreate, UserRead, UserSelfUpdate, UserUpdate
from app.services import notifications as notifications_service
from app.services import initiatives as initiatives_service
from app.services import guilds as guilds_service

router = APIRouter()

GuildContextDep = Annotated[GuildContext, Depends(get_guild_membership)]
GuildAdminContext = Annotated[GuildContext, Depends(require_guild_roles(GuildRole.admin))]

SUPER_USER_ID = 1
TIME_PATTERN = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")


def _normalize_timezone(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    try:
        ZoneInfo(cleaned)
    except ZoneInfoNotFoundError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid timezone")
    return cleaned


def _normalize_notification_time(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    if not TIME_PATTERN.match(cleaned):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid time format")
    return cleaned


@router.get("/me", response_model=UserRead)
async def read_users_me(session: SessionDep, current_user: Annotated[User, Depends(get_current_active_user)]) -> User:
    await initiatives_service.load_user_initiative_roles(session, [current_user])
    return current_user


@router.get("/", response_model=List[UserRead])
async def list_users(
    session: SessionDep,
    _current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> List[User]:
    stmt = (
        select(User)
        .join(GuildMembership, GuildMembership.user_id == User.id)
        .where(GuildMembership.guild_id == guild_context.guild_id)
        .order_by(User.created_at.asc())
    )
    result = await session.exec(stmt)
    users = result.all()
    await initiatives_service.load_user_initiative_roles(session, users)
    return users


@router.post("/", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def create_user(
    user_in: UserCreate,
    session: SessionDep,
    _current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildAdminContext,
) -> User:
    statement = select(User).where(User.email == user_in.email)
    result = await session.exec(statement)
    if result.one_or_none():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered")

    guild_id = guild_context.guild_id

    user = User(
        email=user_in.email,
        full_name=user_in.full_name,
        hashed_password=get_password_hash(user_in.password),
        role=user_in.role,
        email_verified=True,
        active_guild_id=guild_id,
    )
    session.add(user)
    await session.flush()
    await guilds_service.ensure_membership(
        session,
        guild_id=guild_id,
        user_id=user.id,
        role=GuildRole.admin if user.role == UserRole.admin else GuildRole.member,
    )
    if user.role == UserRole.admin:
        await initiatives_service.ensure_default_initiative(session, user, guild_id=guild_id)
    await session.commit()
    await session.refresh(user)
    await initiatives_service.load_user_initiative_roles(session, [user])
    return user


@router.patch("/me", response_model=UserRead)
async def update_users_me(
    user_in: UserSelfUpdate,
    session: SessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> User:
    update_data = user_in.dict(exclude_unset=True)
    if not update_data:
        return current_user

    new_full_name = update_data.get("full_name")
    if new_full_name is not None:
        current_user.full_name = new_full_name or None

    password = update_data.get("password")
    if password:
        current_user.hashed_password = get_password_hash(password)

    if "avatar_base64" in update_data:
        avatar_value = update_data["avatar_base64"]
        if avatar_value:
            current_user.avatar_base64 = avatar_value
            current_user.avatar_url = None
        else:
            current_user.avatar_base64 = None

    if "avatar_url" in update_data:
        url_value = update_data["avatar_url"]
        if url_value:
            current_user.avatar_url = url_value
            current_user.avatar_base64 = None
        else:
            current_user.avatar_url = None
    if "show_project_sidebar" in update_data:
        current_user.show_project_sidebar = bool(update_data["show_project_sidebar"])
    if "show_project_tabs" in update_data:
        current_user.show_project_tabs = bool(update_data["show_project_tabs"])
    if "timezone" in update_data:
        normalized_timezone = _normalize_timezone(update_data["timezone"])
        if normalized_timezone:
            current_user.timezone = normalized_timezone
    if "overdue_notification_time" in update_data:
        normalized_time = _normalize_notification_time(update_data["overdue_notification_time"])
        if normalized_time:
            current_user.overdue_notification_time = normalized_time
    for field in [
        "notify_initiative_addition",
        "notify_task_assignment",
        "notify_project_added",
        "notify_overdue_tasks",
    ]:
        if field in update_data:
            new_value = bool(update_data[field])
            setattr(current_user, field, new_value)
            if field == "notify_task_assignment" and not new_value:
                await notifications_service.clear_task_assignment_queue_for_user(session, current_user.id)

    current_user.updated_at = datetime.now(timezone.utc)
    session.add(current_user)
    await session.commit()
    await session.refresh(current_user)
    await initiatives_service.load_user_initiative_roles(session, [current_user])
    return current_user


@router.patch("/{user_id}", response_model=UserRead)
async def update_user(
    user_id: int,
    user_in: UserUpdate,
    session: SessionDep,
    _current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildAdminContext,
) -> User:
    stmt = (
        select(User)
        .join(GuildMembership, GuildMembership.user_id == User.id)
        .where(
            User.id == user_id,
            GuildMembership.guild_id == guild_context.guild_id,
        )
    )
    result = await session.exec(stmt)
    user = result.one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    update_data = user_in.dict(exclude_unset=True)
    if user.id == SUPER_USER_ID and "role" in update_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot change the super user's role",
        )
    if update_data.get("role") == UserRole.member and user.role == UserRole.admin:
        try:
            await initiatives_service.ensure_user_not_sole_pm(session, user_id=user.id)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if (password := update_data.pop("password", None)):
        user.hashed_password = get_password_hash(password)
    if "avatar_base64" in update_data:
        user.avatar_base64 = update_data.pop("avatar_base64")
        if user.avatar_base64:
            user.avatar_url = None
    if "avatar_url" in update_data:
        user.avatar_url = update_data.pop("avatar_url")
        if user.avatar_url:
            user.avatar_base64 = None
    for field, value in update_data.items():
        if field == "timezone":
            normalized_timezone = _normalize_timezone(value)
            if normalized_timezone:
                setattr(user, field, normalized_timezone)
            continue
        if field == "overdue_notification_time":
            normalized_time = _normalize_notification_time(value)
            if normalized_time:
                setattr(user, field, normalized_time)
            continue
        if field == "notify_task_assignment" and value is False:
            await notifications_service.clear_task_assignment_queue_for_user(session, user.id)
        setattr(user, field, value)
    user.updated_at = datetime.now(timezone.utc)

    session.add(user)
    await session.flush()
    await guilds_service.ensure_membership(
        session,
        guild_id=guild_context.guild_id,
        user_id=user.id,
        role=GuildRole.admin if user.role == UserRole.admin else GuildRole.member,
    )
    if user.role == UserRole.admin:
        await initiatives_service.ensure_default_initiative(session, user, guild_id=guild_context.guild_id)
    await session.commit()
    await session.refresh(user)
    await initiatives_service.load_user_initiative_roles(session, [user])
    return user


@router.post("/{user_id}/approve", response_model=UserRead)
async def approve_user(
    user_id: int,
    session: SessionDep,
    _current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildAdminContext,
) -> User:
    stmt = (
        select(User)
        .join(GuildMembership, GuildMembership.user_id == User.id)
        .where(
            User.id == user_id,
            GuildMembership.guild_id == guild_context.guild_id,
        )
    )
    result = await session.exec(stmt)
    user = result.one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if not user.is_active:
        user.is_active = True
        user.updated_at = datetime.now(timezone.utc)
        session.add(user)
        await session.commit()
        await session.refresh(user)
    await initiatives_service.load_user_initiative_roles(session, [user])
    return user


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: int,
    session: SessionDep,
    current_admin: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildAdminContext,
) -> None:
    if user_id == SUPER_USER_ID:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot delete the super user")
    if user_id == current_admin.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="You cannot delete your own account")

    stmt = (
        select(User)
        .join(GuildMembership, GuildMembership.user_id == User.id)
        .where(
            User.id == user_id,
            GuildMembership.guild_id == guild_context.guild_id,
        )
    )
    result = await session.exec(stmt)
    user = result.one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    try:
        await initiatives_service.ensure_user_not_sole_pm(session, user_id=user.id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    await session.exec(delete(TaskAssignee).where(TaskAssignee.user_id == user_id))
    await session.delete(user)
    await session.commit()
