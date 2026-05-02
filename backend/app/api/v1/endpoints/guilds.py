from __future__ import annotations

from typing import Annotated, List

from fastapi import APIRouter, Depends, HTTPException, status, Response

from app.api.deps import SessionDep, UserSessionDep, get_current_active_user
from app.core.config import settings
from app.core.messages import AdvancedToolMessages, GuildMessages
from app.core.security import create_advanced_tool_handoff_token
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
    LeaveGuildRequest,
)
from app.schemas.user import GuildRemovalProjectInfo, UserPublic
from app.schemas.initiative import AdvancedToolHandoffResponse
from app.services import guilds as guilds_service
from app.services import initiatives as initiatives_service
from app.services import rls as rls_service
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

AdminSessionDep = Annotated[AsyncSession, Depends(get_admin_session)]

router = APIRouter()


def _serialize_guild(
    guild: Guild,
    membership: GuildMembership,
    retention_days: int | None = None,
) -> GuildRead:
    return GuildRead(
        id=guild.id,
        name=guild.name,
        description=guild.description,
        icon_base64=guild.icon_base64,
        created_at=guild.created_at,
        updated_at=guild.updated_at,
        role=membership.role,
        position=membership.position,
        retention_days=retention_days,
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
    membership = await rls_service.require_guild_membership(
        session, guild_id=guild_id, user_id=user_id,
    )
    rls_service.require_guild_admin(membership.role)
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
    for guild, membership, retention_days in memberships:
        payloads.append(_serialize_guild(guild, membership, retention_days=retention_days))
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
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=GuildMessages.GUILD_CREATION_DISABLED)
    name = guild_in.name.strip()
    if not name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=GuildMessages.GUILD_NAME_REQUIRED)

    guild = await guilds_service.create_guild(
        session,
        name=name,
        description=guild_in.description,
        icon_base64=guild_in.icon_base64,
        creator=current_user,
    )
    await initiatives_service.ensure_default_initiative(session, current_user, guild_id=guild.id)
    await session.commit()
    await reapply_rls_context(session)
    membership = await guilds_service.get_membership(session, guild_id=guild.id, user_id=current_user.id)
    if not membership:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=GuildMessages.GUILD_MEMBERSHIP_CREATE_FAILED)
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
    retention_days_provided = "retention_days" in updates.model_fields_set
    guild = await guilds_service.update_guild(
        session,
        guild_id=guild_id,
        name=updates.name,
        description=updates.description,
        icon_base64=updates.icon_base64,
        icon_provided=icon_provided,
        retention_days=updates.retention_days,
        retention_days_provided=retention_days_provided,
    )
    await session.commit()
    retention_days = await guilds_service.get_guild_retention_days(session, guild_id)
    return _serialize_guild(guild, membership, retention_days=retention_days)


# ---------------------------------------------------------------------------
# Advanced tool handoff (guild scope) — admin-only embed.
# ---------------------------------------------------------------------------


