"""A community's location: set by its admin, read by its members and the
directory.

``PATCH /api/v1/communities/{guild_id}`` replaces the whole location; omitting
it leaves it alone and ``null`` clears it.
"""

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.guild import GuildRole
from app.services.platform import app_settings as app_settings_service
from app.testing.factories import create_guild


async def _admin(session: AsyncSession, acting_user):
    guild = await create_guild(session, name="Queen Anne Gardeners")
    admin = await acting_user(guild_role=GuildRole.admin, guild=guild)
    return guild, admin


async def _patch(client: AsyncClient, guild_id: int, headers: dict, body: dict):
    return await client.patch(
        f"/api/v1/communities/{guild_id}", json=body, headers=headers
    )


async def test_a_guild_starts_with_no_location(
    client: AsyncClient, session: AsyncSession, acting_user
):
    guild, admin = await _admin(session, acting_user)

    response = await client.get("/api/v1/communities/", headers=admin.headers)

    assert response.status_code == 200
    [read] = [item for item in response.json() if item["id"] == guild.id]
    assert read["location"] is None


async def test_a_country_alone_is_a_location(
    client: AsyncClient, session: AsyncSession, acting_user
):
    guild, admin = await _admin(session, acting_user)

    response = await _patch(
        client, guild.id, admin.headers, {"location": {"country": "jp"}}
    )

    assert response.status_code == 200, response.text
    await session.refresh(guild)
    # Stored upper case, and with only the parts that were given.
    assert guild.location == {"country": "JP"}
    assert response.json()["location"] == {
        "country": "JP",
        "region": None,
        "region_code": None,
        "city": None,
        "address": None,
        "postal_code": None,
        "label": None,
    }


async def test_an_exact_address_is_stored_tidied(
    client: AsyncClient, session: AsyncSession, acting_user
):
    guild, admin = await _admin(session, acting_user)

    response = await _patch(
        client,
        guild.id,
        admin.headers,
        {
            "location": {
                "country": "US",
                "region": "Washington",
                "region_code": "WA",
                "city": "  Seattle ",
                "address": "1 Queen  Anne Ave N",
                "postal_code": "98109",
                "label": "Queen Anne Neighborhood",
            }
        },
    )

    assert response.status_code == 200, response.text
    await session.refresh(guild)
    assert guild.location == {
        "country": "US",
        "region": "Washington",
        "region_code": "WA",
        "city": "Seattle",
        "address": "1 Queen Anne Ave N",
        "postal_code": "98109",
        "label": "Queen Anne Neighborhood",
    }


async def test_a_blank_part_is_absent(
    client: AsyncClient, session: AsyncSession, acting_user
):
    guild, admin = await _admin(session, acting_user)

    response = await _patch(
        client,
        guild.id,
        admin.headers,
        {"location": {"country": "GB", "city": "London", "region": "  "}},
    )

    assert response.status_code == 200, response.text
    await session.refresh(guild)
    assert guild.location == {"country": "GB", "city": "London"}


async def test_omitting_the_location_leaves_it_and_null_clears_it(
    client: AsyncClient, session: AsyncSession, acting_user
):
    guild, admin = await _admin(session, acting_user)
    await _patch(
        client,
        guild.id,
        admin.headers,
        {"location": {"country": "CA", "city": "Toronto"}},
    )

    renamed = await _patch(client, guild.id, admin.headers, {"name": "Gardeners"})
    assert renamed.status_code == 200, renamed.text
    await session.refresh(guild)
    assert guild.location == {"country": "CA", "city": "Toronto"}

    cleared = await _patch(client, guild.id, admin.headers, {"location": None})
    assert cleared.status_code == 200, cleared.text
    await session.refresh(guild)
    assert guild.location is None
    assert cleared.json()["location"] is None


@pytest.mark.parametrize(
    "location",
    [
        {"city": "Seattle"},
        {"country": "USA"},
        {"country": "1A"},
        {"country": "US", "label": "x" * 61},
    ],
    ids=["no country", "three letters", "not letters", "label too long"],
)
async def test_a_malformed_location_is_refused(
    client: AsyncClient, session: AsyncSession, acting_user, location: dict
):
    guild, admin = await _admin(session, acting_user)

    response = await _patch(client, guild.id, admin.headers, {"location": location})

    assert response.status_code == 422
    await session.refresh(guild)
    assert guild.location is None


async def test_a_member_cannot_set_the_location(
    client: AsyncClient, session: AsyncSession, acting_user
):
    guild = await create_guild(session, name="Queen Anne Gardeners")
    member = await acting_user(guild_role=GuildRole.member, guild=guild)

    response = await _patch(
        client, guild.id, member.headers, {"location": {"country": "US"}}
    )

    assert response.status_code == 403
    await session.refresh(guild)
    assert guild.location is None


async def test_members_and_the_directory_read_the_location(
    client: AsyncClient, session: AsyncSession, acting_user
):
    await app_settings_service.update_community_settings(
        session, community_directory_enabled=True
    )
    guild = await create_guild(
        session,
        name="Queen Anne Gardeners",
        location={"country": "US", "region_code": "WA", "city": "Seattle"},
    )
    member = await acting_user(guild_role=GuildRole.member, guild=guild)
    guild.is_community = True
    guild.show_member_names = False
    guild.categories = ["other"]
    guild.has_adult_content = False
    session.add(guild)
    await session.commit()

    mine = await client.get("/api/v1/communities/", headers=member.headers)
    [read] = [item for item in mine.json() if item["id"] == guild.id]
    assert read["location"]["city"] == "Seattle"

    browser = await acting_user("member")
    directory = await client.get(
        "/api/v1/communities/directory", headers=browser.headers
    )
    [card] = [item for item in directory.json()["items"] if item["id"] == guild.id]
    assert card["location"]["region_code"] == "WA"


