"""Guests: a membership row with an end. It admits its holder until then,
takes no seat, and only on the demo deployment carries a rung above ``guest``."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func
from sqlmodel import select

from app.core.messages import GuildMessages
from app.models.platform.guild import CommunityRole, GuildMembership
from app.models.platform.user_profile_view import MemberProfile
from app.services.platform import app_settings as app_settings_service
from app.services.platform import guests
from app.services.platform import guilds as guilds_service
from app.services.platform import users as users_service
from app.testing import create_guild_membership, create_user, get_auth_headers

HOUR = timedelta(hours=1)


async def _platform(session, *, guests_enabled: bool = True, demo_mode: bool = False):
    row = await app_settings_service.ensure_settings_row(session)
    row.guests_enabled = guests_enabled
    row.demo_mode = demo_mode
    session.add(row)
    await session.commit()


async def _guest(session, guild, *, role=CommunityRole.admin, ends_in=HOUR):
    user = await create_user(session)
    await create_guild_membership(
        session,
        user=user,
        guild=guild,
        role=role,
        guest_until=datetime.now(timezone.utc) + ends_in,
    )
    return user


@pytest.mark.parametrize(
    ("guests_enabled", "demo_mode", "ends_in", "admitted"),
    [
        (True, True, HOUR, True),
        (True, True, -HOUR, False),
        # Guests are off on the platform.
        (False, True, HOUR, False),
        # A rung above guest, away from the demo deployment.
        (True, False, HOUR, False),
    ],
)
async def test_a_guest_is_admitted_until_its_end_and_as_the_platform_allows(
    client, acting_user, session, guests_enabled, demo_mode, ends_in, admitted
):
    a = await acting_user(guild_role=CommunityRole.admin)
    await _platform(session, guests_enabled=guests_enabled, demo_mode=demo_mode)
    guest = await _guest(
        session, a.guild, role=CommunityRole.superadmin, ends_in=ends_in
    )
    guild_id, guest_id = a.guild.id, guest.id

    response = await client.get(
        f"/api/v1/c/{guild_id}/initiatives/", headers=get_auth_headers(guest)
    )
    holds_seat = (
        await session.exec(select(func.guild_superadmin(guild_id, guest_id)))
    ).one()

    assert response.status_code == (200 if admitted else 403), response.text
    assert holds_seat is admitted


async def test_the_guest_rung_reaches_nothing_yet(client, acting_user, session):
    a = await acting_user(guild_role=CommunityRole.admin)
    await _platform(session)
    guest = await _guest(session, a.guild, role=CommunityRole.guest)

    response = await client.get(
        f"/api/v1/c/{a.guild.id}/initiatives/", headers=get_auth_headers(guest)
    )

    assert response.status_code == 403


async def test_guests_take_no_seat_and_are_not_on_the_roster(acting_user, session):
    a = await acting_user(guild_role=CommunityRole.admin)
    await _platform(session, demo_mode=True)
    await _guest(session, a.guild)
    await _guest(session, a.guild, role=CommunityRole.guest)
    guild_id = a.guild.id

    listed = (
        await session.exec(
            users_service.guild_members(select(MemberProfile.id), guild_id=guild_id)
        )
    ).all()

    assert await guilds_service.count_members(session, guild_id=guild_id) == 1
    assert await guilds_service.count_members_by_guild(
        session, guild_ids=[guild_id]
    ) == {guild_id: 1}
    assert listed == [a.user.id]


async def test_an_ended_guest_is_swept_away(acting_user, session):
    a = await acting_user(guild_role=CommunityRole.admin)
    await _platform(session)
    ended = await _guest(session, a.guild, role=CommunityRole.guest, ends_in=-HOUR)
    staying = await _guest(session, a.guild, role=CommunityRole.guest)
    guild_id, ended_id, staying_id = a.guild.id, ended.id, staying.id

    await guests.end_expired_guests()

    session.expire_all()
    remaining = set(
        (
            await session.exec(
                select(GuildMembership.user_id).where(
                    GuildMembership.guild_id == guild_id
                )
            )
        ).all()
    )
    assert staying_id in remaining and ended_id not in remaining


async def test_a_guest_rung_is_not_changed_as_a_member_role(
    client, acting_user, session
):
    a = await acting_user(guild_role=CommunityRole.superadmin)
    await _platform(session)
    guest = await _guest(session, a.guild, role=CommunityRole.guest)

    response = await client.patch(
        f"/api/v1/communities/{a.guild.id}/members/{guest.id}",
        json={"role": "member"},
        headers=a.headers,
    )

    assert response.status_code == 400
    assert response.json()["detail"] == GuildMessages.COMMUNITY_ROLE_NOT_ASSIGNABLE


async def test_boot_records_whether_this_is_the_demo(session):
    for demo_mode in (True, False):
        await app_settings_service.record_running_version(
            session, version="9.9.9", demo_mode=demo_mode
        )
        await session.commit()
        row = await app_settings_service.ensure_settings_row(session)
        assert row.demo_mode is demo_mode
