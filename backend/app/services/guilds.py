from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
import secrets

from sqlalchemy import func
from sqlmodel import select, delete
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.encryption import encrypt_field, hash_email, SALT_EMAIL
from app.core.messages import GuildMessages
from app.models.guild import Guild, GuildInvite, GuildMembership, GuildRole
from app.models.guild_setting import GuildSetting
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
    # Commit the new guild row, then provision its schema — a brand-new primary
    # guild is schema-native from birth. (Only the first time the primary guild is
    # created, i.e. fresh-DB seeding.)
    await session.commit()
    from app.db.schema_provisioning import provision_guild

    await provision_guild(guild.id)
    return guild


async def get_primary_guild_id(session: AsyncSession) -> int:
    guild = await get_primary_guild(session)
    return guild.id  # ty: ignore[invalid-return-type]


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
            select(GuildMembership.guild_id)
            .where(GuildMembership.user_id == user.id)
            .limit(1)
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
        select(func.max(GuildMembership.position)).where(
            GuildMembership.user_id == user_id
        )
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

    membership_by_guild = {
        membership.guild_id: membership for membership in memberships
    }
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

    remaining = [
        membership for membership in memberships if membership.guild_id not in seen
    ]
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
) -> list[tuple[Guild, GuildMembership, int | None, int]]:
    """Return (guild, membership, retention_days, member_count) for each guild
    the user belongs to.

    The guild + membership rows are shared (public). ``retention_days`` lives in
    each guild's own schema (``guild_settings``), so it's read per guild with the
    user's membership context — a single cross-guild join would hit the empty
    public table and report NULL for everyone. ``guild_settings.id`` is a
    per-schema serial that collides across schemas, so each settings row is
    detached after reading so a cached row can't shadow the next guild's.

    ``member_count`` is the total number of members in the guild. It's read
    inside the same per-guild loop because the ``guild_memberships_select`` RLS
    policy only exposes sibling rows while that guild's context is active
    (``guild_id = current_guild_id``); under the caller's user-only context a
    cross-guild count would see just the user's own row."""
    from app.db.session import set_rls_context  # lazy: avoids a circular import

    await set_rls_context(session, user_id=user_id)
    pairs = (
        await session.exec(
            select(Guild, GuildMembership)
            .join(GuildMembership, GuildMembership.guild_id == Guild.id)
            .where(GuildMembership.user_id == user_id)
            .order_by(
                GuildMembership.position.asc(),
                GuildMembership.joined_at.asc(),
                Guild.id.asc(),
            )
        )
    ).all()

    out: list[tuple[Guild, GuildMembership, int | None, int]] = []
    for guild, membership in pairs:
        await set_rls_context(session, user_id=user_id, guild_id=guild.id)
        row = (
            await session.exec(
                select(GuildSetting).where(GuildSetting.guild_id == guild.id)
            )
        ).one_or_none()
        # No row yet → the 90-day default; an explicit NULL is the user's "never".
        retention = 90 if row is None else row.retention_days
        if row is not None:
            session.expunge(row)
        member_count = await count_members(session, guild_id=guild.id)
        out.append((guild, membership, retention, member_count))

    # Restore the user-only context the caller (UserSessionDep) handed us.
    await set_rls_context(session, user_id=user_id)
    return out


async def count_members(session: AsyncSession, *, guild_id: int) -> int:
    """Total number of members in a guild.

    The caller must already hold a session that can see the guild's
    ``guild_memberships`` rows — an admin (BYPASSRLS) session, or one whose RLS
    context is set to this guild (``guild_id = current_guild_id``). Under a
    user-only context the ``guild_memberships_select`` policy would expose only
    the caller's own row."""
    return (
        await session.exec(
            select(func.count())
            .select_from(GuildMembership)
            .where(GuildMembership.guild_id == guild_id)
        )
    ).one()


async def create_guild_settings(session: AsyncSession, guild_id: int) -> GuildSetting:
    """Seed a guild_settings row. guild_settings is guild-scoped (it holds
    private config like API keys), so under schema-per-guild this must run with
    the session already routed to the guild's schema."""
    settings_row = GuildSetting(guild_id=guild_id, retention_days=90)
    session.add(settings_row)
    await session.flush()
    return settings_row


