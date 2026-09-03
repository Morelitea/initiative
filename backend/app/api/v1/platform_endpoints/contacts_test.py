"""Integration tests for /api/v1/me/contacts."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.app_setting import AppSetting
from app.models.platform.guild import GuildRole
from app.models.platform.profile_favorite import ProfileFavorite
from app.models.platform.user import UserStatus
from app.models.platform.user_dm_settings import DmPolicy
from app.services.platform.app_settings import GLOBAL_SETTINGS_ID
from app.testing.factories import (
    create_guild,
    create_guild_membership,
    create_user,
    get_auth_headers,
)

SECTIONS = "/api/v1/me/contacts"
FAVORITES = "/api/v1/me/contacts/favorites"


@pytest.fixture(autouse=True)
async def community_by_default(session: AsyncSession):
    """Run these against a deployment whose operator default is ``community``.

    A roster names the people the reader could actually reach out to, so on the
    shipped default — ``private`` — every one of these sections is empty and
    the paging, search and naming below have nothing to describe. Setting the
    operator's default here is what gives them members to be about; the default
    itself, and the empty page it makes, are
    ``services/platform/contacts_reachable_test.py``.

    Set before any account is made: the default is copied into the account when
    it is created, and moving it afterwards moves nobody.
    """
    settings = (
        await session.exec(
            select(AppSetting).where(AppSetting.id == GLOBAL_SETTINGS_ID)
        )
    ).one_or_none()
    if settings is None:
        settings = AppSetting(id=GLOBAL_SETTINGS_ID)
        session.add(settings)
    settings.default_dm_policy = DmPolicy.community
    await session.commit()


def _section(payload: dict, guild_id: int) -> dict:
    """The section for one guild, or fail the test saying it is missing."""
    for section in payload["sections"]:
        if section["guild_id"] == guild_id:
            return section
    raise AssertionError(
        f"no section for guild {guild_id}; got "
        f"{[s['guild_id'] for s in payload['sections']]}"
    )


# --- sections ---------------------------------------------------------------


@pytest.mark.integration
async def test_no_guilds_no_sections(client: AsyncClient, session: AsyncSession):
    user = await create_user(session)
    response = await client.get(SECTIONS, headers=get_auth_headers(user))
    assert response.status_code == 200
    assert response.json()["sections"] == []


@pytest.mark.integration
async def test_sections_follow_rail_order(client: AsyncClient, session: AsyncSession):
    """Sections come back in ``GuildMembership.position``, not guild id."""
    user = await create_user(session)
    first = await create_guild(session)
    second = await create_guild(session)
    third = await create_guild(session)
    # Deliberately not id order: the rail is what decides.
    await create_guild_membership(session, user=user, guild=first, position=2)
    await create_guild_membership(session, user=user, guild=second, position=0)
    await create_guild_membership(session, user=user, guild=third, position=1)
    # Somebody else in each, or there would be no section to order.
    for guild in (first, second, third):
        await create_guild_membership(
            session, user=await create_user(session), guild=guild
        )

    response = await client.get(SECTIONS, headers=get_auth_headers(user))
    assert response.status_code == 200
    assert [s["guild_id"] for s in response.json()["sections"]] == [
        second.id,
        third.id,
        first.id,
    ]


@pytest.mark.integration
async def test_a_guild_the_caller_left_has_no_section(
    client: AsyncClient, session: AsyncSession
):
    user = await create_user(session)
    mine = await create_guild(session)
    theirs = await create_guild(session)
    await create_guild_membership(session, user=user, guild=mine)
    await create_guild_membership(session, user=await create_user(session), guild=mine)

    response = await client.get(SECTIONS, headers=get_auth_headers(user))
    ids = [s["guild_id"] for s in response.json()["sections"]]
    assert ids == [mine.id]
    assert theirs.id not in ids


@pytest.mark.integration
async def test_caller_is_not_their_own_contact(
    client: AsyncClient, session: AsyncSession
):
    user = await create_user(session)
    guild = await create_guild(session)
    await create_guild_membership(session, user=user, guild=guild)
    other = await create_user(session)
    await create_guild_membership(session, user=other, guild=guild)

    response = await client.get(SECTIONS, headers=get_auth_headers(user))
    section = _section(response.json(), guild.id)
    assert [item["id"] for item in section["items"]] == [other.id]


@pytest.mark.integration
async def test_suspended_member_drops_out(client: AsyncClient, session: AsyncSession):
    user = await create_user(session)
    guild = await create_guild(session)
    await create_guild_membership(session, user=user, guild=guild)
    other = await create_user(session)
    await create_guild_membership(session, user=other, guild=guild)

    other.status = UserStatus.suspended
    session.add(other)
    await session.commit()

    response = await client.get(SECTIONS, headers=get_auth_headers(user))
    section = _section(response.json(), guild.id)
    assert section["items"] == []
    assert section["total_count"] == 0


@pytest.mark.integration
async def test_sections_page_within_each_guild(
    client: AsyncClient, session: AsyncSession
):
    """Paging is per section — a flat offset across a merged list would not
    mean anything for a grouped response."""
    user = await create_user(session)
    guild = await create_guild(session)
    await create_guild_membership(session, user=user, guild=guild)
    for index in range(5):
        member = await create_user(session, username=f"member{index}")
        await create_guild_membership(session, user=member, guild=guild)

    headers = get_auth_headers(user)
    first = await client.get(f"{SECTIONS}?page=1&page_size=2", headers=headers)
    section = _section(first.json(), guild.id)
    assert len(section["items"]) == 2
    assert section["total_count"] == 5
    assert section["has_next"] is True

    last = await client.get(f"{SECTIONS}?page=3&page_size=2", headers=headers)
    section = _section(last.json(), guild.id)
    assert len(section["items"]) == 1
    assert section["has_next"] is False


@pytest.mark.integration
async def test_guild_ids_narrows_to_one_section(
    client: AsyncClient, session: AsyncSession
):
    user = await create_user(session)
    first = await create_guild(session)
    second = await create_guild(session)
    await create_guild_membership(session, user=user, guild=first, position=0)
    await create_guild_membership(session, user=user, guild=second, position=1)
    for guild in (first, second):
        await create_guild_membership(
            session, user=await create_user(session), guild=guild
        )

    response = await client.get(
        f"{SECTIONS}?guild_ids={second.id}", headers=get_auth_headers(user)
    )
    assert [s["guild_id"] for s in response.json()["sections"]] == [second.id]


# --- names, per guild -------------------------------------------------------


@pytest.mark.integration
async def test_each_guild_names_people_its_own_way(
    client: AsyncClient, session: AsyncSession
):
    """One response, two guilds, one person — named by each guild's setting."""
    user = await create_user(session)
    shows = await create_guild(session, show_member_names=True)
    hides = await create_guild(session, show_member_names=False)
    await create_guild_membership(session, user=user, guild=shows, position=0)
    await create_guild_membership(session, user=user, guild=hides, position=1)

    other = await create_user(session, full_name="Ada Lovelace")
    await create_guild_membership(session, user=other, guild=shows)
    await create_guild_membership(session, user=other, guild=hides)

    payload = (await client.get(SECTIONS, headers=get_auth_headers(user))).json()
    assert _section(payload, shows.id)["items"][0]["full_name"] == "Ada Lovelace"
    assert _section(payload, hides.id)["items"][0]["full_name"] is None


