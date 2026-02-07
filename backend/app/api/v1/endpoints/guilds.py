from __future__ import annotations

from typing import Annotated, List

from fastapi import APIRouter, Depends, HTTPException, status, Response

from app.api.deps import SessionDep, UserSessionDep, get_current_active_user
from app.core.config import settings
from app.db.session import get_admin_session, reapply_rls_context, set_rls_context
from app.models.guild import GuildRole, GuildMembership, Guild
from app.models.user import User, UserRole
from app.schemas.guild import (
    GuildCreate,
    GuildMembershipUpdate,
    GuildRead,
    GuildInviteAcceptRequest,
    GuildInviteCreate,
    GuildInviteRead,
    GuildInviteStatus,
    GuildOrderUpdate,
    GuildUpdate,
    LeaveGuildEligibilityResponse,
)
from app.services import guilds as guilds_service
from app.services import initiatives as initiatives_service
from sqlmodel.ext.asyncio.session import AsyncSession

AdminSessionDep = Annotated[AsyncSession, Depends(get_admin_session)]

router = APIRouter()


def _serialize_guild(guild: Guild, membership: GuildMembership) -> GuildRead:
    return GuildRead(
        id=guild.id,
        name=guild.name,
        description=guild.description,
        icon_base64=guild.icon_base64,
        created_at=guild.created_at,
        updated_at=guild.updated_at,
        role=membership.role,
        position=membership.position,
    )


async def _ensure_guild_admin(
    session: SessionDep,
    *,
    guild_id: int,
    user_id: int,
    is_superadmin: bool = False,
) -> GuildMembership:
    # Set minimal RLS context so the guild_memberships query succeeds.
    # Full context is set by _set_guild_admin_rls after validation.
    await set_rls_context(session, user_id=user_id, is_superadmin=is_superadmin)
    membership = await guilds_service.get_membership(session, guild_id=guild_id, user_id=user_id)
    if membership is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Guild access denied")
    if membership.role != GuildRole.admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Guild admin role required")
    return membership


async def _set_guild_admin_rls(
    session: AsyncSession,
    *,
    guild_id: int,
    user: User,
) -> None:
    """Set RLS context after _ensure_guild_admin has validated the user's role."""
    await set_rls_context(
        session,
        user_id=user.id,
        guild_id=guild_id,
        guild_role="admin",
        is_superadmin=(user.role == UserRole.admin),
    )


@router.get("/", response_model=List[GuildRead])
async def list_guilds(session: UserSessionDep, current_user: Annotated[User, Depends(get_current_active_user)]) -> List[GuildRead]:
    memberships = await guilds_service.list_memberships(session, user_id=current_user.id)
    payloads: List[GuildRead] = []
    for guild, membership in memberships:
        payloads.append(_serialize_guild(guild, membership))
    return payloads


