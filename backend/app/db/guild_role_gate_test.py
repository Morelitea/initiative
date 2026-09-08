"""The database decides what a member's initiative role may engage.

Each test reads the table with a plain SELECT, carrying no clause of its own,
so what comes back is what the policies allowed.
"""

from __future__ import annotations

import pytest
from sqlmodel import select

from app.db.session import set_rls_context
from app.models.platform.guild import GuildRole
from app.models.tenant.queue import Queue
from app.models.tenant.resource_grant import ResourceAccessLevel, ResourceGrant
from app.testing import create_queue, grant_role_permission
from app.testing.schema_harness import route_session_to_guild

pytestmark = pytest.mark.integration


async def _shared(session, queue, user) -> None:
    """A read grant on the queue — gate 4 satisfied, so only gate 3 is left."""
    await route_session_to_guild(session, queue.guild_id)
    session.add(
        ResourceGrant(
            resource_type="queue",
            resource_id=queue.id,
            user_id=user.id,
            level=ResourceAccessLevel.read,
            guild_id=queue.guild_id,
            initiative_id=queue.initiative_id,
        )
    )
    await session.commit()


async def _names(session, guild_id, actor, *, role: str = "member") -> list[str]:
    """Queue names the database hands back for a bare SELECT."""
    await set_rls_context(
        session, user_id=actor.user.id, guild_id=guild_id, guild_role=role
    )
    return sorted(await session.exec(select(Queue.name)))


async def test_a_role_that_cannot_engage_the_tool_is_refused(session, acting_user):
    """Shared with them, in their initiative — and still not theirs to reach,
    because their role does not hold Queues."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    b = await acting_user(
        guild_role=GuildRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )
    queue = await create_queue(session, a.initiative, a.user, name="Vendor intake")
    await _shared(session, queue, b.user)

    assert await _names(session, a.guild.id, b) == []


async def test_the_role_permission_admits_them(session, acting_user):
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    b = await acting_user(
        guild_role=GuildRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )
    queue = await create_queue(session, a.initiative, a.user, name="Vendor intake")
    await _shared(session, queue, b.user)
    await grant_role_permission(session, a.initiative, "queues_enabled")

    assert await _names(session, a.guild.id, b) == ["Vendor intake"]


async def test_a_manager_role_needs_no_row(session, acting_user):
    """A manager holds every key whether or not one is stored — the same rule
    the application's resolver applies."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    b = await acting_user(
        guild_role=GuildRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="project_manager",
    )
    queue = await create_queue(session, a.initiative, a.user, name="Vendor intake")
    await _shared(session, queue, b.user)

    assert await _names(session, a.guild.id, b) == ["Vendor intake"]


async def test_the_routed_guild_admin_still_reaches_it(session, acting_user):
    """Guild admin sits above all four gates."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await create_queue(session, a.initiative, a.user, name="Vendor intake")

    assert await _names(session, a.guild.id, a, role="admin") == ["Vendor intake"]
