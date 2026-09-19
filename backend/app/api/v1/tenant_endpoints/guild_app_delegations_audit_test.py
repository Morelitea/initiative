"""A member letting an app carry their name, in the audit log.

The subject of one of these is an account rather than a thing, so every record
here names two people: the one who acted, and the member whose authorization it
was. ``via`` is what separates the two ways it can end — the member withdrawing
their own, and the seat ending somebody else's — which is the distinction a
reviewer is reading the log for.
"""

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core import config as config_module
from app.core.audit_events import AuditEventType
from app.models.platform.guild import GuildRole
from app.services.marketplace.registration_lookup import invalidate_registrations
from app.testing import recorded
from app.testing.delegation import install_delegate, register_delegate

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
async def _delegate_registered(session: AsyncSession):
    """An operator has granted the delegate, which is what makes the question
    worth asking a member at all."""
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(
            config_module.settings,
            "APP_PLATFORM_SIGNING_PRIVATE_KEY_PEM",
            "-----BEGIN PRIVATE KEY-----",
        )
        await register_delegate(session)
        yield
    invalidate_registrations()


async def _installed_for(session: AsyncSession, actor):
    return await install_delegate(session, actor.guild, creator=actor.user)


async def _grant(client: AsyncClient, actor, app_id: int, *, can_write: bool = True):
    response = await client.put(
        actor.g(f"/apps/{app_id}/delegation"),
        headers=actor.headers,
        json={"can_write": can_write},
    )
    assert response.status_code == 200, response.text
    return response


async def test_authorizing_records_the_member_and_the_depth(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(guild_role=GuildRole.member)
    app = await _installed_for(session, a)

    await _grant(client, a, app.id, can_write=True)

    (row,) = await recorded(session, AuditEventType.DELEGATION_GRANTED)
    assert row.actor_user_id == a.user.id
    assert row.target_user_id == a.user.id
    assert row.guild_id == a.guild.id
    assert (row.target_type, row.target_id) == ("app", app.id)
    assert row.envelope["detail"] == {"can_write": True, "via": "self"}


async def test_withdrawing_your_own_records_it_as_yours(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(guild_role=GuildRole.member)
    app = await _installed_for(session, a)
    await _grant(client, a, app.id)

    response = await client.delete(a.g(f"/apps/{app.id}/delegation"), headers=a.headers)
    assert response.status_code == 204, response.text

    (row,) = await recorded(session, AuditEventType.DELEGATION_REVOKED)
    assert row.actor_user_id == a.user.id
    assert row.target_user_id == a.user.id
    assert row.guild_id == a.guild.id
    assert (row.target_type, row.target_id) == ("app", app.id)
    assert row.envelope["detail"] == {"via": "self"}


async def test_the_seat_ending_a_members_authorization_names_both_of_them(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(guild_role=GuildRole.superadmin)
    member = await acting_user(guild_role=GuildRole.member, guild=a.guild)
    app = await _installed_for(session, a)
    await _grant(client, member, app.id)

    response = await client.delete(
        a.g(f"/apps/{app.id}/members/{member.user.id}/delegation"), headers=a.headers
    )
    assert response.status_code == 204, response.text

    (row,) = await recorded(session, AuditEventType.DELEGATION_REVOKED)
    assert row.actor_user_id == a.user.id
    assert row.target_user_id == member.user.id
    assert row.envelope["detail"] == {"via": "admin"}


async def test_ending_everyones_records_one_per_member(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """One row per authorization actually withdrawn, each naming its member:
    "everything ever granted to this person" is a query on the target."""
    a = await acting_user(guild_role=GuildRole.superadmin)
    member = await acting_user(guild_role=GuildRole.member, guild=a.guild)
    app = await _installed_for(session, a)
    for actor in (a, member):
        await _grant(client, actor, app.id)

    response = await client.post(
        a.g(f"/apps/{app.id}/delegations/revoke-all"), headers=a.headers
    )
    assert response.status_code == 204, response.text

    rows = await recorded(session, AuditEventType.DELEGATION_REVOKED)
    assert sorted(row.target_user_id for row in rows) == sorted(
        [a.user.id, member.user.id]
    )
    assert {row.actor_user_id for row in rows} == {a.user.id}
    assert [row.envelope["detail"] for row in rows] == [{"via": "admin"}] * 2


async def test_withdrawing_what_was_never_granted_records_nothing(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The endpoint answers the same either way, so the log is what says
    whether anything was in force."""
    a = await acting_user(guild_role=GuildRole.member)
    app = await _installed_for(session, a)

    response = await client.delete(a.g(f"/apps/{app.id}/delegation"), headers=a.headers)
    assert response.status_code == 204, response.text

    assert await recorded(session, AuditEventType.DELEGATION_REVOKED) == []
