from typing import Annotated, List
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status, Response
from sqlmodel import select

from app.api.deps import require_roles
from app.db.session import get_admin_session
from sqlmodel.ext.asyncio.session import AsyncSession
from app.models.guild import Guild, GuildRole
from app.models.initiative import Initiative, InitiativeMember, InitiativeRole
from app.models.user import User, UserRole
from app.models.user_token import UserTokenPurpose
from app.schemas.user import UserRead, AccountDeletionResponse, ProjectBasic, UserPublic
from app.schemas.auth import VerificationSendResponse
from app.schemas.admin import (
    PlatformRoleUpdate,
    PlatformAdminCountResponse,
    AdminUserDeleteRequest,
    AdminDeletionEligibilityResponse,
    AdminGuildRoleUpdate,
    AdminInitiativeRoleUpdate,
    GuildBlockerInfo,
    InitiativeBlockerInfo,
)
from app.core.messages import AdminMessages, SettingsMessages
from app.services import user_tokens
from app.services import email as email_service
from app.services import initiatives as initiatives_service
from app.services import users as users_service
from app.services import guilds as guilds_service

router = APIRouter()

AdminUserDep = Annotated[User, Depends(require_roles(UserRole.admin))]
AdminSessionDep = Annotated[AsyncSession, Depends(get_admin_session)]


@router.get("/users", response_model=List[UserRead])
async def list_all_users(
    session: AdminSessionDep,
    _current_user: AdminUserDep,
) -> List[User]:
    """List all users in the platform (admin only)."""
    from app.services.users import SYSTEM_USER_EMAIL

    stmt = select(User).where(User.email != SYSTEM_USER_EMAIL).order_by(User.created_at.asc())
    result = await session.exec(stmt)
    users = result.all()
    await initiatives_service.load_user_initiative_roles(session, users)
    return users


@router.post("/users/{user_id}/reset-password", response_model=VerificationSendResponse)
async def trigger_password_reset(
    user_id: int,
    session: AdminSessionDep,
    _current_user: AdminUserDep,
) -> VerificationSendResponse:
    """Trigger a password reset email for a user (admin only)."""
    stmt = select(User).where(User.id == user_id)
    result = await session.exec(stmt)
    user = result.one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=AdminMessages.USER_NOT_FOUND)

    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=AdminMessages.CANNOT_RESET_INACTIVE)

    try:
        token = await user_tokens.create_token(
            session,
            user_id=user.id,
            purpose=UserTokenPurpose.password_reset,
            expires_minutes=60,
        )
        await email_service.send_password_reset_email(session, user, token)
    except email_service.EmailNotConfiguredError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=SettingsMessages.SMTP_INCOMPLETE
        ) from None
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc)
        ) from exc
    return VerificationSendResponse(status="sent")


@router.post("/users/{user_id}/reactivate", response_model=UserRead)
async def reactivate_user(
    user_id: int,
    session: AdminSessionDep,
    _current_user: AdminUserDep,
) -> User:
    """Reactivate a deactivated user account (admin only)."""
    stmt = select(User).where(User.id == user_id)
    result = await session.exec(stmt)
    user = result.one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=AdminMessages.USER_NOT_FOUND)

    if user.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=AdminMessages.USER_ALREADY_ACTIVE)

    user.is_active = True
    user.updated_at = datetime.now(timezone.utc)
    session.add(user)
    await session.commit()
    await session.refresh(user)
    await initiatives_service.load_user_initiative_roles(session, [user])
    return user


@router.get("/platform-admin-count", response_model=PlatformAdminCountResponse)
async def get_platform_admin_count(
    session: AdminSessionDep,
    _current_user: AdminUserDep,
) -> PlatformAdminCountResponse:
    """Get the count of platform admins (admin only)."""
    count = await users_service.count_platform_admins(session)
    return PlatformAdminCountResponse(count=count)


