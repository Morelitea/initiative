from datetime import datetime, timezone
from typing import Annotated, List, Optional
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func
from sqlmodel import select

from app.api.deps import (
    RLSSessionDep,
    SessionDep,
    UserSessionDep,
    get_current_active_user,
    get_guild_membership,
    GuildContext,
    require_guild_roles,
)
from app.core.security import get_password_hash, verify_password
from app.db.session import get_admin_session, reapply_rls_context, set_rls_context
from sqlmodel.ext.asyncio.session import AsyncSession
from app.models.guild import GuildRole, GuildMembership
from app.models.initiative import InitiativeMember
from app.models.user import User, UserRole
from app.schemas.user import (
    UserCreate,
    UserGuildMember,
    UserRead,
    UserSelfUpdate,
    UserUpdate,
    AccountDeletionRequest,
    AccountDeletionResponse,
    DeletionEligibilityResponse,
    ProjectBasic,
    UserPublic,
)
from app.schemas.api_key import (
    ApiKeyCreateRequest,
    ApiKeyCreateResponse,
    ApiKeyListResponse,
)
from app.schemas.stats import UserStatsResponse
from app.core.messages import AuthMessages, UserMessages
from app.services import notifications as notifications_service
from app.services import initiatives as initiatives_service
from app.services import guilds as guilds_service
from app.services import users as users_service
from app.services import api_keys as api_keys_service
from app.services import stats_service

router = APIRouter()

AdminSessionDep = Annotated[AsyncSession, Depends(get_admin_session)]
GuildContextDep = Annotated[GuildContext, Depends(get_guild_membership)]
GuildAdminContext = Annotated[GuildContext, Depends(require_guild_roles(GuildRole.admin))]

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
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=UserMessages.INVALID_TIMEZONE)
    return cleaned


def _normalize_notification_time(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    if not TIME_PATTERN.match(cleaned):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=UserMessages.INVALID_TIME_FORMAT)
    return cleaned


def _normalize_week_starts_on(value: int | str | None) -> int | None:
    if value is None:
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=UserMessages.INVALID_WEEK_START,
        )
    if number < 0 or number > 6:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=UserMessages.INVALID_WEEK_START,
        )
    return number


@router.get("/me", response_model=UserRead)
async def read_users_me(session: UserSessionDep, current_user: Annotated[User, Depends(get_current_active_user)]) -> User:
    await initiatives_service.load_user_initiative_roles(session, [current_user])
    return current_user


@router.get("/me/stats", response_model=UserStatsResponse)
async def get_user_stats(
    session: UserSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_id: Optional[int] = Query(default=None, description="Optional guild ID to filter stats"),
    days: int = Query(default=90, ge=1, le=365, description="Number of days to analyze"),
) -> UserStatsResponse:
    """Get comprehensive statistics for the current user."""
    stats = await stats_service.get_user_stats(
        session,
        user=current_user,
        guild_id=guild_id,
        days=days,
    )
    return stats