@router.post(
    "/{guild_id}/advanced-tool/handoff",
    response_model=AdvancedToolHandoffResponse,
)
async def create_guild_advanced_tool_handoff(
    guild_id: int,
    session: SessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> AdvancedToolHandoffResponse:
    """Mint a short-lived JWT for the guild-scoped advanced-tool iframe.

    Authorization gates (all enforced here, not in the receiving embed):

      1. Deployment must have ADVANCED_TOOL_URL configured.
      2. Caller must be a guild admin (or platform superadmin).

    The returned token has ``scope=guild`` and intentionally omits
    ``initiative_id``. The receiving service must trust the JWT's scope
    claim — the URL query param is a hint only, useful for routing on the
    embed side, not enough to authorize on its own.
    """
    if not settings.ADVANCED_TOOL_URL:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=AdvancedToolMessages.NOT_CONFIGURED)

    is_superadmin = current_user.role == UserRole.admin
    await _ensure_guild_admin(
        session,
        guild_id=guild_id,
        user_id=current_user.id,
        is_superadmin=is_superadmin,
    )

    token, expires_in_seconds = create_advanced_tool_handoff_token(
        user_id=current_user.id,
        guild_id=guild_id,
        guild_role=GuildRole.admin.value,
        # Guild admins are managers by definition for this scope.
        is_manager=True,
        # Admins always have create permission at the guild level.
        can_create=True,
        scope="guild",
    )

    return AdvancedToolHandoffResponse(
        handoff_token=token,
        expires_in_seconds=expires_in_seconds,
        iframe_url=settings.ADVANCED_TOOL_URL,
        scope="guild",
        initiative_id=None,
    )


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
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=GuildMessages.GUILD_MEMBERSHIP_MISSING)
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
            detail=GuildMessages.CANNOT_CHANGE_OWN_ROLE,
        )

    target_membership = await guilds_service.get_membership(session, guild_id=guild_id, user_id=user_id, for_update=True)
    if target_membership is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=GuildMessages.USER_NOT_FOUND_IN_GUILD)

    # Check if demoting the last guild admin (FOR UPDATE already acquired above)
    if target_membership.role == GuildRole.admin and payload.role != GuildRole.admin:
        from app.services.users import is_last_admin_of_guild
        if await is_last_admin_of_guild(session, guild_id, user_id, for_update=True):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=GuildMessages.CANNOT_DEMOTE_LAST_ADMIN,
            )

    target_membership.role = payload.role
    session.add(target_membership)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def _fetch_pm_candidates(
    session: AsyncSession,
    *,
    initiative_id: int,
    excluded_user_id: int,
) -> list[UserPublic]:
    """Active project-manager candidates for ``initiative_id``, with
    ``excluded_user_id`` filtered out.

    Project ownership only requires initiative membership in principle,
    but for transfer-on-departure UX we restrict the picker to
    initiative managers — they're the role that actually administers
    the project, so handing them the row matches the user's intent and
    keeps them empowered to make further changes (reassign, rename,
    archive). Non-manager members can still appear via direct
    ``ProjectPermission`` rows; this helper just narrows the picker.
    """
    from app.models.initiative import InitiativeMember, InitiativeRoleModel
    from app.models.user import UserStatus

    stmt = (
        select(User)
        .join(InitiativeMember, InitiativeMember.user_id == User.id)
        .join(InitiativeRoleModel, InitiativeRoleModel.id == InitiativeMember.role_id)
        .where(
            InitiativeMember.initiative_id == initiative_id,
            InitiativeRoleModel.is_manager.is_(True),
            User.status == UserStatus.active,
            User.id != excluded_user_id,
        )
        .order_by(User.full_name, User.id)
    )
    result = await session.exec(stmt)
    return [UserPublic.model_validate(u) for u in result.all()]


@router.get("/{guild_id}/leave/eligibility", response_model=LeaveGuildEligibilityResponse)
async def check_leave_eligibility(
    guild_id: int,
    session: UserSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> LeaveGuildEligibilityResponse:
    """Check if the current user can leave a guild.

    Returns information about blockers:
    - is_last_admin: User is the last admin of the guild
    - sole_pm_initiatives: Initiatives in this guild where the user is the sole PM
    - owned_projects: Projects in this guild whose ``owner_id`` is the
      user, with project-manager candidates per project. The leave
      endpoint requires a transfer-or-delete disposition for each —
      without one, the project's RLS gate (``InitiativeMember``) no
      longer matches on leave, and there's no DAC bypass for guild
      admins, so the row would be unreachable.
    """
    membership = await guilds_service.get_membership(session, guild_id=guild_id, user_id=current_user.id)
    if membership is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=GuildMessages.NOT_GUILD_MEMBER)

    from app.services.users import get_owned_projects_in_guild, is_last_admin_of_guild

    is_last_admin = await is_last_admin_of_guild(session, guild_id, current_user.id)

    sole_pm_initiatives = await initiatives_service.initiatives_requiring_new_pm(
        session, current_user.id, guild_id=guild_id
    )
    sole_pm_names = [initiative.name for initiative in sole_pm_initiatives]

    owned_projects = await get_owned_projects_in_guild(session, current_user.id, guild_id)
    owned_project_infos: list[GuildRemovalProjectInfo] = []
    candidate_cache: dict[int, list[UserPublic]] = {}
    for project in owned_projects:
        candidates = candidate_cache.get(project.initiative_id)
        if candidates is None:
            candidates = await _fetch_pm_candidates(
                session,
                initiative_id=project.initiative_id,
                excluded_user_id=current_user.id,
            )
            candidate_cache[project.initiative_id] = candidates
        owned_project_infos.append(
            GuildRemovalProjectInfo(
                id=project.id,
                name=project.name,
                initiative_id=project.initiative_id,
                candidates=candidates,
            )
        )

    can_leave = (
        not is_last_admin
        and len(sole_pm_names) == 0
        # ``owned_projects`` is not itself a hard blocker — leave can
        # proceed if the client supplies a disposition for every entry.
        # ``can_leave`` here reflects "can leave with no extra input";
        # the leave endpoint enforces the transfer/delete rules.
        and len(owned_project_infos) == 0
    )

    return LeaveGuildEligibilityResponse(
        can_leave=can_leave,
        is_last_admin=is_last_admin,
        sole_pm_initiatives=sole_pm_names,
        owned_projects=owned_project_infos,
    )