# ---------------------------------------------------------------------------
# Searching the directory by location
# ---------------------------------------------------------------------------


async def _listed_at(session: AsyncSession, name: str, location: dict | None):
    guild = await create_guild(session, name=name, location=location)
    guild.is_community = True
    guild.show_member_names = False
    guild.categories = ["other"]
    guild.has_adult_content = False
    session.add(guild)
    await session.commit()
    return guild


async def _directory_names(client: AsyncClient, headers: dict, **params) -> set[str]:
    response = await client.get(
        "/api/v1/communities/directory", params=params, headers=headers
    )
    assert response.status_code == 200, response.text
    return {item["name"] for item in response.json()["items"]}


@pytest.fixture
async def located_directory(session: AsyncSession):
    await app_settings_service.update_community_settings(
        session, community_directory_enabled=True
    )
    await _listed_at(
        session,
        "Gardeners",
        {
            "country": "US",
            "region": "Washington",
            "region_code": "WA",
            "city": "Seattle",
            "label": "Queen Anne Neighborhood",
            "postal_code": "98109",
        },
    )
    await _listed_at(session, "Go Club", {"country": "JP", "city": "Kyoto"})
    await _listed_at(session, "Choir", None)


@pytest.mark.parametrize(
    "params,expected",
    [
        ({"q": "seattle"}, {"Gardeners"}),
        ({"q": "Queen Anne"}, {"Gardeners"}),
        ({"q": "washington"}, {"Gardeners"}),
        ({"q": "98109"}, {"Gardeners"}),
        ({"q": "kyoto"}, {"Go Club"}),
        # A country is stored as a code: the client names the codes the
        # search text means, and either is enough.
        ({"q": "Japan", "q_country": ["jp"]}, {"Go Club"}),
        ({"q": "Japan"}, set()),
        # A malformed code is ignored rather than refused.
        ({"q": "Japan", "q_country": ["japan"]}, set()),
    ],
)
async def test_the_directory_searches_where_a_community_is(
    client: AsyncClient,
    acting_user,
    located_directory,
    params: dict,
    expected: set[str],
):
    browser = await acting_user("member")

    assert await _directory_names(client, browser.headers, **params) == expected


async def test_a_country_alone_does_not_filter_without_a_search(
    client: AsyncClient, acting_user, located_directory
):
    """``q_country`` widens a search; it is not a filter of its own."""
    browser = await acting_user("member")

    names = await _directory_names(client, browser.headers, q_country=["JP"])

    assert names == {"Gardeners", "Go Club", "Choir"}


# ---------------------------------------------------------------------------
# Putting the communities near the reader first
# ---------------------------------------------------------------------------


async def _directory_order(client: AsyncClient, headers: dict, **params) -> list[str]:
    response = await client.get(
        "/api/v1/communities/directory", params=params, headers=headers
    )
    assert response.status_code == 200, response.text
    return [item["name"] for item in response.json()["items"]]


@pytest.fixture
async def spread_directory(session: AsyncSession):
    await app_settings_service.update_community_settings(
        session, community_directory_enabled=True
    )
    places = {
        "Kyoto Go": {"country": "JP", "city": "Kyoto"},
        "Nowhere Choir": None,
        "Texas Rodeo": {"country": "US", "region_code": "TX", "city": "Austin"},
        "Tacoma Rowers": {"country": "US", "region_code": "WA", "city": "Tacoma"},
        "Seattle Gardeners": {
            "country": "US",
            "region_code": "WA",
            "city": "Seattle",
        },
        # Same city name, another state: not near a reader in Washington.
        "Seattle Ohio": {"country": "US", "region_code": "OH", "city": "Seattle"},
    }
    for name, location in places.items():
        await _listed_at(session, name, location)


async def test_the_nearest_communities_come_first(
    client: AsyncClient, acting_user, spread_directory
):
    browser = await acting_user("member")

    order = await _directory_order(
        client,
        browser.headers,
        near_country="us",
        near_region="wa",
        near_city="seattle",
    )

    assert order[:2] == ["Seattle Gardeners", "Tacoma Rowers"]
    # Then the rest of the country, then nowhere in particular, then abroad.
    assert set(order[2:4]) == {"Seattle Ohio", "Texas Rodeo"}
    assert order[4:] == ["Nowhere Choir", "Kyoto Go"]


async def test_a_country_alone_puts_that_country_first(
    client: AsyncClient, acting_user, spread_directory
):
    browser = await acting_user("member")

    order = await _directory_order(client, browser.headers, near_country="JP")

    assert order[0] == "Kyoto Go"
    assert order[1] == "Nowhere Choir"


async def test_near_reorders_without_narrowing(
    client: AsyncClient, acting_user, spread_directory
):
    browser = await acting_user("member")

    near = await _directory_order(client, browser.headers, near_country="JP")
    anywhere = await _directory_order(client, browser.headers)

    assert sorted(near) == sorted(anywhere)