@router.get("/", response_model=List[UserGuildMember])
async def list_users(
    session: RLSSessionDep,
    _current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> List[UserGuildMember]:
    stmt = (
        select(User, GuildMembership.role, GuildMembership.oidc_managed)
        .join(GuildMembership, GuildMembership.user_id == User.id)
        .where(GuildMembership.guild_id == guild_context.guild_id)
        .order_by(User.created_at.asc())
    )
    result = await session.exec(stmt)
    rows = result.all()
    users = [row[0] for row in rows]
    await initiatives_service.load_user_initiative_roles(session, users)

    # Build response with guild_role and oidc_managed
    response = []
    for user, guild_role, oidc_managed in rows:
        member = UserGuildMember.model_validate(user)
        member.guild_role = guild_role.value
        member.oidc_managed = oidc_managed
        # Copy initiative_roles from loaded user
        member.initiative_roles = getattr(user, "initiative_roles", [])
        response.append(member)
    return response


@router.post("/", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def create_user(
    user_in: UserCreate,
    session: SessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildAdminContext,
) -> User:
    await set_rls_context(
        session,
        user_id=current_user.id,
        guild_id=guild_context.guild_id,
        guild_role="admin",
        is_superadmin=(current_user.role == UserRole.admin),
    )

    normalized_email = user_in.email.lower().strip()
    statement = select(User).where(func.lower(User.email) == normalized_email)
    result = await session.exec(statement)
    if result.one_or_none():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=UserMessages.EMAIL_ALREADY_REGISTERED)

    guild_id = guild_context.guild_id

    user = User(
        email=normalized_email,
        full_name=user_in.full_name,
        hashed_password=get_password_hash(user_in.password),
        role=user_in.role,
        email_verified=True,
    )
    session.add(user)
    await session.flush()
    # Platform role and guild role are independent - new users join as guild members
    await guilds_service.ensure_membership(
        session,
        guild_id=guild_id,
        user_id=user.id,
        role=GuildRole.member,
    )
    await session.commit()
    await reapply_rls_context(session)
    await session.refresh(user)
    await initiatives_service.load_user_initiative_roles(session, [user])
    return user


@router.patch("/me", response_model=UserRead)
async def update_users_me(
    user_in: UserSelfUpdate,
    session: UserSessionDep,
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
    if "week_starts_on" in update_data:
        normalized_week_start = _normalize_week_starts_on(update_data["week_starts_on"])
        if normalized_week_start is not None:
            current_user.week_starts_on = normalized_week_start
    if "timezone" in update_data:
        normalized_timezone = _normalize_timezone(update_data["timezone"])
        if normalized_timezone:
            current_user.timezone = normalized_timezone
    if "overdue_notification_time" in update_data:
        normalized_time = _normalize_notification_time(update_data["overdue_notification_time"])
        if normalized_time:
            current_user.overdue_notification_time = normalized_time
    for field in [
        "email_initiative_addition",
        "email_task_assignment",
        "email_project_added",
        "email_overdue_tasks",
        "email_mentions",
        "push_initiative_addition",
        "push_task_assignment",
        "push_project_added",
        "push_overdue_tasks",
        "push_mentions",
    ]:
        if field in update_data:
            new_value = bool(update_data[field])
            setattr(current_user, field, new_value)
            if field == "email_task_assignment" and not new_value:
                await notifications_service.clear_task_assignment_queue_for_user(session, current_user.id)
    if "color_theme" in update_data:
        current_user.color_theme = update_data["color_theme"]
    if "locale" in update_data:
        current_user.locale = update_data["locale"]

    current_user.updated_at = datetime.now(timezone.utc)
    session.add(current_user)
    await session.commit()
    await reapply_rls_context(session)
    await session.refresh(current_user)
    await initiatives_service.load_user_initiative_roles(session, [current_user])
    return current_user


@router.patch("/{user_id}", response_model=UserRead)
async def update_user(
    user_id: int,
    user_in: UserUpdate,
    session: SessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildAdminContext,
) -> User:
    await set_rls_context(
        session,
        user_id=current_user.id,
        guild_id=guild_context.guild_id,
        guild_role="admin",
        is_superadmin=(current_user.role == UserRole.admin),
    )

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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=AuthMessages.USER_NOT_FOUND)

    update_data = user_in.dict(exclude_unset=True)
    # Platform role changes are not allowed via this endpoint - use /admin/users/{id}/platform-role
    if "role" in update_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=UserMessages.PLATFORM_ROLE_WRONG_ENDPOINT,
        )
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
        if field == "week_starts_on":
            normalized_week_start = _normalize_week_starts_on(value)
            if normalized_week_start is not None:
                setattr(user, field, normalized_week_start)
            continue
        if field == "email_task_assignment" and value is False:
            await notifications_service.clear_task_assignment_queue_for_user(session, user.id)
        setattr(user, field, value)
    user.updated_at = datetime.now(timezone.utc)

    session.add(user)
    await session.commit()
    await reapply_rls_context(session)
    await session.refresh(user)
    await initiatives_service.load_user_initiative_roles(session, [user])
    return user


@router.post("/{user_id}/approve", response_model=UserRead)
async def approve_user(
    user_id: int,
    session: SessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildAdminContext,
) -> User:
    await set_rls_context(
        session,
        user_id=current_user.id,
        guild_id=guild_context.guild_id,
        guild_role="admin",
        is_superadmin=(current_user.role == UserRole.admin),
    )

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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=AuthMessages.USER_NOT_FOUND)

    if not user.is_active:
        user.is_active = True
        user.updated_at = datetime.now(timezone.utc)
        session.add(user)
        await session.commit()
        await reapply_rls_context(session)
        await session.refresh(user)
    await initiatives_service.load_user_initiative_roles(session, [user])
    return user


