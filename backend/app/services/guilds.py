from __future__ import annotations

from datetime import datetime, timedelta, timezone
import secrets

from sqlalchemy import func
from sqlmodel import select, delete
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.messages import GuildMessages
from app.models.guild import Guild, GuildInvite, GuildMembership, GuildRole
from app.models.guild_setting import GuildSetting
from app.models.initiative import Initiative, InitiativeMember
from app.models.project import Project, ProjectPermission
from app.models.task import Task, TaskAssignee
from app.models.user import User

DEFAULT_INVITE_EXPIRATION_DAYS = 7
INVITE_CODE_BYTES = 16


class GuildInviteError(Exception):
    """Raised when an invite cannot be redeemed."""


async def get_primary_guild(session: AsyncSession) -> Guild:
    result = await session.exec(select(Guild).order_by(Guild.id.asc()))
    guild = result.first()
    if guild:
        return guild
    now = datetime.now(timezone.utc)
    guild = Guild(
        name="Primary Guild",
        description="Default guild",
        created_at=now,
        updated_at=now,
    )
    session.add(guild)
    await session.flush()
    return guild


async def get_primary_guild_id(session: AsyncSession) -> int:
    guild = await get_primary_guild(session)
    return guild.id  # type: ignore[return-value]


async def get_guild(session: AsyncSession, guild_id: int) -> Guild:
    stmt = select(Guild).where(Guild.id == guild_id)
    result = await session.exec(stmt)
    guild = result.one_or_none()
    if not guild:
        raise ValueError(GuildMessages.GUILD_NOT_FOUND)
    return guild


async def resolve_user_guild_id(
    session: AsyncSession,
    *,
    user,
    guild_id: int | None = None,
) -> int | None:
    if guild_id is not None:
        return guild_id
    if user and getattr(user, "id", None):
        result = await session.exec(
            select(GuildMembership.guild_id).where(GuildMembership.user_id == user.id).limit(1)
        )
        membership_guild_id = result.first()
        if membership_guild_id:
            return membership_guild_id
    return None


async def ensure_membership(
    session: AsyncSession,
    *,
    guild_id: int,
    user_id: int,
    role: GuildRole = GuildRole.member,
    force_role: bool = False,
    oidc_managed: bool = False,
) -> GuildMembership:
    stmt = select(GuildMembership).where(
        GuildMembership.guild_id == guild_id,
        GuildMembership.user_id == user_id,
    )
    result = await session.exec(stmt)
    membership = result.one_or_none()
    if membership:
        updated = False
        if force_role and membership.role != role:
            membership.role = role
            updated = True
        if oidc_managed and not membership.oidc_managed:
            membership.oidc_managed = True
            updated = True
        if updated:
            session.add(membership)
            await session.flush()
        return membership
    next_position = await _next_membership_position(session, user_id=user_id)
    membership = GuildMembership(
        guild_id=guild_id,
        user_id=user_id,
        role=role,
        position=next_position,
        oidc_managed=oidc_managed,
    )
    session.add(membership)
    await session.flush()
    return membership


async def _next_membership_position(session: AsyncSession, *, user_id: int) -> int:
    result = await session.exec(
        select(func.max(GuildMembership.position)).where(GuildMembership.user_id == user_id)
    )
    max_value = result.one_or_none()
    highest = max_value if max_value is not None else -1
    return highest + 1


async def reorder_memberships(
    session: AsyncSession,
    *,
    user_id: int,
    ordered_guild_ids: list[int],
) -> None:
    if not ordered_guild_ids:
        return

    stmt = select(GuildMembership).where(GuildMembership.user_id == user_id)
    result = await session.exec(stmt)
    memberships = result.all()
    if not memberships:
        return

    membership_by_guild = {membership.guild_id: membership for membership in memberships}
    seen: set[int] = set()
    position = 0

    for guild_id in ordered_guild_ids:
        if guild_id in seen:
            continue
        membership = membership_by_guild.get(guild_id)
        if not membership:
            continue
        membership.position = position
        session.add(membership)
        seen.add(guild_id)
        position += 1

    remaining = [membership for membership in memberships if membership.guild_id not in seen]
    remaining.sort(
        key=lambda membership: (
            membership.position if membership.position is not None else 0,
            membership.joined_at,
        )
    )
    for membership in remaining:
        membership.position = position
        session.add(membership)
        position += 1

    await session.flush()


