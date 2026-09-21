"""Integration tests for /api/v1/me/contacts."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.app_setting import AppSetting
from app.models.platform.guild import Guild, GuildRole
from app.models.platform.profile_favorite import ProfileFavorite
from app.models.platform.user import User, UserStatus
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


async def _join(
    session: AsyncSession, guild: Guild, user: User | None = None, **overrides
) -> User:
    """Put somebody in ``guild`` — a fresh account unless one is given."""
    if user is None:
        user = await create_user(session, **overrides)
    await create_guild_membership(session, user=user, guild=guild)
    return user


async def _rail(session: AsyncSession, user: User, *guilds: Guild) -> None:
    """Put ``user`` in each guild, in the rail order given."""
    for position, guild in enumerate(guilds):
        await create_guild_membership(
            session, user=user, guild=guild, position=position
        )


# --- sections ---------------------------------------------------------------


@pytest.mark.integration
async def test_an_account_on_its_own_has_nothing_to_list(
    client: AsyncClient, acting_user
):
    """No communities and nobody starred: both lists answer, both empty."""
    a = await acting_user()

    sections = await client.get(SECTIONS, headers=a.headers)
    assert sections.status_code == 200
    assert sections.json()["sections"] == []

    favorites = await client.get(FAVORITES, headers=a.headers)
    assert favorites.status_code == 200
    assert favorites.json() == {"items": [], "total_count": 0}


@pytest.mark.integration
async def test_sections_follow_rail_order(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Sections come back in ``GuildMembership.position``, not guild id."""
    a = await acting_user()
    first = await create_guild(session)
    second = await create_guild(session)
    third = await create_guild(session)
    # Deliberately not id order: the rail is what decides.
    await _rail(session, a.user, second, third, first)
    # Somebody else in each, or there would be no section to order.
    for guild in (first, second, third):
        await _join(session, guild)

    response = await client.get(SECTIONS, headers=a.headers)
    assert response.status_code == 200
    assert [s["guild_id"] for s in response.json()["sections"]] == [
        second.id,
        third.id,
        first.id,
    ]