@router.get("/me/deletion-eligibility", response_model=DeletionEligibilityResponse)
async def check_deletion_eligibility(
    session: AdminSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> DeletionEligibilityResponse:
    """Check if the current user can be deleted and what blockers exist."""
    can_delete, blockers, warnings, owned_projects = await users_service.check_deletion_eligibility(
        session, current_user.id
    )

    project_basics = [
        ProjectBasic(id=project.id, name=project.name, initiative_id=project.initiative_id)
        for project in owned_projects
    ]

    last_admin_guilds = await users_service.is_last_guild_admin(session, current_user.id)

    return DeletionEligibilityResponse(
        can_delete=can_delete,
        blockers=blockers,
        warnings=warnings,
        owned_projects=project_basics,
        last_admin_guilds=last_admin_guilds,
    )


@router.get("/me/initiative-members/{initiative_id}", response_model=List[UserPublic])
async def get_my_initiative_members(
    initiative_id: int,
    session: AdminSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> List[User]:
    """List members of an initiative the current user belongs to.

    Uses AdminSession to bypass RLS so users can see members across guilds
    when selecting project transfer targets during account deletion.
    """
    # Verify the current user is a member of this initiative
    membership = await initiatives_service.get_initiative_membership(
        session, initiative_id=initiative_id, user_id=current_user.id,
    )
    if not membership:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    stmt = (
        select(User)
        .join(InitiativeMember, InitiativeMember.user_id == User.id)
        .where(InitiativeMember.initiative_id == initiative_id)
        .order_by(User.full_name, User.email)
    )
    result = await session.exec(stmt)
    return result.all()


@router.post("/me/delete-account", response_model=AccountDeletionResponse)
async def delete_own_account(
    request: AccountDeletionRequest,
    session: AdminSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> AccountDeletionResponse:
    """Delete or deactivate the current user's account."""
    # Prevent last platform admin deletion (use FOR UPDATE to prevent race condition)
    if await users_service.is_last_platform_admin(session, current_user.id, for_update=True):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=UserMessages.CANNOT_DELETE_LAST_ADMIN,
        )

    # Verify password
    if not verify_password(request.password, current_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=UserMessages.INVALID_PASSWORD,
        )

    # Check confirmation text
    if request.confirmation_text != "DELETE MY ACCOUNT":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=UserMessages.CONFIRMATION_MISMATCH,
        )

    # Check deletion eligibility (includes last admin and sole PM checks)
    can_delete, blockers, _, owned_projects = await users_service.check_deletion_eligibility(
        session, current_user.id
    )

    if not can_delete:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot delete account: {'; '.join(blockers)}",
        )

    # Perform deletion based on type
    if request.deletion_type == "soft":
        await users_service.soft_delete_user(session, current_user.id)
        return AccountDeletionResponse(
            success=True,
            deletion_type="soft",
            message="Your account has been deactivated. Contact an administrator to reactivate.",
        )
    else:  # hard delete
        # Validate project transfers
        if owned_projects:
            if not request.project_transfers:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=UserMessages.PROJECT_TRANSFERS_REQUIRED,
                )

            owned_project_ids = {project.id for project in owned_projects}
            transfer_ids = set(request.project_transfers.keys())

            if owned_project_ids != transfer_ids:
                missing = owned_project_ids - transfer_ids
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Missing transfer recipients for projects: {missing}",
                )

        await users_service.hard_delete_user(
            session,
            current_user.id,
            request.project_transfers or {},
        )

        return AccountDeletionResponse(
            success=True,
            deletion_type="hard",
            message="Your account has been permanently deleted.",
        )


@router.get("/me/api-keys", response_model=ApiKeyListResponse)
async def list_my_api_keys(
    session: SessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> ApiKeyListResponse:
    """List all API keys for the current user."""
    keys = await api_keys_service.list_api_keys(session, user=current_user)
    return ApiKeyListResponse(keys=keys)


@router.post("/me/api-keys", response_model=ApiKeyCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_my_api_key(
    payload: ApiKeyCreateRequest,
    session: SessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> ApiKeyCreateResponse:
    """Create a new API key for the current user."""
    secret, api_key = await api_keys_service.create_api_key(
        session,
        user=current_user,
        name=payload.name,
        expires_at=payload.expires_at,
    )
    return ApiKeyCreateResponse(api_key=api_key, secret=secret)


@router.delete("/me/api-keys/{api_key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_my_api_key(
    api_key_id: int,
    session: SessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> None:
    """Delete an API key for the current user."""
    deleted = await api_keys_service.delete_api_key(session, user=current_user, api_key_id=api_key_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=UserMessages.API_KEY_NOT_FOUND)



@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: int,
    session: SessionDep,
    current_admin: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildAdminContext,
) -> None:
    await set_rls_context(
        session,
        user_id=current_admin.id,
        guild_id=guild_context.guild_id,
        guild_role="admin",
        is_superadmin=(current_admin.role == UserRole.admin),
    )

    # Use FOR UPDATE to prevent race condition when checking last admin
    if await users_service.is_last_platform_admin(session, user_id, for_update=True):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=UserMessages.CANNOT_REMOVE_LAST_ADMIN)
    if user_id == current_admin.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=UserMessages.CANNOT_DELETE_SELF)

    stmt = (
        select(GuildMembership)
        .where(
            GuildMembership.user_id == user_id,
            GuildMembership.guild_id == guild_context.guild_id,
        )
    )
    result = await session.exec(stmt)
    membership = result.one_or_none()
    if not membership:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=UserMessages.NOT_IN_GUILD)

    try:
        await initiatives_service.ensure_user_not_sole_pm(
            session,
            user_id=user_id,
            guild_id=guild_context.guild_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    await initiatives_service.remove_user_from_guild_initiatives(
        session,
        guild_id=guild_context.guild_id,
        user_id=user_id,
    )

    await session.delete(membership)
    await session.commit()
