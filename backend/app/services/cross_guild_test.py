"""Tests for the cross-guild resolver tooling (`resolve_across_guilds`)."""

import pytest
from sqlalchemy import inspect as sa_inspect
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.guild import GuildRole
from app.models.initiative import Initiative
from app.services.cross_guild import resolve_across_guilds
from app.testing.factories import (
    create_guild,
    create_guild_membership,
    create_initiative,
    create_user,
)


async def _two_guilds_with_colliding_initiatives(session: AsyncSession):
    """A user in guilds A and B, each holding an initiative with the SAME
    per-schema id (fresh schemas → colliding serials)."""
    user = await create_user(session, email="resolver@example.com")
    guild_a = await create_guild(session, creator=user, name="Resolver A")
    await create_guild_membership(
        session, user=user, guild=guild_a, role=GuildRole.admin
    )
    init_a = await create_initiative(session, guild_a, user, name="Resolver Init A")

    guild_b = await create_guild(session, creator=user, name="Resolver B")
    await create_guild_membership(
        session, user=user, guild=guild_b, role=GuildRole.admin
    )
    init_b = await create_initiative(session, guild_b, user, name="Resolver Init B")

    assert init_a.id == init_b.id, "test requires colliding per-schema ids"
    return user, guild_a, init_a, guild_b, init_b


def _fetch_initiative(entity_id: int):
    async def _fetch(s: AsyncSession, gid: int):
        return (
            await s.exec(
                select(Initiative).where(
                    Initiative.id == entity_id, Initiative.guild_id == gid
                )
            )
        ).one_or_none()

    return _fetch


@pytest.mark.integration
async def test_resolver_returns_attached_winner_from_earlier_probe(
    session: AsyncSession,
) -> None:
    """The structural guarantee: even when the winner came from a guild probed
    BEFORE later probes expunged it, the returned instance is re-fetched and
    ATTACHED — never a detached probe-time leftover."""
    (
        user,
        guild_a,
        init_a,
        guild_b,
        _init_b,
    ) = await _two_guilds_with_colliding_initiatives(session)

    seen: list[list[int]] = []

    def _choose(candidates):
        seen.append([gid for gid, _ in candidates])
        return guild_a.id  # the FIRST-probed guild (detached by B's probe)

    resolved = await resolve_across_guilds(
        session,
        user.id,
        sorted([guild_a.id, guild_b.id]),
        _fetch_initiative(init_a.id),
        _choose,
        superadmin=True,
    )
    assert resolved is not None
    winner_gid, winner = resolved

    # choose saw every candidate, in probe order.
    assert seen == [sorted([guild_a.id, guild_b.id])]
    assert winner_gid == guild_a.id
    assert winner.guild_id == guild_a.id
    assert winner.name == "Resolver Init A"
    # The invariant under test: attached, not a detached probe-time object.
    assert not sa_inspect(winner).detached

    # The session is left routed to the winner's schema: a follow-up bare query
    # for the colliding id resolves to the winner's row.
    followup = (
        await session.exec(select(Initiative).where(Initiative.id == init_a.id))
    ).one_or_none()
    assert followup is not None and followup.guild_id == guild_a.id


@pytest.mark.integration
async def test_resolver_choose_may_refuse_and_misses_return_none(
    session: AsyncSession,
) -> None:
    """choose() exceptions propagate (selection policy belongs to the caller),
    and an id matching nothing returns None."""
    (
        user,
        guild_a,
        init_a,
        guild_b,
        _init_b,
    ) = await _two_guilds_with_colliding_initiatives(session)

    class Refused(Exception):
        pass

    def _refuse(_candidates):
        raise Refused()

    with pytest.raises(Refused):
        await resolve_across_guilds(
            session,
            user.id,
            [guild_a.id, guild_b.id],
            _fetch_initiative(init_a.id),
            _refuse,
            superadmin=True,
        )

    missing = await resolve_across_guilds(
        session,
        user.id,
        [guild_a.id, guild_b.id],
        _fetch_initiative(99_999),
        lambda candidates: candidates[0][0],
        superadmin=True,
    )
    assert missing is None