@router.put("/order", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def reorder_guilds(
    payload: GuildOrderUpdate,
    session: UserSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> Response:
    await guilds_service.reorder_memberships(
        session,
        user_id=current_user.id,
        ordered_guild_ids=payload.guild_ids,
    )
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/invite/{code}", response_model=GuildInviteStatus)
async def get_invite_status(
    code: str,
    session: AdminSessionDep,
) -> GuildInviteStatus:
    invite, guild, is_valid, reason = await guilds_service.describe_invite_code(session, code=code)
    return GuildInviteStatus(
        code=code,
        guild_id=guild.id if guild else None,
        guild_name=guild.name if guild else None,
        is_valid=is_valid,
        reason=reason,
        expires_at=invite.expires_at if invite else None,
        max_uses=invite.max_uses if invite else None,
        uses=invite.uses if invite else None,
    )


@router.post("/", response_model=GuildRead, status_code=status.HTTP_201_CREATED)
async def create_guild(
    guild_in: GuildCreate,
    session: AdminSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> GuildRead:
    """Create a new guild. Uses admin session because the guild doesn't exist
    yet — no guild context or membership exists for RLS to match against."""
    if settings.DISABLE_GUILD_CREATION and current_user.role != UserRole.admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Guild creation is disabled")
    name = guild_in.name.strip()
    if not name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Guild name is required")

    guild = await guilds_service.create_guild(
        session,
        name=name,
        description=guild_in.description,
        icon_base64=guild_in.icon_base64,
        creator=current_user,
    )
    await initiatives_service.ensure_default_initiative(session, current_user, guild_id=guild.id)
    await session.commit()
    membership = await guilds_service.get_membership(session, guild_id=guild.id, user_id=current_user.id)
    if not membership:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to create guild membership")
    return _serialize_guild(guild, membership)


@router.get("/{guild_id}/invites", response_model=List[GuildInviteRead])
async def list_guild_invites(
    guild_id: int,
    session: SessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> List[GuildInviteRead]:
    await _ensure_guild_admin(session, guild_id=guild_id, user_id=current_user.id, is_superadmin=(current_user.role == UserRole.admin))
    await _set_guild_admin_rls(session, guild_id=guild_id, user=current_user)
    invites = await guilds_service.list_guild_invites(session, guild_id=guild_id)
    return [GuildInviteRead.model_validate(invite) for invite in invites]


@router.patch("/{guild_id}", response_model=GuildRead)
async def update_guild(
    guild_id: int,
    updates: GuildUpdate,
    session: SessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> GuildRead:
    membership = await _ensure_guild_admin(session, guild_id=guild_id, user_id=current_user.id, is_superadmin=(current_user.role == UserRole.admin))
    await _set_guild_admin_rls(session, guild_id=guild_id, user=current_user)
    icon_provided = "icon_base64" in updates.model_fields_set
    guild = await guilds_service.update_guild(
        session,
        guild_id=guild_id,
        name=updates.name,
        description=updates.description,
        icon_base64=updates.icon_base64,
        icon_provided=icon_provided,
    )
    await session.commit()
    return _serialize_guild(guild, membership)


@router.delete("/{guild_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def delete_guild(
    guild_id: int,
    session: SessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> Response:
    await _ensure_guild_admin(session, guild_id=guild_id, user_id=current_user.id, is_superadmin=(current_user.role == UserRole.admin))
    await _set_guild_admin_rls(session, guild_id=guild_id, user=current_user)
    guild = await guilds_service.get_guild(session, guild_id=guild_id)
    await guilds_service.delete_guild(session, guild)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{guild_id}/invites", response_model=GuildInviteRead, status_code=status.HTTP_201_CREATED)
async def create_guild_invite(
    guild_id: int,
    invite_in: GuildInviteCreate,
    session: SessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> GuildInviteRead:
    await _ensure_guild_admin(session, guild_id=guild_id, user_id=current_user.id, is_superadmin=(current_user.role == UserRole.admin))
    await _set_guild_admin_rls(session, guild_id=guild_id, user=current_user)
    invite = await guilds_service.create_guild_invite(
        session,
        guild_id=guild_id,
        created_by_user_id=current_user.id,
        expires_at=invite_in.expires_at,
        max_uses=invite_in.max_uses,
        invitee_email=invite_in.invitee_email,
    )
    await session.commit()
    return GuildInviteRead.model_validate(invite)


@router.delete(
    "/{guild_id}/invites/{invite_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_guild_invite(
    guild_id: int,
    invite_id: int,
    session: SessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> Response:
    await _ensure_guild_admin(session, guild_id=guild_id, user_id=current_user.id, is_superadmin=(current_user.role == UserRole.admin))
    await _set_guild_admin_rls(session, guild_id=guild_id, user=current_user)
    await guilds_service.delete_guild_invite(session, guild_id=guild_id, invite_id=invite_id)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/invite/accept", response_model=GuildRead)
async def accept_invite(
    payload: GuildInviteAcceptRequest,
    session: AdminSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> GuildRead:
    """Accept a guild invite. Uses admin session because the user doesn't
    belong to the guild yet — the invite code is the authorization."""
    try:
        guild = await guilds_service.redeem_invite_for_user(session, code=payload.code, user=current_user)
    except guilds_service.GuildInviteError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    await session.commit()
    await reapply_rls_context(session)
    membership = await guilds_service.get_membership(session, guild_id=guild.id, user_id=current_user.id)
    if not membership:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Guild membership missing")
    return _serialize_guild(guild, membership)


@router.patch("/{guild_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def update_guild_membership(
    guild_id: int,
    user_id: int,
    payload: GuildMembershipUpdate,
    session: SessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> Response:
    """Update a user's guild membership role. Guild admin only.

    Restrictions:
    - Cannot change your own role
    - Cannot demote the last guild admin
    """
    await _ensure_guild_admin(session, guild_id=guild_id, user_id=current_user.id, is_superadmin=(current_user.role == UserRole.admin))
    await _set_guild_admin_rls(session, guild_id=guild_id, user=current_user)

    if user_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot change your own guild role",
        )

    target_membership = await guilds_service.get_membership(session, guild_id=guild_id, user_id=user_id, for_update=True)
    if target_membership is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found in guild")

    # Check if demoting the last guild admin (FOR UPDATE already acquired above)
    if target_membership.role == GuildRole.admin and payload.role != GuildRole.admin:
        from app.services.users import is_last_admin_of_guild
        if await is_last_admin_of_guild(session, guild_id, user_id, for_update=True):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot demote the last guild admin",
            )

    target_membership.role = payload.role
    session.add(target_membership)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{guild_id}/leave/eligibility", response_model=LeaveGuildEligibilityResponse)
async def check_leave_eligibility(
    guild_id: int,
    session: UserSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> LeaveGuildEligibilityResponse:
    """Check if the current user can leave a guild.

    Returns information about blockers:
    - is_last_admin: User is the last admin of the guild
    - sole_pm_initiatives: List of initiative names where user is the sole PM
    """
    membership = await guilds_service.get_membership(session, guild_id=guild_id, user_id=current_user.id)
    if membership is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not a member of this guild")

    from app.services.users import is_last_admin_of_guild

    is_last_admin = await is_last_admin_of_guild(session, guild_id, current_user.id)

    sole_pm_initiatives = await initiatives_service.initiatives_requiring_new_pm(
        session, current_user.id, guild_id=guild_id
    )
    sole_pm_names = [initiative.name for initiative in sole_pm_initiatives]

    can_leave = not is_last_admin and len(sole_pm_names) == 0

    return LeaveGuildEligibilityResponse(
        can_leave=can_leave,
        is_last_admin=is_last_admin,
        sole_pm_initiatives=sole_pm_names,
    )


@router.delete("/{guild_id}/leave", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def leave_guild(
    guild_id: int,
    session: UserSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> Response:
    """Leave a guild.

    Restrictions:
    - Cannot leave if you are the last admin of the guild
    - Cannot leave if you are the sole PM of any initiative in the guild
    """
    membership = await guilds_service.get_membership(session, guild_id=guild_id, user_id=current_user.id)
    if membership is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not a member of this guild")

    from app.services.users import is_last_admin_of_guild

    if await is_last_admin_of_guild(session, guild_id, current_user.id, for_update=True):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot leave guild: you are the last admin. Promote another user to admin first.",
        )

    sole_pm_initiatives = await initiatives_service.initiatives_requiring_new_pm(
        session, current_user.id, guild_id=guild_id
    )
    if sole_pm_initiatives:
        names = ", ".join(initiative.name for initiative in sole_pm_initiatives)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot leave guild: you are the sole project manager of: {names}. Promote another member first.",
        )

    await guilds_service.remove_user_from_guild(session, guild_id=guild_id, user_id=current_user.id)

    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
