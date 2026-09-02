from __future__ import annotations

import logging
from dataclasses import dataclass, field

from sqlmodel import delete, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.session import set_rls_context
from app.models.platform.guild import GuildMembership, GuildRole
from app.services.platform import account_stream
from app.services.platform import billing_ping
from app.models.tenant.initiative import (
    Initiative,
    InitiativeMember,
    InitiativeRoleModel,
)
from app.models.platform.oidc_claim_mapping import (
    OIDCClaimMapping,
    OIDCMappingTargetType,
)

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

    def _traverse(data: dict, path_parts: list[str]) -> list | str | dict | None:
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
        elif _GUILD_ROLE_PRIORITY.get(role, 0) > _GUILD_ROLE_PRIORITY.get(
            guild_roles[gid], 0
        ):
            guild_roles[gid] = role

    # Resolve initiative mappings: collect candidate role_ids per initiative,
    # then pick the highest-privilege role (is_manager wins, then lowest position).
    # Also track which guild each initiative mapping belongs to.
    initiative_guild: dict[int, int] = {}  # initiative_id -> guild_id
    initiative_role_candidates: dict[int, list[int]] = {}  # initiative_id -> role_ids
    for mapping in matched:
        if (
            mapping.target_type == OIDCMappingTargetType.initiative
            and mapping.initiative_id is not None
        ):
            initiative_guild[mapping.initiative_id] = mapping.guild_id
            if mapping.initiative_role_id is not None:
                initiative_role_candidates.setdefault(mapping.initiative_id, []).append(
                    mapping.initiative_role_id
                )
            else:
                initiative_role_candidates.setdefault(mapping.initiative_id, [])

    # ``oidc_claim_mappings`` is shared, but initiatives/roles/members are
    # guild-scoped (per-guild schemas). Every guild-scoped read/write below is
    # therefore routed into the relevant guild's schema as its guild role.

    # --- Guild memberships (shared table — public/admin context) ---
    # Apply matched guild roles, and ensure a membership exists for every guild
    # that has a matched initiative so the initiative member can be added below.
    ensure_member_guilds = set(guild_roles) | set(initiative_guild.values())
    # Guilds this sync admits the user to for the first time, as a plain member.
    # They are as new to the guild as an invite redeemer, so the guild's
    # auto-join initiatives take them in the same way (below, in the routed
    # per-guild loop). Admins are left out for the same reason the invite path
    # leaves them out — standing access already, and no member role to hold.
    newly_admitted_guilds: set[int] = set()
    for guild_id in sorted(ensure_member_guilds):
        desired = guild_roles.get(guild_id)
        membership = await _get_guild_membership(
            session, user_id=user_id, guild_id=guild_id
        )
        if membership:
            # Never overwrite a manual membership.
            if desired is not None and membership.oidc_managed:
                role = GuildRole(desired)
                if membership.role != role:
                    membership.role = role
                    session.add(membership)
                    result.guilds_updated.append(guild_id)
        else:
            role = GuildRole(desired) if desired is not None else GuildRole.member
            await _create_guild_membership(
                session, user_id=user_id, guild_id=guild_id, role=role
            )
            result.guilds_added.append(guild_id)
            # Nobody was at a keyboard for this one — it is the case the
            # standing checks exist for. Their tabs re-read the account.
            account_stream.queue_account_signal(session, user_id, "membership")
            if role != GuildRole.admin:
                newly_admitted_guilds.add(guild_id)
            # Event-driven seats (billing plan D5); no-op unless billing is
            # configured. Once per changed guild, not per member row.
            billing_ping.notify_membership_changed(guild_id)
    await session.flush()

    # Guilds to visit for guild-scoped work: those the claims map to, plus every
    # guild the user already belongs to (so stale oidc-managed initiative
    # memberships get cleaned up). guild_memberships is shared/public.
    existing_guild_ids = set(
        (
            await session.exec(
                select(GuildMembership.guild_id).where(
                    GuildMembership.user_id == user_id
                )
            )
        ).all()
    )
    relevant_guilds = sorted(
        existing_guild_ids | set(initiative_guild.values()) | set(guild_roles)
    )

    # --- Initiative resolution + membership (guild-scoped, routed per guild) ---
    from app.services.tenant.initiatives import (
        clear_user_task_assignments_for_initiative,
        enroll_in_auto_join_initiatives,
    )

    for gid in relevant_guilds:
        session.expunge_all()
        await set_rls_context(session, guild_id=gid, guild_role="admin")

        guild_inits = {iid for iid, g in initiative_guild.items() if g == gid}
        # Drop references to initiatives that no longer exist in this schema
        # (oidc_claim_mappings has no cross-schema FK, so a purged initiative can
        # leave a dangling mapping).
        if guild_inits:
            present = set(
                (
                    await session.exec(
                        select(Initiative.id).where(Initiative.id.in_(guild_inits))
                    )
                ).all()
            )
            guild_inits &= present

        # Resolve each initiative to a single role_id (manager first, then lowest
        # position), validating the role still exists in this schema.
        guild_init_roles: dict[int, int | None] = {}
        for iid in guild_inits:
            unique_ids = list(
                {c for c in initiative_role_candidates.get(iid, []) if c is not None}
            )
            role_id: int | None = None
            if unique_ids:
                roles = (
                    await session.exec(
                        select(InitiativeRoleModel).where(
                            InitiativeRoleModel.id.in_(unique_ids)
                        )
                    )
                ).all()
                if roles:
                    roles.sort(key=lambda r: (not r.is_manager, r.position))
                    role_id = roles[0].id
            guild_init_roles[iid] = role_id

        for iid, role_id in guild_init_roles.items():
            im = await _get_initiative_membership(
                session, user_id=user_id, initiative_id=iid
            )
            if im:
                if not im.oidc_managed:
                    continue
                if role_id is not None and im.role_id != role_id:
                    im.role_id = role_id
                    session.add(im)
                    result.initiatives_updated.append(iid)
            else:
                await _create_initiative_membership(
                    session,
                    user_id=user_id,
                    initiative_id=iid,
                    guild_id=gid,
                    role_id=role_id,
                )
                result.initiatives_added.append(iid)

        # Remove stale oidc-managed initiative memberships in THIS guild that the
        # claims no longer grant.
        stale_inits = (
            await session.exec(
                select(InitiativeMember).where(
                    InitiativeMember.user_id == user_id,
                    InitiativeMember.oidc_managed == True,  # noqa: E712
                )
            )
        ).all()
        for im in stale_inits:
            if im.initiative_id not in matched_initiative_ids:
                await clear_user_task_assignments_for_initiative(
                    session, initiative_id=im.initiative_id, user_id=user_id
                )
                await session.delete(im)
                result.initiatives_removed.append(im.initiative_id)

        # Onboarding for a first-time arrival, once the claims have had their
        # say. It runs last because the claims are authoritative about role:
        # enrolment would otherwise write a plain member row that the mapping
        # loop above then declines to touch (it leaves non-oidc-managed rows
        # alone by design), and a user mapped to a manager role would silently
        # land as a member. Enrolling afterwards is a no-op for any initiative
        # the claims already placed them in, so this only fills the gaps.
        #
        # The rows are ordinary (``oidc_managed`` false), so the sweep above
        # leaves them alone and a later sync neither reaps nor fights them.
        if gid in newly_admitted_guilds:
            try:
                async with session.begin_nested():
                    await enroll_in_auto_join_initiatives(
                        session, guild_id=gid, user_id=user_id
                    )
            except Exception:
                logger.exception(
                    "auto-join: user %s was admitted to guild %s by claim sync "
                    "but enrolled in none of its auto-join initiatives",
                    user_id,
                    gid,
                )
        await session.flush()

    # --- Remove stale guild memberships ---
    # For each oidc-managed guild the claims no longer grant: re-home owned
    # projects + drop initiative memberships (guild-scoped, routed), then delete
    # the shared GuildMembership row in public context.
    from app.services.tenant.initiatives import remove_user_from_guild_initiatives

    session.expunge_all()
    await set_rls_context(session)
    stale_guild_ids = (
        await session.exec(
            select(GuildMembership.guild_id).where(
                GuildMembership.user_id == user_id,
                GuildMembership.oidc_managed == True,  # noqa: E712
            )
        )
    ).all()
    for stale_gid in stale_guild_ids:
        if stale_gid in matched_guild_ids:
            continue
        session.expunge_all()
        await set_rls_context(session, guild_id=stale_gid, guild_role="admin")
        await remove_user_from_guild_initiatives(
            session, guild_id=stale_gid, user_id=user_id
        )
        await session.flush()
        session.expunge_all()
        await set_rls_context(session)
        await session.exec(
            delete(GuildMembership).where(
                GuildMembership.user_id == user_id,
                GuildMembership.guild_id == stale_gid,
            )
        )
        result.guilds_removed.append(stale_gid)
        billing_ping.notify_membership_changed(stale_gid)

    session.expunge_all()
    await set_rls_context(session)
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
