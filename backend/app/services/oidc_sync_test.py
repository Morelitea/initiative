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
from app.models.platform.guild import GuildMembership, GuildRole
from app.models.platform.oidc_claim_mapping import (
    OIDCClaimMapping,
    OIDCMappingTargetType,
)
from app.models.tenant.initiative import InitiativeMember
from app.services.oidc_sync import sync_oidc_assignments
from app.services.tenant.initiatives import get_pm_role
from app.testing.factories import (
    create_auth_provider,
    create_guild,
    create_initiative,
    create_user,
)


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
    provider = await create_auth_provider(session)
    owner = await create_user(session)
    guild = await create_guild(session, creator=owner)
    initiative = await create_initiative(
        session, guild, owner, name="Onboarding", join_policy="open", auto_join=True
    )
    pm_role = await get_pm_role(session, initiative_id=initiative.id)

    newcomer = await create_user(session)
    session.add(
        OIDCClaimMapping(
            provider_id=provider.id,
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
        session,
        user_id=newcomer.id,
        provider_id=provider.id,
        claim_values={"engineering"},
    )
    await session.commit()

    membership = await _membership(
        session, guild_id=guild.id, initiative_id=initiative.id, user_id=newcomer.id
    )
    assert membership is not None
    # The claim's role, not the built-in member role enrolment hands out.
    assert membership.role_id == pm_role.id
    assert membership.oidc_provider_id == provider.id


@pytest.mark.integration
async def test_a_guild_provider_grants_only_inside_its_own_guild(session: AsyncSession):
    """A guild configures its own provider, so that provider's sign-in reads the
    rules naming that guild. One of its rules naming a different guild is not
    part of the sign-in, and grants nothing."""
    owner = await create_user(session)
    home = await create_guild(session, creator=owner)
    elsewhere = await create_guild(session, creator=owner)
    provider = await create_auth_provider(session, slug="tenant", guild_id=home.id)

    newcomer = await create_user(session)
    for guild_id in (home.id, elsewhere.id):
        session.add(
            OIDCClaimMapping(
                provider_id=provider.id,
                claim_value="staff",
                target_type=OIDCMappingTargetType.guild,
                guild_id=guild_id,
                guild_role=GuildRole.admin.value,
            )
        )
    await session.commit()

    await set_rls_context(session)
    result = await sync_oidc_assignments(
        session,
        user_id=newcomer.id,
        provider_id=provider.id,
        claim_values={"staff"},
    )
    await session.commit()

    assert result.guilds_added == [home.id]
    joined = set(
        (
            await session.exec(
                select(GuildMembership.guild_id).where(
                    GuildMembership.user_id == newcomer.id
                )
            )
        ).all()
    )
    assert joined == {home.id}


@pytest.mark.integration
async def test_auto_join_still_covers_what_the_claims_do_not(session: AsyncSession):
    """Enrolment fills the gaps the mapping left, and only those."""
    provider = await create_auth_provider(session)
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
            provider_id=provider.id,
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
        session,
        user_id=newcomer.id,
        provider_id=provider.id,
        claim_values={"engineering"},
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
    assert enrolled.oidc_provider_id is None


@pytest.mark.integration
async def test_one_providers_sign_in_leaves_anothers_memberships_alone(
    session: AsyncSession,
):
    """Two providers, one account, and a sign-in through each in turn.

    The sync both grants and reclaims, so a rule set that is not this
    provider's must reach neither half: signing in through one must not read
    the other's rules, and must not take back what the other's rules gave.
    """
    from app.models.platform.guild import GuildMembership

    corp = await create_auth_provider(session, slug="corp")
    partner = await create_auth_provider(session, slug="partner")

    owner = await create_user(session)
    corp_guild = await create_guild(session, creator=owner, name="Corp")
    partner_guild = await create_guild(session, creator=owner, name="Partner")

    person = await create_user(session)
    session.add(
        OIDCClaimMapping(
            provider_id=corp.id,
            claim_value="staff",
            target_type=OIDCMappingTargetType.guild,
            guild_id=corp_guild.id,
            guild_role=GuildRole.member.value,
        )
    )
    session.add(
        OIDCClaimMapping(
            provider_id=partner.id,
            claim_value="vendors",
            target_type=OIDCMappingTargetType.guild,
            guild_id=partner_guild.id,
            guild_role=GuildRole.member.value,
        )
    )
    await session.commit()

    async def _guild_ids() -> set[int]:
        session.expunge_all()
        await set_rls_context(session)
        rows = (
            await session.exec(
                select(GuildMembership.guild_id).where(
                    GuildMembership.user_id == person.id
                )
            )
        ).all()
        return set(rows)

    await set_rls_context(session)
    await sync_oidc_assignments(
        session, user_id=person.id, provider_id=corp.id, claim_values={"staff"}
    )
    await session.commit()
    assert await _guild_ids() == {corp_guild.id}

    # The partner's claims admit them to the partner guild...
    await set_rls_context(session)
    await sync_oidc_assignments(
        session, user_id=person.id, provider_id=partner.id, claim_values={"vendors"}
    )
    await session.commit()
    assert await _guild_ids() == {corp_guild.id, partner_guild.id}

    # ...and signing in through the corporate provider again keeps both. Its
    # claims say nothing about the partner guild because its rules do not
    # mention it, which is not the same as saying the person does not belong.
    await set_rls_context(session)
    await sync_oidc_assignments(
        session, user_id=person.id, provider_id=corp.id, claim_values={"staff"}
    )
    await session.commit()
    assert await _guild_ids() == {corp_guild.id, partner_guild.id}


@pytest.mark.integration
async def test_deleting_the_last_rule_hands_back_what_it_granted(
    session: AsyncSession,
):
    """A provider with no rules grants nothing, which is not the same as having
    nothing to take back. Its next sign-in releases what its rules had given."""
    from app.models.platform.guild import GuildMembership

    provider = await create_auth_provider(session, slug="corp")
    owner = await create_user(session)
    guild = await create_guild(session, creator=owner, name="Corp")
    person = await create_user(session)

    rule = OIDCClaimMapping(
        provider_id=provider.id,
        claim_value="staff",
        target_type=OIDCMappingTargetType.guild,
        guild_id=guild.id,
        guild_role=GuildRole.member.value,
    )
    session.add(rule)
    await session.commit()

    await set_rls_context(session)
    await sync_oidc_assignments(
        session, user_id=person.id, provider_id=provider.id, claim_values={"staff"}
    )
    await session.commit()

    session.expunge_all()
    await set_rls_context(session)
    assert (
        await session.exec(
            select(GuildMembership).where(GuildMembership.user_id == person.id)
        )
    ).all()

    # The operator deletes the rule, and the next sign-in reconciles.
    await session.delete(await session.get(OIDCClaimMapping, rule.id))
    await session.commit()

    await set_rls_context(session)
    await sync_oidc_assignments(
        session, user_id=person.id, provider_id=provider.id, claim_values={"staff"}
    )
    await session.commit()

    session.expunge_all()
    await set_rls_context(session)
    assert not (
        await session.exec(
            select(GuildMembership).where(GuildMembership.user_id == person.id)
        )
    ).all()


@pytest.mark.integration
async def test_stale_provider_claim_preserves_a_promoted_superadmin(
    session: AsyncSession,
):
    provider = await create_auth_provider(session, slug="corp")
    owner = await create_user(session)
    guild = await create_guild(session, creator=owner, name="Corp")
    person = await create_user(session)
    rule = OIDCClaimMapping(
        provider_id=provider.id,
        claim_value="staff",
        target_type=OIDCMappingTargetType.guild,
        guild_id=guild.id,
        guild_role=GuildRole.member.value,
    )
    session.add(rule)
    await session.commit()

    await set_rls_context(session)
    await sync_oidc_assignments(
        session, user_id=person.id, provider_id=provider.id, claim_values={"staff"}
    )
    await session.commit()

    session.expunge_all()
    await set_rls_context(session)
    membership = (
        await session.exec(
            select(GuildMembership).where(
                GuildMembership.user_id == person.id,
                GuildMembership.guild_id == guild.id,
            )
        )
    ).one()
    membership.role = GuildRole.superadmin
    session.add(membership)
    await session.delete(await session.get(OIDCClaimMapping, rule.id))
    await session.commit()

    await set_rls_context(session)
    result = await sync_oidc_assignments(
        session, user_id=person.id, provider_id=provider.id, claim_values={"staff"}
    )

    session.expunge_all()
    await set_rls_context(session)
    preserved = (
        await session.exec(
            select(GuildMembership).where(
                GuildMembership.user_id == person.id,
                GuildMembership.guild_id == guild.id,
            )
        )
    ).one_or_none()
    assert preserved is not None
    assert preserved.role == GuildRole.superadmin
    assert result.guilds_removed == []