async def create_guild(
    session: AsyncSession,
    *,
    name: str,
    description: str | None = None,
    icon_base64: str | None = None,
    creator: User | None = None,
) -> Guild:
    """Create a guild's *shared* rows only — the guild row (public) and the
    creator's admin membership (public). The guild-scoped seed rows (settings +
    default initiative) live in the guild's schema, which doesn't exist yet, so
    the caller commits this, then calls :func:`seed_guild_content`.
    """
    now = datetime.now(timezone.utc)
    guild = Guild(
        name=name.strip(),
        description=description.strip()
        if description and description.strip()
        else None,
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


async def seed_guild_content(
    session: AsyncSession,
    *,
    guild_id: int,
    creator: User,
    is_superadmin: bool = False,
) -> None:
    """Provision a new guild's schema and create its guild-scoped seed rows
    (settings + default initiative) *inside* it.

    The shared guild row must already exist; this provisions the schema + role and
    seeds into it (the caller commits around the call). On failure the caller
    should ``deprovision_guild`` and remove the shared rows.
    """
    from app.db.schema_provisioning import provision_guild
    from app.db.session import set_rls_context
    from app.services import initiatives as initiatives_service

    await provision_guild(guild_id)
    await set_rls_context(
        session,
        user_id=creator.id,
        guild_id=guild_id,
        guild_role=GuildRole.admin.value,
        is_superadmin=is_superadmin,
    )
    await create_guild_settings(session, guild_id)
    await initiatives_service.ensure_default_initiative(
        session, creator, guild_id=guild_id
    )


async def update_guild(
    session: AsyncSession,
    *,
    guild_id: int,
    name: str | None = None,
    description: str | None = None,
    icon_base64: str | None = None,
    icon_provided: bool = False,
    retention_days: int | None = None,
    retention_days_provided: bool = False,
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
    if retention_days_provided:
        from app.services.app_settings import get_or_create_guild_settings

        gs = await get_or_create_guild_settings(session, guild_id)
        if gs.retention_days != retention_days:
            gs.retention_days = retention_days
            session.add(gs)
            await session.flush()
    return guild


async def get_guild_retention_days(session: AsyncSession, guild_id: int) -> int | None:
    """Return the per-guild trash retention period in days, or None for
    "never auto-purge".

    Selecting the full row (not the column) is intentional: NULL in
    ``retention_days`` is the user's explicit "never" choice, and we must
    distinguish it from "no guild_settings row yet" (which would be a
    setup gap, fall back to the 90-day default). A bare column select
    collapses both to None and silently re-enables auto-purge for guilds
    that opted out.
    """
    stmt = select(GuildSetting).where(GuildSetting.guild_id == guild_id)
    result = await session.exec(stmt)
    row = result.one_or_none()
    if row is None:
        return 90
    return row.retention_days


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


async def list_guild_invites(
    session: AsyncSession, *, guild_id: int
) -> Sequence[GuildInvite]:
    stmt = (
        select(GuildInvite)
        .where(GuildInvite.guild_id == guild_id)
        .order_by(GuildInvite.created_at.desc())
    )
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
        expiry = datetime.now(timezone.utc) + timedelta(
            days=DEFAULT_INVITE_EXPIRATION_DAYS
        )
    else:
        expiry = (
            expires_at if expires_at.tzinfo else expires_at.replace(tzinfo=timezone.utc)
        )
    invite = GuildInvite(
        code=code,
        guild_id=guild_id,
        created_by_user_id=created_by_user_id,
        expires_at=expiry,
        max_uses=max_uses,
        invitee_email_encrypted=encrypt_field(invitee_email, SALT_EMAIL)
        if invitee_email
        else None,
    )
    session.add(invite)
    await session.flush()
    return invite


async def delete_guild_invite(
    session: AsyncSession, *, guild_id: int, invite_id: int
) -> None:
    stmt = select(GuildInvite).where(
        GuildInvite.id == invite_id,
        GuildInvite.guild_id == guild_id,
    )
    result = await session.exec(stmt)
    invite = result.one_or_none()
    if invite:
        await session.delete(invite)


async def delete_guild(session: AsyncSession, guild: Guild) -> None:
    """Delete a guild's shared rows.

    Under schema-per-guild the guild's content lives in its schema and is removed
    separately by ``deprovision_guild`` (``DROP SCHEMA … CASCADE``). Here we only
    delete the shared guild row; its ``ON DELETE CASCADE`` foreign keys clear the
    roster (memberships, invites, OIDC claim mappings, access grants).

    Order-independent w.r.t. the schema drop: guild-schema tables carry no FKs to
    ``public.guilds`` (provisioning omits cross-schema FKs), so this row delete is
    never blocked by the schema. Callers delete the row first (reliable, makes the
    guild gone) and drop the schema as best-effort cleanup afterwards.

    Uses a bulk DELETE (not ``session.delete``) so the row goes via the DB-level
    ON DELETE CASCADE FKs — ``session.delete`` would walk ORM relationships and
    attempt sync loads in the async context (MissingGreenlet).
    """
    await session.exec(delete(Guild).where(Guild.id == guild.id))


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

    # Email binding. ``invitee_email`` is advisory-when-absent: an invite with no
    # bound address (``invitee_email_encrypted`` is NULL) is a shareable link and
    # any authenticated user may redeem it. When it *is* set, the invite is bound
    # to that address and only the matching user may redeem it — otherwise the
    # binding is decorative and gives a false sense of security (SEC-15). We
    # compare via ``hash_email`` so normalization (lowercase/strip) matches the
    # users.email_hash unique-constraint exactly; ``user.email_hash`` is already
    # populated in both the register and accept-invite flows.
    bound_email = invite.invitee_email
    if bound_email and user.email_hash != hash_email(bound_email):
        raise GuildInviteError(GuildMessages.INVITE_EMAIL_MISMATCH)

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