# --- the shared-guild chip --------------------------------------------------


@pytest.mark.integration
async def test_shared_guilds_named_on_every_appearance(
    client: AsyncClient, session: AsyncSession
):
    user = await create_user(session)
    guilds = [await create_guild(session) for _ in range(3)]
    for position, guild in enumerate(guilds):
        await create_guild_membership(
            session, user=user, guild=guild, position=position
        )

    other = await create_user(session)
    for guild in guilds:
        await create_guild_membership(session, user=other, guild=guild)

    payload = (await client.get(SECTIONS, headers=get_auth_headers(user))).json()
    expected = [guild.id for guild in guilds]
    for guild in guilds:
        section = _section(payload, guild.id)
        assert [item["id"] for item in section["items"]] == [other.id]
        # Every appearance names the full set, in rail order; the chip is what
        # drops the section's own guild.
        assert section["items"][0]["shared_guild_ids"] == expected


@pytest.mark.integration
async def test_shared_guilds_stable_across_pages(
    client: AsyncClient, session: AsyncSession
):
    """The map is read from memberships, not from the rows on the page.

    ``other`` is last alphabetically in the big guild, so it only appears on a
    later page there — and its chip must be the same on both.
    """
    user = await create_user(session)
    big = await create_guild(session)
    small = await create_guild(session)
    await create_guild_membership(session, user=user, guild=big, position=0)
    await create_guild_membership(session, user=user, guild=small, position=1)

    for index in range(4):
        filler = await create_user(session, username=f"aaa{index}")
        await create_guild_membership(session, user=filler, guild=big)

    other = await create_user(session, username="zzztail")
    await create_guild_membership(session, user=other, guild=big)
    await create_guild_membership(session, user=other, guild=small)

    headers = get_auth_headers(user)
    expected = [big.id, small.id]

    page_one = await client.get(f"{SECTIONS}?page=1&page_size=2", headers=headers)
    small_section = _section(page_one.json(), small.id)
    assert small_section["items"][0]["shared_guild_ids"] == expected
    # ...and ``other`` is not even on the big guild's first page.
    assert other.id not in [i["id"] for i in _section(page_one.json(), big.id)["items"]]

    page_three = await client.get(f"{SECTIONS}?page=3&page_size=2", headers=headers)
    big_section = _section(page_three.json(), big.id)
    assert [i["id"] for i in big_section["items"]] == [other.id]
    assert big_section["items"][0]["shared_guild_ids"] == expected


