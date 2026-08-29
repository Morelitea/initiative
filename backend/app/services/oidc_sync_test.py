"""Claim sync and auto-join enrolment share a user's first arrival in a guild.

Coverage here is deliberately narrow: it pins the ordering between the two, the
invariant that is easy to break and silent when broken. The module's wider
behaviour — the stale sweep, role changes, idempotency — is still uncovered and
tracked in #1279.
"""

import pytest
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.session import set_rls_context
from app.models.platform.guild import GuildRole
from app.models.platform.oidc_claim_mapping import (
    OIDCClaimMapping,
    OIDCMappingTargetType,
)
from app.models.tenant.initiative import InitiativeMember
from app.services.oidc_sync import sync_oidc_assignments
from app.services.tenant.initiatives import get_pm_role
from app.testing.factories import create_guild, create_initiative, create_user


async def _membership(
    session: AsyncSession, *, guild_id: int, initiative_id: int, user_id: int
) -> InitiativeMember | None:
    session.expunge_all()
    await set_rls_context(session, guild_id=guild_id, guild_role="admin")
    return (
        await session.exec(
            select(InitiativeMember).where(
                InitiativeMember.initiative_id == initiative_id,
                InitiativeMember.user_id == user_id,
            )
        )
    ).one_or_none()


@pytest.mark.integration
async def test_claim_mapped_role_survives_auto_join(session: AsyncSession):
    """A mapped role wins over the plain membership auto-join would write.

    Both apply to the same initiative on the same first arrival. Enrolment runs
    after the mapping for this reason: it writes a non-oidc-managed row, and the
    mapping loop leaves those alone by design, so enrolling first would silently
    strand a manager on the member role.
    """
    owner = await create_user(session)
    guild = await create_guild(session, creator=owner)
    initiative = await create_initiative(
        session, guild, owner, name="Onboarding", join_policy="open", auto_join=True
    )
    pm_role = await get_pm_role(session, initiative_id=initiative.id)

    newcomer = await create_user(session)
    session.add(
        OIDCClaimMapping(
            claim_value="engineering",
            target_type=OIDCMappingTargetType.initiative,
            guild_id=guild.id,
            guild_role=GuildRole.member.value,
            initiative_id=initiative.id,
            initiative_role_id=pm_role.id,
        )
    )
    await session.commit()

    await set_rls_context(session)
    await sync_oidc_assignments(
        session, user_id=newcomer.id, claim_values={"engineering"}
    )
    await session.commit()

    membership = await _membership(
        session, guild_id=guild.id, initiative_id=initiative.id, user_id=newcomer.id
    )
    assert membership is not None
    # The claim's role, not the built-in member role enrolment hands out.
    assert membership.role_id == pm_role.id
    assert membership.oidc_managed is True


@pytest.mark.integration
async def test_auto_join_still_covers_what_the_claims_do_not(session: AsyncSession):
    """Enrolment fills the gaps the mapping left, and only those."""
    owner = await create_user(session)
    guild = await create_guild(session, creator=owner)
    mapped = await create_initiative(session, guild, owner, name="Mapped")
    unmapped = await create_initiative(
        session, guild, owner, name="Welcome", join_policy="open", auto_join=True
    )
    mapped_pm = await get_pm_role(session, initiative_id=mapped.id)

    newcomer = await create_user(session)
    session.add(
        OIDCClaimMapping(
            claim_value="engineering",
            target_type=OIDCMappingTargetType.initiative,
            guild_id=guild.id,
            guild_role=GuildRole.member.value,
            initiative_id=mapped.id,
            initiative_role_id=mapped_pm.id,
        )
    )
    await session.commit()

    await set_rls_context(session)
    await sync_oidc_assignments(
        session, user_id=newcomer.id, claim_values={"engineering"}
    )
    await session.commit()

    # The claim placed them here, at its own role.
    claimed = await _membership(
        session, guild_id=guild.id, initiative_id=mapped.id, user_id=newcomer.id
    )
    assert claimed is not None and claimed.role_id == mapped_pm.id
    # Nothing claimed this one, so arriving in the guild did.
    enrolled = await _membership(
        session, guild_id=guild.id, initiative_id=unmapped.id, user_id=newcomer.id
    )
    assert enrolled is not None
    # Enrolment's rows stay outside OIDC's remit, so its sweep never reaps them.
    assert enrolled.oidc_managed is False
