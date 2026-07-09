"""Regression tests for transaction-local RLS context (#784).

The contract under test (see history/transaction-scoped-context-design.md):

- Context is applied with ``set_config(..., is_local=true)`` and REPLAYED at
  the start of every transaction by the ``after_begin`` hook — so a
  ``commit()`` followed by a query needs no manual ``reapply_rls_context``.
- Nothing session-level ever exists: with the stored params removed, the
  connection reverts to the bare login role and empty GUCs.
- A *user-derived* snapshot older than ``RLS_CONTEXT_MAX_AGE_SECONDS`` fails
  closed (``StaleAuthorizationContext``) at transaction begin; system
  contexts (no user) are exempt.
"""

import pytest
from sqlalchemy import text
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.schema_provisioning import guild_role_name
from app.db.session import (
    _RLS_ESTABLISHED_INFO_KEY,
    _RLS_PARAMS_INFO_KEY,
    RLS_CONTEXT_MAX_AGE_SECONDS,
    StaleAuthorizationContext,
    set_rls_context,
)
from app.models.platform.guild import GuildRole
from app.testing import create_guild, create_guild_membership, create_user
from app.testing.schema_harness import route_session_to_guild


async def _scalar(session: AsyncSession, sql: str):
    return (await session.exec(text(sql))).scalar()


@pytest.mark.database
async def test_commit_then_query_replays_context(session, role_session):
    """The core rule-2 regression: routed session → commit → tenant query
    succeeds with NO manual reapply (the after_begin hook replays context on
    the new transaction)."""
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    await create_guild_membership(session, user=user, guild=guild)

    s = await role_session("app_user")
    await set_rls_context(
        s, user_id=user.id, guild_id=guild.id, guild_role=GuildRole.admin.value
    )
    assert await _scalar(s, "SELECT count(*) FROM projects") is not None
    await s.commit()
    # Previously this required reapply_rls_context(s); now it must just work.
    assert await _scalar(s, "SELECT count(*) FROM projects") is not None
    assert (await _scalar(s, "SELECT current_setting('search_path')")).startswith(
        f"guild_{guild.id}"
    )


@pytest.mark.database
async def test_context_dies_with_transaction(session, role_session):
    """No session-level state: with the stored params removed (no replay),
    the connection is back to the login role, public search_path, empty GUCs."""
    user = await create_user(session)
    guild = await create_guild(session, creator=user)

    s = await role_session("app_user")
    await set_rls_context(
        s, user_id=user.id, guild_id=guild.id, guild_role=GuildRole.admin.value
    )
    assert (await _scalar(s, "SELECT current_user")) == guild_role_name(guild.id)
    await s.commit()

    del s.info[_RLS_PARAMS_INFO_KEY]  # disable replay: probe the bare connection
    assert (await _scalar(s, "SELECT current_user")) != guild_role_name(guild.id)
    assert (
        await _scalar(s, "SELECT current_setting('app.current_user_id', true)")
    ) in (
        "",
        None,
    )
    assert "guild_" not in (await _scalar(s, "SELECT current_setting('search_path')"))


@pytest.mark.database
async def test_stale_user_snapshot_fails_closed(session, role_session):
    """A user-derived snapshot past the freshness floor refuses to begin a
    transaction — the DB-layer floor under the realtime spine."""
    user = await create_user(session)
    guild = await create_guild(session, creator=user)

    s = await role_session("app_user")
    await set_rls_context(
        s, user_id=user.id, guild_id=guild.id, guild_role=GuildRole.member.value
    )
    await s.commit()
    s.info[_RLS_ESTABLISHED_INFO_KEY] -= RLS_CONTEXT_MAX_AGE_SECONDS + 1

    with pytest.raises(StaleAuthorizationContext):
        await s.exec(text("SELECT 1"))


@pytest.mark.database
async def test_system_context_exempt_from_ttl(session, role_session):
    """A system context (no user_id — worker loops, seeding) is not a user
    authorization snapshot; the floor must not break a long maintenance pass."""
    user = await create_user(session)
    guild = await create_guild(session, creator=user)

    s = await role_session("app_admin")
    await set_rls_context(s, guild_id=guild.id, guild_role=GuildRole.admin.value)
    await s.commit()
    s.info[_RLS_ESTABLISHED_INFO_KEY] -= RLS_CONTEXT_MAX_AGE_SECONDS + 1

    assert await _scalar(s, "SELECT count(*) FROM projects") is not None


@pytest.mark.database
async def test_mid_transaction_reroute(session, role_session):
    """cross_guild-style loops re-route guild A → guild B inside one
    transaction; the direct application must win over the replayed context."""
    user = await create_user(session)
    guild_a = await create_guild(session, creator=user)
    guild_b = await create_guild(session, creator=user)

    s = await role_session("app_user")
    await set_rls_context(
        s, user_id=user.id, guild_id=guild_a.id, guild_role=GuildRole.admin.value
    )
    assert f"guild_{guild_a.id}" in await _scalar(
        s, "SELECT current_setting('search_path')"
    )
    await set_rls_context(
        s, user_id=user.id, guild_id=guild_b.id, guild_role=GuildRole.admin.value
    )
    assert f"guild_{guild_b.id}" in await _scalar(
        s, "SELECT current_setting('search_path')"
    )
    assert (await _scalar(s, "SELECT current_user")) == guild_role_name(guild_b.id)


@pytest.mark.database
async def test_nested_transaction_inherits_context(session, role_session):
    """SET LOCAL scopes to the top-level transaction; a savepoint must inherit
    the routed context (the hook skips nested begins)."""
    user = await create_user(session)
    guild = await create_guild(session, creator=user)

    s = await role_session("app_user")
    await set_rls_context(
        s, user_id=user.id, guild_id=guild.id, guild_role=GuildRole.admin.value
    )
    async with s.begin_nested():
        assert await _scalar(s, "SELECT count(*) FROM projects") is not None
        assert f"guild_{guild.id}" in await _scalar(
            s, "SELECT current_setting('search_path')"
        )


@pytest.mark.database
async def test_harness_pin_survives_commit(session):
    """route_session_to_guild pins are transaction-local but replayed: a
    factory-routed test session still resolves the guild schema after commit."""
    user = await create_user(session)
    guild = await create_guild(session, creator=user)

    await route_session_to_guild(session, guild.id)
    await session.commit()
    sp = (await session.exec(text("SELECT current_setting('search_path')"))).scalar()
    assert f"guild_{guild.id}" in sp