@router.patch("/users/{user_id}/platform-role", response_model=UserRead)
async def update_platform_role(
    user_id: int,
    payload: PlatformRoleUpdate,
    session: AdminSessionDep,
    current_user: AdminUserDep,
) -> User:
    """Update a user's platform role (admin only).

    Restrictions:
    - Cannot change your own role
    - Cannot demote the last platform admin
    """
    if user_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=AdminMessages.CANNOT_CHANGE_OWN_ROLE,
        )

    stmt = select(User).where(User.id == user_id).with_for_update()
    result = await session.exec(stmt)
    user = result.one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=AdminMessages.USER_NOT_FOUND)

    # Check if demoting the last admin (FOR UPDATE already acquired above)
    if user.role == UserRole.admin and payload.role != UserRole.admin:
        if await users_service.is_last_platform_admin(session, user_id, for_update=True):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=AdminMessages.CANNOT_DEMOTE_LAST_ADMIN,
            )

    user.role = payload.role
    user.updated_at = datetime.now(timezone.utc)
    session.add(user)
    await session.commit()
    await session.refresh(user)
    await initiatives_service.load_user_initiative_roles(session, [user])
    return user


@router.get("/users/{user_id}/deletion-eligibility", response_model=AdminDeletionEligibilityResponse)
async def check_user_deletion_eligibility(
    user_id: int,
    session: AdminSessionDep,
    current_user: AdminUserDep,
) -> AdminDeletionEligibilityResponse:
    """Check if a user can be deleted (admin only).

    Returns blockers, warnings, owned projects, and detailed blocker info
    with lists of members who could be promoted to resolve blockers.
    """
    if user_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=AdminMessages.USE_SELF_DELETION,
        )

    stmt = select(User).where(User.id == user_id)
    result = await session.exec(stmt)
    user = result.one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=AdminMessages.USER_NOT_FOUND)

    can_delete, blockers, warnings, owned_projects = await users_service.check_deletion_eligibility(
        session, user_id, admin_context=True
    )

    # Check if target is the last platform admin
    if user.role == UserRole.admin:
        if await users_service.is_last_platform_admin(session, user_id):
            blockers.append("User is the last platform admin. Promote another user first.")
            can_delete = False

    # Get detailed blocker info for guild and initiative blockers
    guild_blocker_details = await users_service.get_guild_blocker_details(session, user_id)
    initiative_blocker_details = await users_service.get_initiative_blocker_details(session, user_id)

    return AdminDeletionEligibilityResponse(
        can_delete=can_delete,
        blockers=blockers,
        warnings=warnings,
        owned_projects=[
            ProjectBasic(id=p.id, name=p.name, initiative_id=p.initiative_id)
            for p in owned_projects
        ],
        guild_blockers=[
            GuildBlockerInfo(
                guild_id=gb["guild_id"],
                guild_name=gb["guild_name"],
                other_members=[
                    UserPublic(
                        id=m.id,
                        email=m.email,
                        full_name=m.full_name,
                        avatar_base64=m.avatar_base64,
                        avatar_url=m.avatar_url,
                    )
                    for m in gb["other_members"]
                ],
            )
            for gb in guild_blocker_details
        ],
        initiative_blockers=[
            InitiativeBlockerInfo(
                initiative_id=ib["initiative_id"],
                initiative_name=ib["initiative_name"],
                guild_id=ib["guild_id"],
                other_members=[
                    UserPublic(
                        id=m.id,
                        email=m.email,
                        full_name=m.full_name,
                        avatar_base64=m.avatar_base64,
                        avatar_url=m.avatar_url,
                    )
                    for m in ib["other_members"]
                ],
            )
            for ib in initiative_blocker_details
        ],
    )


@router.delete("/users/{user_id}", response_model=AccountDeletionResponse)
async def delete_user(
    user_id: int,
    payload: AdminUserDeleteRequest,
    session: AdminSessionDep,
    current_user: AdminUserDep,
) -> AccountDeletionResponse:
    """Delete a user account (admin only).

    Supports soft delete (deactivation) or hard delete (permanent removal).

    Restrictions:
    - Cannot delete yourself (use /users/me/delete-account)
    - Cannot delete the last platform admin
    """
    if user_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=AdminMessages.CANNOT_DELETE_SELF,
        )

    stmt = select(User).where(User.id == user_id).with_for_update()
    result = await session.exec(stmt)
    user = result.one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=AdminMessages.USER_NOT_FOUND)

    # Check if target is the last platform admin
    if user.role == UserRole.admin:
        if await users_service.is_last_platform_admin(session, user_id, for_update=True):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=AdminMessages.CANNOT_DELETE_LAST_ADMIN,
            )

    # Check deletion eligibility
    can_delete, blockers, _, owned_projects = await users_service.check_deletion_eligibility(
        session, user_id, admin_context=True
    )

    if not can_delete:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=blockers[0] if blockers else AdminMessages.USER_CANNOT_BE_DELETED,
        )

    if payload.deletion_type == "soft":
        await users_service.soft_delete_user(session, user_id)
        return AccountDeletionResponse(
            success=True,
            deletion_type="soft",
            message=f"User {user.email} has been deactivated",
        )
    else:
        # Hard delete - validate project transfers
        if owned_projects:
            if not payload.project_transfers:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=AdminMessages.PROJECT_TRANSFERS_REQUIRED,
                )

            missing = [p.id for p in owned_projects if p.id not in payload.project_transfers]
            if missing:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Missing transfer recipients for projects: {missing}",
                )

        await users_service.hard_delete_user(
            session, user_id, payload.project_transfers or {}
        )
        return AccountDeletionResponse(
            success=True,
            deletion_type="hard",
            message=f"User {user.email} has been permanently deleted",
        )