async def get_membership(
    session: AsyncSession,
    *,
    guild_id: int,
    user_id: int,
    for_update: bool = False,
) -> GuildMembership | None:
    stmt = select(GuildMembership).where(
        GuildMembership.guild_id == guild_id,
        GuildMembership.user_id == user_id,
    )
    if for_update:
        stmt = stmt.with_for_update()
    result = await session.exec(stmt)
    return result.one_or_none()


async def list_memberships(
    session: AsyncSession,
    *,
    user_id: int,
) -> list[tuple[Guild, GuildMembership]]:
    stmt = (
        select(Guild, GuildMembership)
        .join(GuildMembership, GuildMembership.guild_id == Guild.id)
        .where(GuildMembership.user_id == user_id)
        .order_by(
            GuildMembership.position.asc(),
            GuildMembership.joined_at.asc(),
            Guild.id.asc(),
        )
    )
    result = await session.exec(stmt)
    return result.all()


async def create_guild(
    session: AsyncSession,
    *,
    name: str,
    description: str | None = None,
    icon_base64: str | None = None,
    creator: User | None = None,
) -> Guild:
    now = datetime.now(timezone.utc)
    guild = Guild(
        name=name.strip(),
        description=description.strip() if description and description.strip() else None,
        icon_base64=icon_base64,
        created_by_user_id=creator.id if creator else None,
        created_at=now,
        updated_at=now,
    )
    session.add(guild)
    await session.flush()
    if creator:
        await ensure_membership(
            session,
            guild_id=guild.id,
            user_id=creator.id,
            role=GuildRole.admin,
        )
    return guild


async def update_guild(
    session: AsyncSession,
    *,
    guild_id: int,
    name: str | None = None,
    description: str | None = None,
    icon_base64: str | None = None,
    icon_provided: bool = False,
) -> Guild:
    guild = await get_guild(session, guild_id=guild_id)
    updated = False
    if name is not None and name.strip() and guild.name != name.strip():
        guild.name = name.strip()
        updated = True
    if description is not None:
        normalized_description = description.strip() or None
        if guild.description != normalized_description:
            guild.description = normalized_description
            updated = True
    if icon_provided and icon_base64 != guild.icon_base64:
        guild.icon_base64 = icon_base64
        updated = True
    if updated:
        guild.updated_at = datetime.now(timezone.utc)
        session.add(guild)
        await session.flush()
    return guild


async def _invite_code_exists(session: AsyncSession, code: str) -> bool:
    stmt = select(GuildInvite.id).where(GuildInvite.code == code)
    result = await session.exec(stmt)
    return result.first() is not None


async def _generate_unique_invite_code(session: AsyncSession) -> str:
    for _ in range(10):
        candidate = secrets.token_urlsafe(INVITE_CODE_BYTES)
        if not await _invite_code_exists(session, candidate):
            return candidate
    raise RuntimeError("Unable to generate unique invite code")


async def list_guild_invites(session: AsyncSession, *, guild_id: int) -> list[GuildInvite]:
    stmt = select(GuildInvite).where(GuildInvite.guild_id == guild_id).order_by(GuildInvite.created_at.desc())
    result = await session.exec(stmt)
    return result.all()


async def create_guild_invite(
    session: AsyncSession,
    *,
    guild_id: int,
    created_by_user_id: int | None,
    expires_at: datetime | None = None,
    max_uses: int | None = 1,
    invitee_email: str | None = None,
) -> GuildInvite:
    code = await _generate_unique_invite_code(session)
    if expires_at is None:
        expiry = datetime.now(timezone.utc) + timedelta(days=DEFAULT_INVITE_EXPIRATION_DAYS)
    else:
        expiry = expires_at if expires_at.tzinfo else expires_at.replace(tzinfo=timezone.utc)
    invite = GuildInvite(
        code=code,
        guild_id=guild_id,
        created_by_user_id=created_by_user_id,
        expires_at=expiry,
        max_uses=max_uses,
        invitee_email=invitee_email,
    )
    session.add(invite)
    await session.flush()
    return invite


