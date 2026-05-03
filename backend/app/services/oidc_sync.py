from __future__ import annotations

import logging
from dataclasses import dataclass, field

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.guild import GuildMembership, GuildRole
from app.models.initiative import InitiativeMember, InitiativeRoleModel
from app.models.oidc_claim_mapping import OIDCClaimMapping, OIDCMappingTargetType
from app.models.user import User, UserStatus

logger = logging.getLogger(__name__)

# Role priority for conflict resolution: higher wins
_GUILD_ROLE_PRIORITY = {
    GuildRole.member.value: 0,
    GuildRole.admin.value: 1,
}


@dataclass
class OIDCSyncResult:
    guilds_added: list[int] = field(default_factory=list)
    guilds_updated: list[int] = field(default_factory=list)
    guilds_removed: list[int] = field(default_factory=list)
    initiatives_added: list[int] = field(default_factory=list)
    initiatives_updated: list[int] = field(default_factory=list)
    initiatives_removed: list[int] = field(default_factory=list)


def extract_claim_values(
    profile: dict,
    id_token_claims: dict | None,
    claim_path: str,
) -> set[str]:
    """Extract claim values from userinfo or id_token using dot-notation path."""

    def _traverse(data: dict, path_parts: list[str]) -> list | str | None:
        current = data
        for part in path_parts:
            if not isinstance(current, dict):
                return None
            current = current.get(part)
            if current is None:
                return None
        return current

    parts = claim_path.strip().split(".")
    if not parts or not parts[0]:
        return set()

    # Try userinfo first, then id_token
    raw = _traverse(profile, parts)
    if raw is None and id_token_claims:
        raw = _traverse(id_token_claims, parts)

    if raw is None:
        return set()

    if isinstance(raw, str):
        return {raw.lower()}
    if isinstance(raw, list):
        return {str(v).lower() for v in raw if v is not None}
    return set()