@pytest.mark.integration
async def test_shared_guilds_never_names_a_guild_the_caller_is_not_in(
    client: AsyncClient, session: AsyncSession
):
    user = await create_user(session)
    ours = await create_guild(session)
    await create_guild_membership(session, user=user, guild=ours)

    other = await create_user(session)
    await create_guild_membership(session, user=other, guild=ours)
    # A guild the subject is in and the caller is not.
    elsewhere = await create_guild(session)
    await create_guild_membership(session, user=other, guild=elsewhere)

    payload = (await client.get(SECTIONS, headers=get_auth_headers(user))).json()
    section = _section(payload, ours.id)
    assert section["items"][0]["shared_guild_ids"] == [ours.id]
    assert elsewhere.id not in section["items"][0]["shared_guild_ids"]


# --- search -----------------------------------------------------------------


@pytest.mark.integration
async def test_search_finds_someone_past_the_first_page(
    client: AsyncClient, session: AsyncSession
):
    """The reason search is server-side: a client filter over the loaded page
    could not reach this person."""
    user = await create_user(session)
    guild = await create_guild(session)
    await create_guild_membership(session, user=user, guild=guild)
    for index in range(6):
        filler = await create_user(session, username=f"aaa{index}")
        await create_guild_membership(session, user=filler, guild=guild)
    target = await create_user(session, username="zzzneedle")
    await create_guild_membership(session, user=target, guild=guild)

    headers = get_auth_headers(user)
    unsearched = await client.get(f"{SECTIONS}?page=1&page_size=3", headers=headers)
    assert target.id not in [
        i["id"] for i in _section(unsearched.json(), guild.id)["items"]
    ]

    searched = await client.get(
        f"{SECTIONS}?search=zzzneedle&page=1&page_size=3", headers=headers
    )
    section = _section(searched.json(), guild.id)
    assert [i["id"] for i in section["items"]] == [target.id]


@pytest.mark.integration
async def test_search_hides_sections_with_no_match(
    client: AsyncClient, session: AsyncSession
):
    user = await create_user(session)
    hit = await create_guild(session)
    miss = await create_guild(session)
    await create_guild_membership(session, user=user, guild=hit, position=0)
    await create_guild_membership(session, user=user, guild=miss, position=1)

    target = await create_user(session, username="findme")
    await create_guild_membership(session, user=target, guild=hit)
    bystander = await create_user(session, username="somebody")
    await create_guild_membership(session, user=bystander, guild=miss)

    response = await client.get(
        f"{SECTIONS}?search=findme", headers=get_auth_headers(user)
    )
    assert [s["guild_id"] for s in response.json()["sections"]] == [hit.id]