async def delete_guild_invite(session: AsyncSession, *, guild_id: int, invite_id: int) -> None:
    stmt = select(GuildInvite).where(
        GuildInvite.id == invite_id,
        GuildInvite.guild_id == guild_id,
    )
    result = await session.exec(stmt)
    invite = result.one_or_none()
    if invite:
        await session.delete(invite)


async def delete_guild(session: AsyncSession, guild: Guild) -> None:
    initiative_ids = [row for row in (await session.exec(select(Initiative.id).where(Initiative.guild_id == guild.id))).all()]
    project_ids: list[int] = []
    task_ids: list[int] = []
    if initiative_ids:
        project_ids = [row for row in (await session.exec(select(Project.id).where(Project.initiative_id.in_(initiative_ids)))).all()]
    if project_ids:
        task_ids = [row for row in (await session.exec(select(Task.id).where(Task.project_id.in_(project_ids)))).all()]

    if task_ids:
        await session.exec(delete(TaskAssignee).where(TaskAssignee.task_id.in_(task_ids)))
        await session.exec(delete(Task).where(Task.id.in_(task_ids)))
    if project_ids:
        await session.exec(delete(ProjectPermission).where(ProjectPermission.project_id.in_(project_ids)))
        await session.exec(delete(Project).where(Project.id.in_(project_ids)))
    if initiative_ids:
        await session.exec(delete(InitiativeMember).where(InitiativeMember.initiative_id.in_(initiative_ids)))
        await session.exec(delete(Initiative).where(Initiative.id.in_(initiative_ids)))

    await session.exec(delete(GuildInvite).where(GuildInvite.guild_id == guild.id))
    await session.exec(delete(GuildMembership).where(GuildMembership.guild_id == guild.id))
    await session.exec(delete(GuildSetting).where(GuildSetting.guild_id == guild.id))
    await session.delete(guild)


async def get_invite_by_code(session: AsyncSession, *, code: str) -> GuildInvite | None:
    stmt = select(GuildInvite).where(GuildInvite.code == code)
    result = await session.exec(stmt)
    return result.one_or_none()


def invite_is_active(invite: GuildInvite) -> bool:
    if invite.expires_at and invite.expires_at < datetime.now(timezone.utc):
        return False
    if invite.max_uses is not None and invite.uses >= invite.max_uses:
        return False
    return True


async def redeem_invite_for_user(
    session: AsyncSession,
    *,
    code: str,
    user: User,
) -> Guild:
    invite = await get_invite_by_code(session, code=code)
    if not invite:
        raise GuildInviteError(GuildMessages.INVITE_NOT_FOUND)
    if not invite_is_active(invite):
        raise GuildInviteError(GuildMessages.INVITE_EXPIRED_OR_USED)

    await ensure_membership(
        session,
        guild_id=invite.guild_id,
        user_id=user.id,
        role=GuildRole.member,
    )
    invite.uses += 1
    session.add(invite)
    guild = await get_guild(session, guild_id=invite.guild_id)
    return guild


async def describe_invite_code(
    session: AsyncSession,
    *,
    code: str,
) -> tuple[GuildInvite | None, Guild | None, bool, str | None]:
    invite = await get_invite_by_code(session, code=code)
    if not invite:
        return None, None, False, GuildMessages.INVITE_NOT_FOUND
    guild = await get_guild(session, guild_id=invite.guild_id)
    if invite_is_active(invite):
        return invite, guild, True, None

    reason = GuildMessages.INVITE_INVALID
    now = datetime.now(timezone.utc)
    if invite.expires_at and invite.expires_at < now:
        reason = GuildMessages.INVITE_EXPIRED
    elif invite.max_uses is not None and invite.uses >= invite.max_uses:
        reason = GuildMessages.INVITE_USED
    return invite, guild, False, reason


async def remove_user_from_guild(
    session: AsyncSession,
    *,
    guild_id: int,
    user_id: int,
) -> None:
    """Remove a user from a guild and all its initiatives."""
    from app.services import initiatives as initiatives_service

    # Remove from all initiatives in this guild
    await initiatives_service.remove_user_from_guild_initiatives(
        session,
        guild_id=guild_id,
        user_id=user_id,
    )

    # Remove guild membership
    stmt = delete(GuildMembership).where(
        GuildMembership.guild_id == guild_id,
        GuildMembership.user_id == user_id,
    )
    await session.exec(stmt)