async def sync_oidc_assignments(
    session: AsyncSession,
    *,
    user_id: int,
    claim_values: set[str],
) -> OIDCSyncResult:
    """Sync guild/initiative memberships based on OIDC claim values.

    Must be called with an admin session (bypasses RLS).
    """
    result = OIDCSyncResult()

    # Load all mapping rules
    stmt = select(OIDCClaimMapping)
    mappings = (await session.exec(stmt)).all()
    if not mappings:
        return result

    # Partition into matched and unmatched
    matched: list[OIDCClaimMapping] = []
    matched_guild_ids: set[int] = set()
    matched_initiative_ids: set[int] = set()

    for mapping in mappings:
        if mapping.claim_value.lower() in claim_values:
            matched.append(mapping)
            if mapping.target_type == OIDCMappingTargetType.guild:
                matched_guild_ids.add(mapping.guild_id)
            elif mapping.target_type == OIDCMappingTargetType.initiative:
                matched_guild_ids.add(mapping.guild_id)
                if mapping.initiative_id is not None:
                    matched_initiative_ids.add(mapping.initiative_id)

    # Resolve guild role conflicts: highest role wins per guild
    guild_roles: dict[int, str] = {}
    for mapping in matched:
        gid = mapping.guild_id
        role = mapping.guild_role
        if gid not in guild_roles:
            guild_roles[gid] = role
        elif _GUILD_ROLE_PRIORITY.get(role, 0) > _GUILD_ROLE_PRIORITY.get(guild_roles[gid], 0):
            guild_roles[gid] = role

    # Resolve initiative mappings: collect candidate role_ids per initiative,
    # then pick the highest-privilege role (is_manager wins, then lowest position).
    # Also track which guild each initiative mapping belongs to.
    initiative_guild: dict[int, int] = {}  # initiative_id -> guild_id
    initiative_role_candidates: dict[int, list[int]] = {}  # initiative_id -> role_ids
    for mapping in matched:
        if mapping.target_type == OIDCMappingTargetType.initiative and mapping.initiative_id is not None:
            initiative_guild[mapping.initiative_id] = mapping.guild_id
            if mapping.initiative_role_id is not None:
                initiative_role_candidates.setdefault(mapping.initiative_id, []).append(mapping.initiative_role_id)
            else:
                initiative_role_candidates.setdefault(mapping.initiative_id, [])

    # Resolve each to a single role_id using DB metadata
    initiative_roles: dict[int, int | None] = {}  # initiative_id -> role_id
    for key, candidate_ids in initiative_role_candidates.items():
        if not candidate_ids:
            initiative_roles[key] = None
            continue
        unique_ids = list(set(candidate_ids))
        if len(unique_ids) == 1:
            initiative_roles[key] = unique_ids[0]
            continue
        # Multiple different roles: pick manager first, then lowest position
        roles = (await session.exec(
            select(InitiativeRoleModel).where(InitiativeRoleModel.id.in_(unique_ids))
        )).all()
        if not roles:
            initiative_roles[key] = unique_ids[0]
            continue
        roles.sort(key=lambda r: (not r.is_manager, r.position))
        initiative_roles[key] = roles[0].id

    # --- Guild memberships ---
    for guild_id, role_str in guild_roles.items():
        role = GuildRole(role_str)
        membership = await _get_guild_membership(session, user_id=user_id, guild_id=guild_id)
        if membership:
            if not membership.oidc_managed:
                # Manual membership — never overwrite
                continue
            if membership.role != role:
                membership.role = role
                session.add(membership)
                result.guilds_updated.append(guild_id)
        else:
            await _create_guild_membership(session, user_id=user_id, guild_id=guild_id, role=role)
            result.guilds_added.append(guild_id)

    # --- Initiative memberships ---
    for initiative_id, role_id in initiative_roles.items():
        guild_id = initiative_guild[initiative_id]
        # Ensure guild membership exists first (handled above or create here)
        guild_membership = await _get_guild_membership(session, user_id=user_id, guild_id=guild_id)
        if not guild_membership:
            # Create guild membership as member if not in guild_roles
            g_role = GuildRole(guild_roles.get(guild_id, GuildRole.member.value))
            await _create_guild_membership(session, user_id=user_id, guild_id=guild_id, role=g_role)
            result.guilds_added.append(guild_id)

        im = await _get_initiative_membership(session, user_id=user_id, initiative_id=initiative_id)
        if im:
            if not im.oidc_managed:
                continue
            if role_id is not None and im.role_id != role_id:
                im.role_id = role_id
                session.add(im)
                result.initiatives_updated.append(initiative_id)
        else:
            await _create_initiative_membership(
                session,
                user_id=user_id,
                initiative_id=initiative_id,
                guild_id=guild_id,
                role_id=role_id,
            )
            result.initiatives_added.append(initiative_id)

    # --- Removal of stale oidc_managed memberships ---
    # Remove initiative memberships first (with task cleanup), then guild memberships
    from app.services.initiatives import (
        clear_user_task_assignments_for_initiative,
        remove_user_from_guild_initiatives,
    )

    stale_initiatives = await session.exec(
        select(InitiativeMember).where(
            InitiativeMember.user_id == user_id,
            InitiativeMember.oidc_managed == True,  # noqa: E712
        )
    )
    for im in stale_initiatives.all():
        if im.initiative_id not in matched_initiative_ids:
            await clear_user_task_assignments_for_initiative(
                session, initiative_id=im.initiative_id, user_id=user_id,
            )
            await session.delete(im)
            result.initiatives_removed.append(im.initiative_id)

    stale_guilds = await session.exec(
        select(GuildMembership).where(
            GuildMembership.user_id == user_id,
            GuildMembership.oidc_managed == True,  # noqa: E712
        )
    )
    for gm in stale_guilds.all():
        if gm.guild_id not in matched_guild_ids:
            # Re-home any projects the departing user owned in this
            # guild before dropping their initiative memberships. The
            # interactive ``leave_guild`` endpoint requires the user
            # to nominate transfer recipients; an automated OIDC sync
            # has no UI to ask, so we pick a fallback (initiative
            # manager → guild admin) and log if neither exists.
            await _auto_transfer_owned_projects(
                session, user_id=user_id, guild_id=gm.guild_id,
            )
            await remove_user_from_guild_initiatives(
                session, guild_id=gm.guild_id, user_id=user_id,
            )
            await session.delete(gm)
            result.guilds_removed.append(gm.guild_id)

    await session.commit()
    return result


async def _get_guild_membership(
    session: AsyncSession, *, user_id: int, guild_id: int
) -> GuildMembership | None:
    stmt = select(GuildMembership).where(
        GuildMembership.guild_id == guild_id,
        GuildMembership.user_id == user_id,
    )
    return (await session.exec(stmt)).one_or_none()


async def _create_guild_membership(
    session: AsyncSession,
    *,
    user_id: int,
    guild_id: int,
    role: GuildRole,
) -> GuildMembership:
    from sqlalchemy import func as sa_func

    # Calculate next position
    max_pos = (
        await session.exec(
            select(sa_func.max(GuildMembership.position)).where(
                GuildMembership.user_id == user_id
            )
        )
    ).one_or_none()
    next_pos = (max_pos if max_pos is not None else -1) + 1

    membership = GuildMembership(
        guild_id=guild_id,
        user_id=user_id,
        role=role,
        position=next_pos,
        oidc_managed=True,
    )
    session.add(membership)
    await session.flush()
    return membership