@pytest.mark.integration
async def test_search_matches_real_name_only_where_the_guild_shows_names(
    client: AsyncClient, session: AsyncSession
):
    user = await create_user(session)
    shows = await create_guild(session, show_member_names=True)
    hides = await create_guild(session, show_member_names=False)
    await create_guild_membership(session, user=user, guild=shows, position=0)
    await create_guild_membership(session, user=user, guild=hides, position=1)

    other = await create_user(session, username="qqqhandle", full_name="Ada Lovelace")
    await create_guild_membership(session, user=other, guild=shows)
    await create_guild_membership(session, user=other, guild=hides)

    response = await client.get(
        f"{SECTIONS}?search=Lovelace", headers=get_auth_headers(user)
    )
    assert [s["guild_id"] for s in response.json()["sections"]] == [shows.id]


# --- favorites --------------------------------------------------------------


@pytest.mark.integration
async def test_favorites_start_empty(client: AsyncClient, session: AsyncSession):
    user = await create_user(session)
    response = await client.get(FAVORITES, headers=get_auth_headers(user))
    assert response.status_code == 200
    assert response.json() == {"items": [], "total_count": 0}


@pytest.mark.integration
async def test_favorite_roundtrip_and_idempotence(
    client: AsyncClient, session: AsyncSession
):
    user = await create_user(session)
    other = await create_user(session)
    headers = get_auth_headers(user)

    assert (
        await client.put(f"{FAVORITES}/{other.id}", headers=headers)
    ).status_code == 204
    # Starring twice is a no-op, not a conflict.
    assert (
        await client.put(f"{FAVORITES}/{other.id}", headers=headers)
    ).status_code == 204

    listed = (await client.get(FAVORITES, headers=headers)).json()
    assert [item["id"] for item in listed["items"]] == [other.id]
    assert listed["total_count"] == 1

    assert (
        await client.delete(f"{FAVORITES}/{other.id}", headers=headers)
    ).status_code == 204
    assert (await client.get(FAVORITES, headers=headers)).json()["items"] == []
    # Unstarring what is not starred is a no-op too.
    assert (
        await client.delete(f"{FAVORITES}/{other.id}", headers=headers)
    ).status_code == 204


@pytest.mark.integration
async def test_favorite_survives_the_row_appearing_underneath_it(
    client: AsyncClient, session: AsyncSession
):
    """Two stars of the same person arriving together both find nothing.

    The pair is the primary key and the insert defers to it, so the second one
    settles as a no-op rather than as a server error.
    """
    user = await create_user(session)
    other = await create_user(session)

    session.add(ProfileFavorite(user_id=user.id, favorite_user_id=other.id))
    await session.commit()

    response = await client.put(
        f"{FAVORITES}/{other.id}", headers=get_auth_headers(user)
    )
    assert response.status_code == 204

    rows = (
        await session.exec(
            select(ProfileFavorite).where(ProfileFavorite.user_id == user.id)
        )
    ).all()
    assert len(rows) == 1


@pytest.mark.integration
async def test_favorite_someone_sharing_no_guild(
    client: AsyncClient, session: AsyncSession
):
    """Any profile may be starred — the list is not a subset of the rosters."""
    user = await create_user(session)
    stranger = await create_user(session)
    headers = get_auth_headers(user)

    assert (
        await client.put(f"{FAVORITES}/{stranger.id}", headers=headers)
    ).status_code == 204
    listed = (await client.get(FAVORITES, headers=headers)).json()
    assert [item["id"] for item in listed["items"]] == [stranger.id]
    # ...and they are in no section, because the caller is in no guild with them.
    assert (await client.get(SECTIONS, headers=headers)).json()["sections"] == []