@router.delete("/{guild_id}/leave", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def leave_guild(
    guild_id: int,
    session: UserSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    body: LeaveGuildRequest | None = None,
) -> Response:
    """Leave a guild.

    Restrictions:
    - Cannot leave if you are the last admin of the guild
    - Cannot leave if you are the sole PM of any initiative in the guild
    - Cannot leave while you own projects in the guild unless the body
      supplies ``project_transfers`` covering every owned project.
    """
    membership = await guilds_service.get_membership(session, guild_id=guild_id, user_id=current_user.id)
    if membership is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=GuildMessages.NOT_GUILD_MEMBER)

    # ``UserSessionDep`` only sets the user_id; transferring or
    # soft-deleting projects below issues UPDATEs against the
    # guild-scoped ``projects`` table, whose ``guild_update`` RLS
    # policy requires ``current_guild_id`` to match the row. Now that
    # we've confirmed the user is a member of this guild, set the
    # full RLS context so the UPDATEs aren't filtered to zero rows
    # (which surfaces as ``StaleDataError`` from SQLAlchemy when the
    # expected row count doesn't match).
    await set_rls_context(
        session,
        user_id=current_user.id,
        guild_id=guild_id,
        guild_role=membership.role.value,
        is_superadmin=(current_user.role == UserRole.admin),
    )

    from app.services import users as users_service
    from app.services.users import (
        InvalidTransferRecipient,
        get_owned_projects_in_guild,
        is_last_admin_of_guild,
    )

    if await is_last_admin_of_guild(session, guild_id, current_user.id, for_update=True):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=GuildMessages.CANNOT_LEAVE_LAST_ADMIN,
        )

    sole_pm_initiatives = await initiatives_service.initiatives_requiring_new_pm(
        session, current_user.id, guild_id=guild_id
    )
    if sole_pm_initiatives:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=GuildMessages.CANNOT_LEAVE_SOLE_PM,
        )

    owned_projects = await get_owned_projects_in_guild(session, current_user.id, guild_id)
    if owned_projects:
        transfers = body.project_transfers if body is not None else {}
        deletions = set(body.project_deletions) if body is not None else set()
        owned_ids = {project.id for project in owned_projects}
        transfer_ids = set(transfers.keys())

        # Every owned project needs exactly one disposition (transfer
        # OR delete) and the union must cover them all. Any missing,
        # surplus, or overlapping ids → reject with one stable code so
        # the SPA can map a single translation string.
        missing = owned_ids - transfer_ids - deletions
        extra = (transfer_ids - owned_ids) | (deletions - owned_ids)
        overlap = transfer_ids & deletions
        if missing or extra or overlap:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=GuildMessages.CANNOT_LEAVE_OWNS_PROJECTS,
            )

        for project_id, new_owner_id in transfers.items():
            try:
                await users_service.transfer_project_ownership(
                    session, project_id, new_owner_id
                )
            except InvalidTransferRecipient:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=GuildMessages.PROJECT_TRANSFER_RECIPIENT_INVALID,
                )

        if deletions:
            # Soft-delete (send to trash) the projects the user opted to
            # discard rather than transfer. Uses the guild's configured
            # retention so the trash auto-purge job picks them up just
            # like a normal in-app project deletion.
            from app.services import soft_delete as soft_delete_service

            retention_days = await guilds_service.get_guild_retention_days(
                session, guild_id
            )
            projects_by_id = {project.id: project for project in owned_projects}
            for project_id in deletions:
                project = projects_by_id[project_id]
                await soft_delete_service.soft_delete_entity(
                    session,
                    project,
                    deleted_by_user_id=current_user.id,
                    retention_days=retention_days,
                )

    await guilds_service.remove_user_from_guild(session, guild_id=guild_id, user_id=current_user.id)

    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