@router.delete("/guilds/{guild_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def admin_delete_guild(
    guild_id: int,
    session: AdminSessionDep,
    _current_user: AdminUserDep,
) -> Response:
    """Delete a guild (platform admin only).

    This allows platform admins to delete any guild, even if they're not a member.
    All initiatives, projects, tasks, and memberships within the guild will be deleted.
    """
    stmt = select(Guild).where(Guild.id == guild_id)
    result = await session.exec(stmt)
    guild = result.one_or_none()
    if not guild:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=AdminMessages.GUILD_NOT_FOUND)

    await guilds_service.delete_guild(session, guild)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch(
    "/guilds/{guild_id}/members/{user_id}/role",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def admin_update_guild_member_role(
    guild_id: int,
    user_id: int,
    payload: AdminGuildRoleUpdate,
    session: AdminSessionDep,
    _current_user: AdminUserDep,
) -> Response:
    """Update a guild member's role (platform admin only).

    This allows platform admins to change guild member roles in any guild,
    even if they're not a member. Useful for resolving "last admin" blockers.

    Restrictions:
    - Cannot demote the last guild admin
    """
    # Check guild exists
    stmt = select(Guild).where(Guild.id == guild_id)
    result = await session.exec(stmt)
    guild = result.one_or_none()
    if not guild:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=AdminMessages.GUILD_NOT_FOUND)

    # Get target membership with lock
    target_membership = await guilds_service.get_membership(
        session, guild_id=guild_id, user_id=user_id, for_update=True
    )
    if target_membership is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=AdminMessages.USER_NOT_IN_GUILD)

    # Check if demoting the last guild admin
    if target_membership.role == GuildRole.admin and payload.role != GuildRole.admin:
        if await users_service.is_last_admin_of_guild(session, guild_id, user_id, for_update=True):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=AdminMessages.CANNOT_DEMOTE_LAST_GUILD_ADMIN,
            )

    target_membership.role = payload.role
    session.add(target_membership)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch(
    "/initiatives/{initiative_id}/members/{user_id}/role",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def admin_update_initiative_member_role(
    initiative_id: int,
    user_id: int,
    payload: AdminInitiativeRoleUpdate,
    session: AdminSessionDep,
    _current_user: AdminUserDep,
) -> Response:
    """Update an initiative member's role (platform admin only).

    This allows platform admins to change initiative member roles in any initiative,
    even if they're not a member. Useful for resolving "sole PM" blockers.

    Restrictions:
    - Cannot demote the last project manager
    """
    # Check initiative exists
    stmt = select(Initiative).where(Initiative.id == initiative_id)
    result = await session.exec(stmt)
    initiative = result.one_or_none()
    if not initiative:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=AdminMessages.INITIATIVE_NOT_FOUND)

    # Get target membership with lock
    membership_stmt = (
        select(InitiativeMember)
        .where(
            InitiativeMember.initiative_id == initiative_id,
            InitiativeMember.user_id == user_id,
        )
        .with_for_update()
    )
    membership_result = await session.exec(membership_stmt)
    target_membership = membership_result.one_or_none()
    if target_membership is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=AdminMessages.USER_NOT_IN_INITIATIVE)

    # Check if demoting the last PM
    if target_membership.role == InitiativeRole.project_manager and payload.role != InitiativeRole.project_manager:
        try:
            await initiatives_service.ensure_managers_remain(
                session,
                initiative_id=initiative_id,
                excluded_user_ids=[user_id],
            )
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=AdminMessages.CANNOT_DEMOTE_LAST_PM,
            )

    target_membership.role = payload.role
    session.add(target_membership)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