@pytest.mark.integration
async def test_cannot_favorite_self(client: AsyncClient, session: AsyncSession):
    user = await create_user(session)
    response = await client.put(
        f"{FAVORITES}/{user.id}", headers=get_auth_headers(user)
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "CONTACT_CANNOT_FAVORITE_SELF"


@pytest.mark.integration
async def test_favorite_unknown_user(client: AsyncClient, session: AsyncSession):
    user = await create_user(session)
    response = await client.put(f"{FAVORITES}/98765432", headers=get_auth_headers(user))
    assert response.status_code == 404
    assert response.json()["detail"] == "CONTACT_USER_NOT_FOUND"


@pytest.mark.integration
async def test_suspended_favorite_drops_out_and_returns(
    client: AsyncClient, session: AsyncSession
):
    user = await create_user(session)
    other = await create_user(session)
    headers = get_auth_headers(user)
    await client.put(f"{FAVORITES}/{other.id}", headers=headers)

    other.status = UserStatus.suspended
    session.add(other)
    await session.commit()
    assert (await client.get(FAVORITES, headers=headers)).json()["items"] == []

    other.status = UserStatus.active
    session.add(other)
    await session.commit()
    listed = (await client.get(FAVORITES, headers=headers)).json()
    assert [item["id"] for item in listed["items"]] == [other.id]


@pytest.mark.integration
async def test_favorites_search_matches_the_handle(
    client: AsyncClient, session: AsyncSession
):
    """A profile carries no real name, so the handle is all there is to match."""
    user = await create_user(session)
    headers = get_auth_headers(user)
    hit = await create_user(session, username="findable", full_name="Ada Lovelace")
    miss = await create_user(session, username="otherperson")
    await client.put(f"{FAVORITES}/{hit.id}", headers=headers)
    await client.put(f"{FAVORITES}/{miss.id}", headers=headers)

    by_handle = (
        await client.get(f"{FAVORITES}?search=findable", headers=headers)
    ).json()
    assert [item["id"] for item in by_handle["items"]] == [hit.id]

    by_name = (await client.get(f"{FAVORITES}?search=Lovelace", headers=headers)).json()
    assert by_name["items"] == []


@pytest.mark.integration
async def test_a_favorites_list_is_private(client: AsyncClient, session: AsyncSession):
    """Two readers, one starred person, and neither list is the other's."""
    starrer = await create_user(session)
    subject = await create_user(session)
    onlooker = await create_user(session)

    await client.put(f"{FAVORITES}/{subject.id}", headers=get_auth_headers(starrer))

    # The person starred does not see it...
    assert (await client.get(FAVORITES, headers=get_auth_headers(subject))).json()[
        "items"
    ] == []
    # ...and neither does anybody else.
    assert (await client.get(FAVORITES, headers=get_auth_headers(onlooker))).json()[
        "items"
    ] == []


@pytest.mark.integration
async def test_guild_admin_gets_no_extra_reach_into_a_list(
    client: AsyncClient, session: AsyncSession
):
    """A guild admin runs the guild, not anyone's contacts."""
    admin = await create_user(session)
    member = await create_user(session)
    guild = await create_guild(session)
    await create_guild_membership(
        session, user=admin, guild=guild, role=GuildRole.admin
    )
    await create_guild_membership(session, user=member, guild=guild)

    subject = await create_user(session)
    await client.put(f"{FAVORITES}/{subject.id}", headers=get_auth_headers(member))

    assert (await client.get(FAVORITES, headers=get_auth_headers(admin))).json()[
        "items"
    ] == []


@pytest.mark.integration
async def test_a_community_of_one_has_no_section(
    client: AsyncClient, session: AsyncSession
):
    """Being alone somewhere is not an empty roster, it is no roster.

    The section would otherwise say nobody there is accepting messages, which
    is a remark about people who are not there.
    """
    user = await create_user(session)
    alone = await create_guild(session)
    shared = await create_guild(session)
    await create_guild_membership(session, user=user, guild=alone)
    await create_guild_membership(session, user=user, guild=shared)
    await create_guild_membership(
        session, user=await create_user(session), guild=shared
    )

    response = await client.get(SECTIONS, headers=get_auth_headers(user))
    ids = [s["guild_id"] for s in response.json()["sections"]]
    assert ids == [shared.id]