@pytest.mark.integration
async def test_only_a_community_the_caller_shares_gets_a_section(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Three communities, one section: somebody else's is not the caller's to
    read, and being alone somewhere is not an empty roster, it is no roster —
    a section there would say nobody is accepting messages, which is a remark
    about people who are not there.
    """
    a = await acting_user()
    shared = await create_guild(session)
    alone = await create_guild(session)
    theirs = await create_guild(session)
    await _rail(session, a.user, shared, alone)
    await _join(session, shared)
    await _join(session, theirs)

    response = await client.get(SECTIONS, headers=a.headers)
    ids = [s["guild_id"] for s in response.json()["sections"]]
    assert ids == [shared.id]
    assert alone.id not in ids
    assert theirs.id not in ids


@pytest.mark.integration
async def test_a_section_names_the_other_people_who_are_still_here(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The caller is not their own contact, and a suspended account leaves the
    roster — count and all."""
    a = await acting_user(guild_role=GuildRole.member)
    other = await _join(session, a.guild)

    response = await client.get(SECTIONS, headers=a.headers)
    section = _section(response.json(), a.guild.id)
    assert [item["id"] for item in section["items"]] == [other.id]

    other.status = UserStatus.suspended
    session.add(other)
    await session.commit()

    response = await client.get(SECTIONS, headers=a.headers)
    section = _section(response.json(), a.guild.id)
    assert section["items"] == []
    assert section["total_count"] == 0


@pytest.mark.integration
async def test_sections_page_within_each_guild(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Paging is per section — a flat offset across a merged list would not
    mean anything for a grouped response."""
    a = await acting_user(guild_role=GuildRole.member)
    for index in range(5):
        await _join(session, a.guild, username=f"member{index}")

    first = await client.get(f"{SECTIONS}?page=1&page_size=2", headers=a.headers)
    section = _section(first.json(), a.guild.id)
    assert len(section["items"]) == 2
    assert section["total_count"] == 5
    assert section["has_next"] is True

    last = await client.get(f"{SECTIONS}?page=3&page_size=2", headers=a.headers)
    section = _section(last.json(), a.guild.id)
    assert len(section["items"]) == 1
    assert section["has_next"] is False


@pytest.mark.integration
async def test_guild_ids_narrows_to_one_section(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user()
    first = await create_guild(session)
    second = await create_guild(session)
    await _rail(session, a.user, first, second)
    for guild in (first, second):
        await _join(session, guild)

    response = await client.get(f"{SECTIONS}?guild_ids={second.id}", headers=a.headers)
    assert [s["guild_id"] for s in response.json()["sections"]] == [second.id]


# --- how a person is drawn ---------------------------------------------------


@pytest.mark.integration
async def test_both_ways_of_listing_someone_draw_them_the_same(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A row draws somebody the way every other surface does — and favorites
    come from the profile view rather than the roster walk, so they are their
    own path to the same answer."""
    a = await acting_user(guild_role=GuildRole.member)
    other = await _join(
        session, a.guild, profile_decorations={"frame": "core.gold", "trophies": []}
    )
    session.add(ProfileFavorite(user_id=a.user.id, favorite_user_id=other.id))
    await session.commit()

    roster = await client.get(SECTIONS, headers=a.headers)
    row = _section(roster.json(), a.guild.id)["items"][0]
    assert row["profile_decorations"]["frame"] == "core.gold"

    starred = await client.get(FAVORITES, headers=a.headers)
    assert starred.json()["items"][0]["profile_decorations"]["frame"] == "core.gold"


# --- names, per guild -------------------------------------------------------


@pytest.mark.integration
async def test_a_guild_that_hides_real_names_neither_shows_nor_matches_them(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """One response, two guilds, one person — named by each guild's setting,
    and searchable by that name only where the guild shows it."""
    a = await acting_user()
    shows = await create_guild(session, show_member_names=True)
    hides = await create_guild(session, show_member_names=False)
    await _rail(session, a.user, shows, hides)
    other = await create_user(session, username="qqqhandle", full_name="Ada Lovelace")
    await _join(session, shows, other)
    await _join(session, hides, other)

    payload = (await client.get(SECTIONS, headers=a.headers)).json()
    assert _section(payload, shows.id)["items"][0]["full_name"] == "Ada Lovelace"
    assert _section(payload, hides.id)["items"][0]["full_name"] is None

    searched = await client.get(f"{SECTIONS}?search=Lovelace", headers=a.headers)
    assert [s["guild_id"] for s in searched.json()["sections"]] == [shows.id]


# --- the shared-guild chip --------------------------------------------------


@pytest.mark.integration
async def test_shared_guilds_named_on_every_appearance(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The set is what the two of them share, so it is the same on each
    appearance and says nothing about where else the subject is."""
    a = await acting_user()
    guilds = [await create_guild(session) for _ in range(3)]
    await _rail(session, a.user, *guilds)

    other = await create_user(session)
    for guild in guilds:
        await _join(session, guild, other)
    # A guild the subject is in and the caller is not.
    elsewhere = await create_guild(session)
    await _join(session, elsewhere, other)

    payload = (await client.get(SECTIONS, headers=a.headers)).json()
    expected = [guild.id for guild in guilds]
    for guild in guilds:
        section = _section(payload, guild.id)
        assert [item["id"] for item in section["items"]] == [other.id]
        # Every appearance names the full set, in rail order; the chip is what
        # drops the section's own guild.
        assert section["items"][0]["shared_guild_ids"] == expected
        assert elsewhere.id not in section["items"][0]["shared_guild_ids"]


@pytest.mark.integration
async def test_shared_guilds_stable_across_pages(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The map is read from memberships, not from the rows on the page.

    ``other`` is last alphabetically in the big guild, so it only appears on a
    later page there — and its chip must be the same on both.
    """
    a = await acting_user()
    big = await create_guild(session)
    small = await create_guild(session)
    await _rail(session, a.user, big, small)

    for index in range(4):
        await _join(session, big, username=f"aaa{index}")

    other = await create_user(session, username="zzztail")
    await _join(session, big, other)
    await _join(session, small, other)

    expected = [big.id, small.id]

    page_one = await client.get(f"{SECTIONS}?page=1&page_size=2", headers=a.headers)
    small_section = _section(page_one.json(), small.id)
    assert small_section["items"][0]["shared_guild_ids"] == expected
    # ...and ``other`` is not even on the big guild's first page.
    assert other.id not in [i["id"] for i in _section(page_one.json(), big.id)["items"]]

    page_three = await client.get(f"{SECTIONS}?page=3&page_size=2", headers=a.headers)
    big_section = _section(page_three.json(), big.id)
    assert [i["id"] for i in big_section["items"]] == [other.id]
    assert big_section["items"][0]["shared_guild_ids"] == expected


# --- search -----------------------------------------------------------------


@pytest.mark.integration
async def test_search_finds_someone_past_the_first_page(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The reason search is server-side: a client filter over the loaded page
    could not reach this person."""
    a = await acting_user(guild_role=GuildRole.member)
    for index in range(6):
        await _join(session, a.guild, username=f"aaa{index}")
    target = await _join(session, a.guild, username="zzzneedle")

    unsearched = await client.get(f"{SECTIONS}?page=1&page_size=3", headers=a.headers)
    assert target.id not in [
        i["id"] for i in _section(unsearched.json(), a.guild.id)["items"]
    ]

    searched = await client.get(
        f"{SECTIONS}?search=zzzneedle&page=1&page_size=3", headers=a.headers
    )
    section = _section(searched.json(), a.guild.id)
    assert [i["id"] for i in section["items"]] == [target.id]


@pytest.mark.integration
async def test_search_hides_sections_with_no_match(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user()
    hit = await create_guild(session)
    miss = await create_guild(session)
    await _rail(session, a.user, hit, miss)
    await _join(session, hit, username="findme")
    await _join(session, miss, username="somebody")

    response = await client.get(f"{SECTIONS}?search=findme", headers=a.headers)
    assert [s["guild_id"] for s in response.json()["sections"]] == [hit.id]


# --- favorites --------------------------------------------------------------


@pytest.mark.integration
async def test_favorite_roundtrip_and_idempotence(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user()
    other = await create_user(session)

    assert (
        await client.put(f"{FAVORITES}/{other.id}", headers=a.headers)
    ).status_code == 204
    # Starring twice is a no-op, not a conflict.
    assert (
        await client.put(f"{FAVORITES}/{other.id}", headers=a.headers)
    ).status_code == 204

    listed = (await client.get(FAVORITES, headers=a.headers)).json()
    assert [item["id"] for item in listed["items"]] == [other.id]
    assert listed["total_count"] == 1

    assert (
        await client.delete(f"{FAVORITES}/{other.id}", headers=a.headers)
    ).status_code == 204
    assert (await client.get(FAVORITES, headers=a.headers)).json()["items"] == []
    # Unstarring what is not starred is a no-op too.
    assert (
        await client.delete(f"{FAVORITES}/{other.id}", headers=a.headers)
    ).status_code == 204


@pytest.mark.integration
async def test_favorite_survives_the_row_appearing_underneath_it(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Two stars of the same person arriving together both find nothing.

    The pair is the primary key and the insert defers to it, so the second one
    settles as a no-op rather than as a server error.
    """
    a = await acting_user()
    other = await create_user(session)

    session.add(ProfileFavorite(user_id=a.user.id, favorite_user_id=other.id))
    await session.commit()

    response = await client.put(f"{FAVORITES}/{other.id}", headers=a.headers)
    assert response.status_code == 204

    rows = (
        await session.exec(
            select(ProfileFavorite).where(ProfileFavorite.user_id == a.user.id)
        )
    ).all()
    assert len(rows) == 1


@pytest.mark.integration
async def test_favorite_someone_sharing_no_guild(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Any profile may be starred — the list is not a subset of the rosters."""
    a = await acting_user()
    stranger = await create_user(session)

    assert (
        await client.put(f"{FAVORITES}/{stranger.id}", headers=a.headers)
    ).status_code == 204
    listed = (await client.get(FAVORITES, headers=a.headers)).json()
    assert [item["id"] for item in listed["items"]] == [stranger.id]
    # ...and they are in no section, because the caller is in no guild with them.
    assert (await client.get(SECTIONS, headers=a.headers)).json()["sections"] == []


@pytest.mark.integration
@pytest.mark.parametrize(
    "target,expected,detail",
    [
        pytest.param("self", 400, "CONTACT_CANNOT_FAVORITE_SELF", id="themselves"),
        pytest.param("missing", 404, "USER_NOT_FOUND", id="nobody"),
    ],
)
async def test_who_cannot_be_starred(
    client: AsyncClient, acting_user, target, expected, detail
):
    a = await acting_user()
    user_id = a.user.id if target == "self" else 98765432

    response = await client.put(f"{FAVORITES}/{user_id}", headers=a.headers)

    assert response.status_code == expected
    assert response.json()["detail"] == detail


@pytest.mark.integration
async def test_suspended_favorite_drops_out_and_returns(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user()
    other = await create_user(session)
    await client.put(f"{FAVORITES}/{other.id}", headers=a.headers)

    other.status = UserStatus.suspended
    session.add(other)
    await session.commit()
    assert (await client.get(FAVORITES, headers=a.headers)).json()["items"] == []

    other.status = UserStatus.active
    session.add(other)
    await session.commit()
    listed = (await client.get(FAVORITES, headers=a.headers)).json()
    assert [item["id"] for item in listed["items"]] == [other.id]


@pytest.mark.integration
async def test_favorites_search_matches_the_handle(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A profile carries no real name, so the handle is all there is to match."""
    a = await acting_user()
    hit = await create_user(session, username="findable", full_name="Ada Lovelace")
    miss = await create_user(session, username="otherperson")
    await client.put(f"{FAVORITES}/{hit.id}", headers=a.headers)
    await client.put(f"{FAVORITES}/{miss.id}", headers=a.headers)

    by_handle = (
        await client.get(f"{FAVORITES}?search=findable", headers=a.headers)
    ).json()
    assert [item["id"] for item in by_handle["items"]] == [hit.id]

    by_name = (
        await client.get(f"{FAVORITES}?search=Lovelace", headers=a.headers)
    ).json()
    assert by_name["items"] == []


@pytest.mark.integration
async def test_a_favorites_list_is_private(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """One starred person and three other readers — the person starred, a
    bystander, and the admin of a guild the starrer is in. It is the starrer's
    list, and a guild admin runs the guild rather than anyone's contacts.
    """
    admin = await acting_user(guild_role=GuildRole.admin)
    starrer = await acting_user(guild_role=GuildRole.member, guild=admin.guild)
    onlooker = await acting_user()
    subject = await create_user(session)

    await client.put(f"{FAVORITES}/{subject.id}", headers=starrer.headers)

    starred = (await client.get(FAVORITES, headers=starrer.headers)).json()
    assert [item["id"] for item in starred["items"]] == [subject.id]
    for reader in (admin, onlooker):
        assert (await client.get(FAVORITES, headers=reader.headers)).json()[
            "items"
        ] == []
    assert (await client.get(FAVORITES, headers=get_auth_headers(subject))).json()[
        "items"
    ] == []