async def _get_initiative_membership(
    session: AsyncSession, *, user_id: int, initiative_id: int
) -> InitiativeMember | None:
    stmt = select(InitiativeMember).where(
        InitiativeMember.initiative_id == initiative_id,
        InitiativeMember.user_id == user_id,
    )
    return (await session.exec(stmt)).one_or_none()


async def _create_initiative_membership(
    session: AsyncSession,
    *,
    user_id: int,
    initiative_id: int,
    guild_id: int,
    role_id: int | None,
) -> InitiativeMember:
    im = InitiativeMember(
        initiative_id=initiative_id,
        user_id=user_id,
        guild_id=guild_id,
        role_id=role_id,
        oidc_managed=True,
    )
    session.add(im)
    await session.flush()
    return im


async def _pick_fallback_owner(
    session: AsyncSession,
    *,
    excluded_user_id: int,
    guild_id: int,
    initiative_id: int,
) -> int | None:
    """Pick a fallback owner for an orphaned project.

    Preference order:
      1. An active initiative manager (other than the departing user).
      2. An active guild admin (other than the departing user).
      3. ``None`` if neither exists — caller logs and skips the
         transfer; the project will be orphaned but the OIDC sync
         won't crash.
    """
    manager_stmt = (
        select(User.id)
        .join(InitiativeMember, InitiativeMember.user_id == User.id)
        .join(InitiativeRoleModel, InitiativeRoleModel.id == InitiativeMember.role_id)
        .where(
            InitiativeMember.initiative_id == initiative_id,
            InitiativeRoleModel.is_manager.is_(True),
            User.status == UserStatus.active,
            User.id != excluded_user_id,
        )
        .limit(1)
    )
    manager_id = (await session.exec(manager_stmt)).first()
    if manager_id is not None:
        return manager_id

    admin_stmt = (
        select(User.id)
        .join(GuildMembership, GuildMembership.user_id == User.id)
        .where(
            GuildMembership.guild_id == guild_id,
            GuildMembership.role == GuildRole.admin,
            User.status == UserStatus.active,
            User.id != excluded_user_id,
        )
        .limit(1)
    )
    return (await session.exec(admin_stmt)).first()


async def _auto_transfer_owned_projects(
    session: AsyncSession,
    *,
    user_id: int,
    guild_id: int,
) -> None:
    """Re-home projects owned by ``user_id`` in ``guild_id`` to a
    fallback owner before the user is removed from the guild.

    Used by the OIDC group-sync removal path, which has no UI to ask
    the user where to transfer ownership. The interactive
    ``leave_guild`` endpoint requires explicit transfers instead;
    this helper is the automated equivalent.
    """
    from sqlmodel import delete as sql_delete

    from app.models.project import ProjectPermission
    from app.services.users import (
        InvalidTransferRecipient,
        get_owned_projects_in_guild,
        transfer_project_ownership,
    )

    async def _drop_departing_permission(project_id: int) -> None:
        # Mirror the ``ProjectPermission`` cleanup that
        # ``transfer_project_ownership`` does on its success path. The
        # row is already unreachable (the user's ``InitiativeMember``
        # is about to be deleted), but a re-sync that adds the user
        # back would otherwise resurrect a stale ``level=owner`` entry
        # — the same regression Bug 5 fixed for the transfer path.
        await session.exec(
            sql_delete(ProjectPermission).where(
                ProjectPermission.project_id == project_id,
                ProjectPermission.user_id == user_id,
            )
        )

    owned = await get_owned_projects_in_guild(session, user_id, guild_id)
    for project in owned:
        new_owner_id = await _pick_fallback_owner(
            session,
            excluded_user_id=user_id,
            guild_id=guild_id,
            initiative_id=project.initiative_id,
        )
        if new_owner_id is None:
            logger.warning(
                "OIDC sync: no fallback owner available for project %s "
                "(initiative %s, guild %s); leaving owner_id pointing to "
                "removed user %s",
                project.id,
                project.initiative_id,
                guild_id,
                user_id,
            )
            await _drop_departing_permission(project.id)
            continue
        try:
            await transfer_project_ownership(session, project.id, new_owner_id)
        except InvalidTransferRecipient:
            # ``_pick_fallback_owner`` already filtered for active
            # users, so this is a TOCTOU race: the chosen candidate
            # was deactivated between the picker query and the
            # transfer's re-validation. Treat it the same as
            # "no fallback available" so the rest of the sync keeps
            # going — otherwise the exception would propagate up
            # through ``_auto_transfer_owned_projects`` and abort the
            # ``stale_guilds`` loop in ``sync_oidc_assignments``,
            # leaving later guild removals partially applied.
            logger.warning(
                "OIDC sync: fallback owner %s for project %s became "
                "inactive between selection and transfer; leaving "
                "owner_id pointing to removed user %s",
                new_owner_id,
                project.id,
                user_id,
            )
            await _drop_departing_permission(project.id)
