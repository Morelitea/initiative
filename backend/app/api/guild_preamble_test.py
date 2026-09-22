"""What a guild request spends before its first real query.

``establish_guild_access`` (and the REST dependency chain that composes the
same two primitives) has to do two things before a handler runs: decide the
request may operate in this guild, and route the session into it. Both are
made of database calls, so the cost is round trips, and the preamble is paid
by every guild-addressed request there is.

Two rules keep it from creeping back:

- ``guild_memberships``, ``guilds`` and ``guild_auth_policies`` all live in
  ``public`` and are all keyed on the guild the request addresses, so the gate
  reads them together — and the settings singleton rides with them, because
  what the deployment asks of an account is decided in the same breath.
- The routing is written once. The "Full access" initiative set is the one
  value that is only knowable after the routing lands, so the statement that
  resolves it writes its own GUC and leaves the other twelve alone.
"""

from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from sqlalchemy import event, text
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import establish_guild_access
from app.models.platform.guild import GuildRole


@contextmanager
def _statements(session: AsyncSession) -> Iterator[list[str]]:
    """Every statement ``session`` sends while the block runs."""
    seen: list[str] = []
    engine = session.sync_session.get_bind()

    def record(conn, cursor, statement, parameters, context, executemany) -> None:
        seen.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    try:
        yield seen
    finally:
        event.remove(engine, "before_cursor_execute", record)


@pytest.mark.database
async def test_member_preamble_round_trips(session, role_session, acting_user):
    """A member's preamble: reset + context, the gate's one read, reset +
    context for the routing, and the statement that resolves the "Full access"
    set into its own GUC. Six, and a handler's first query is the seventh."""
    a = await acting_user(guild_role=GuildRole.member, initiative=True)

    s = await role_session("app_user")
    # Establish the connection first so the pool's own setup isn't counted.
    await s.exec(text("SELECT 1"))

    with _statements(s) as sent:
        await establish_guild_access(
            s, a.user, a.guild.id, satisfied_providers=frozenset()
        )

    assert len(sent) == 6, "preamble round trips:\n" + "\n".join(sent)
    # The public rows the gate needs come back together — the deployment's own
    # second-factor answer among them, rather than as a read of its own on
    # every guild request there is.
    (gate_read,) = [
        stmt
        for stmt in sent
        if "guild_memberships" in stmt and "guild_auth_policies" in stmt
    ]
    assert "guild_auth_policies" in gate_read
    assert "app_settings" in gate_read
    assert sum("app_settings" in stmt for stmt in sent) == 1
    # ...and the "Full access" set is resolved and recorded in one statement,
    # rather than read and then written back through the whole context, which
    # is why the full context is written once and not twice.
    (override,) = [stmt for stmt in sent if "initiative_members" in stmt]
    assert override.lstrip().startswith("SELECT")
    assert "set_config(" in override
    # Three mentions, and each is one of the three steps: the gate's own
    # context, the routing, and the standing reading back the community the
    # routing just named.
    assert sum("app.current_guild_id" in stmt for stmt in sent) == 3


@pytest.mark.database
async def test_full_access_initiative_reaches_the_guc(
    session, role_session, acting_user
):
    """The fused statement is still the same answer: a member on a role that
    overrides sharing has that initiative in the GUC the policies read, and an
    ordinary member has an empty one."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    full = await acting_user(
        guild_role=GuildRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="moderator",
        email="full@example.com",
    )
    plain = await acting_user(
        guild_role=GuildRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
        email="plain@example.com",
    )

    s = await role_session("app_user")
    await establish_guild_access(
        s, full.user, a.guild.id, satisfied_providers=frozenset()
    )
    assert (
        await s.exec(text("SELECT current_setting('app.override_initiatives', true)"))
    ).scalar() == str(a.initiative.id)

    t = await role_session("app_user")
    await establish_guild_access(
        t, plain.user, a.guild.id, satisfied_providers=frozenset()
    )
    assert (
        await t.exec(text("SELECT current_setting('app.override_initiatives', true)"))
    ).scalar() == ""
