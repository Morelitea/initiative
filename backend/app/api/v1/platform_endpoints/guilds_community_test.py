"""Integration tests for the community directory.

Covers the two endpoints a guild's opt-in unlocks —
``GET /api/v1/guilds/communities`` (browse) and
``POST /api/v1/guilds/communities/{guild_id}/join`` (join without an invite) —
plus the guild-admin PATCH that sets the opt-in and its categories.
"""

import pytest
from httpx import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.guild import (
    Guild,
    GuildMembership,
    GuildRole,
    GuildStatus,
)
from app.models.platform.user import UserRole
from app.models.tenant.initiative import InitiativeMember
from app.models.tenant.resource_grant import ResourceAccessLevel, ResourceGrant
from app.services.platform import app_settings as app_settings_service
from app.testing.factories import (
    create_guild,
    create_guild_membership,
    create_initiative,
    create_project,
    create_user,
    guild_administration,
)
from app.core.usernames import url_handle
from app.testing.schema_harness import route_session_to_guild


@pytest.fixture(autouse=True)
async def community_directory_on(session: AsyncSession) -> None:
    """Run the directory for this module.

    The switch is a platform-owner setting that starts off, so every test below
    would otherwise be testing a deployment with no directory. Stated once here
    instead of in each test; the tests about the switch itself set it
    themselves.
    """
    await app_settings_service.update_community_settings(
        session, community_directory_enabled=True
    )


async def _list_as_community(
    session: AsyncSession,
    guild: Guild,
    *,
    categories: list[str] | None = None,
) -> Guild:
    """Opt a guild into the directory directly, without the settings page.

    A listed guild is always on a shelf and always declared free of adult
    content — the database refuses to store one that is not — so the default
    category keeps every test that does not care about shelves valid.
    """
    guild.is_community = True
    guild.categories = categories or ["other"]
    guild.has_adult_content = False
    session.add(guild)
    await session.commit()
    await session.refresh(guild)
    return guild


async def _a_listed_guild(
    session: AsyncSession, *, categories: list[str] | None = None, **guild_fields
) -> Guild:
    """A guild that has opted into the directory."""
    return await _list_as_community(
        session, await create_guild(session, **guild_fields), categories=categories
    )


async def _admin_of(session: AsyncSession, acting_user, **guild_fields):
    """A guild plus the headers of one of its admins."""
    guild = await create_guild(session, **guild_fields)
    admin = await acting_user(guild_role=GuildRole.admin, guild=guild)
    return guild, admin.headers


async def _membership_of(
    session: AsyncSession, *, guild: Guild, user_id: int
) -> GuildMembership | None:
    return (
        await session.exec(
            select(GuildMembership).where(
                GuildMembership.guild_id == guild.id,
                GuildMembership.user_id == user_id,
            )
        )
    ).one_or_none()


@pytest.mark.integration
async def test_directory_lists_only_opted_in_guilds(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A guild appears only once it has opted in — invite-only guilds do not."""
    browser = await acting_user("member")
    await _a_listed_guild(session, name="Open Table")
    await create_guild(session, name="Private Office")

    response = await client.get("/api/v1/guilds/communities", headers=browser.headers)

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert [item["name"] for item in data["items"]] == ["Open Table"]


@pytest.mark.integration
@pytest.mark.parametrize(
    "condition",
    ["suspended", "frozen", "one seat"],
)
async def test_the_directory_re_checks_a_listed_guild_before_offering_it(
    client: AsyncClient, session: AsyncSession, acting_user, condition: str
):
    """The opt-in is not the last word. A frozen or suspended guild takes no
    new members, and neither does one whose operator-set cap leaves no seat for
    a joiner — the cap can be lowered long after the listing was made."""
    browser = await acting_user("member")
    guild = await _a_listed_guild(session, name="Open Table")
    if condition == "one seat":
        await guild_administration(session, guild, max_users=1)
    else:
        guild.status = (
            GuildStatus.suspended.value
            if condition == "suspended"
            else GuildStatus.read_only.value
        )
        session.add(guild)
        await session.commit()

    response = await client.get("/api/v1/guilds/communities", headers=browser.headers)

    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 0}


@pytest.mark.integration
async def test_directory_card_carries_only_published_fields(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The card is what the guild published, plus its roster size — no more."""
    browser = await acting_user("member")
    guild = await create_guild(
        session, name="Riverside Players", description="Community theatre."
    )
    await acting_user(guild_role=GuildRole.member, guild=guild)
    await _list_as_community(session, guild, categories=["art", "writing"])

    response = await client.get("/api/v1/guilds/communities", headers=browser.headers)

    card = response.json()["items"][0]
    assert card["name"] == "Riverside Players"
    assert card["description"] == "Community theatre."
    assert card["categories"] == ["art", "writing"]
    assert card["member_count"] == 1
    assert card["already_member"] is False
    # Nothing about the guild's administration or lifecycle reaches a stranger.
    assert "status" not in card
    assert "tier_name" not in card
    assert "max_users" not in card
    assert "role" not in card


@pytest.mark.integration
async def test_directory_flags_guilds_the_caller_is_already_in(
    client: AsyncClient, session: AsyncSession, acting_user
):
    joined = await _a_listed_guild(session, name="Open Table")
    browser = await acting_user(guild_role=GuildRole.member, guild=joined)
    await _a_listed_guild(session, name="Somewhere Else")

    response = await client.get("/api/v1/guilds/communities", headers=browser.headers)

    assert {
        item["name"]: item["already_member"] for item in response.json()["items"]
    } == {
        "Open Table": True,
        "Somewhere Else": False,
    }


@pytest.mark.integration
@pytest.mark.parametrize(
    "query,expected_status,expected_names",
    [
        pytest.param(
            "?category=ttrpg",
            200,
            ["Dice Goblins", "Painted Minis"],
            id="a shelf, reaching a guild that is on two of them",
        ),
        pytest.param(
            "?q=dice",
            200,
            ["Dice Goblins", "Painted Minis"],
            id="a word, matched in a name and in a description",
        ),
        pytest.param("?category=nonsense", 422, None, id="a shelf nobody stocks"),
    ],
)
async def test_the_directory_narrows_to_what_was_asked_for(
    client: AsyncClient,
    session: AsyncSession,
    acting_user,
    query: str,
    expected_status: int,
    expected_names: list[str] | None,
):
    """A shelf or a word narrows the directory to the guilds that match it, and
    a shelf that is not one of the published ones is not a narrowing at all."""
    browser = await acting_user("member")
    await _a_listed_guild(session, name="Dice Goblins", categories=["ttrpg"])
    await _a_listed_guild(session, name="Life Drawing", categories=["art"])
    await _a_listed_guild(
        session,
        name="Painted Minis",
        categories=["art", "ttrpg"],
        description="We paint dice trays too.",
    )

    response = await client.get(
        f"/api/v1/guilds/communities{query}", headers=browser.headers
    )

    assert response.status_code == expected_status
    if expected_names is not None:
        assert sorted(item["name"] for item in response.json()["items"]) == (
            expected_names
        )


@pytest.mark.integration
async def test_directory_lists_the_busiest_guilds_first(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Who is already in a guild is what someone with none is choosing between."""
    browser = await acting_user("member")
    # Named against the order they belong in, so an alphabetical sort cannot
    # pass this by accident.
    await _a_listed_guild(session, name="Aardvark Club")
    busy = await _a_listed_guild(session, name="Zebra Hall")
    for _ in range(3):
        await acting_user(guild_role=GuildRole.member, guild=busy)

    response = await client.get("/api/v1/guilds/communities", headers=browser.headers)

    items = response.json()["items"]
    assert [item["name"] for item in items] == ["Zebra Hall", "Aardvark Club"]
    assert [item["member_count"] for item in items] == [3, 0]


@pytest.mark.integration
async def test_directory_searches_every_guild_not_only_a_loaded_page(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The search is the query's, not the caller's.

    The match is the quietest guild here and the page holds one guild, so it is
    on no page a browser would have loaded by the time it searched.
    """
    browser = await acting_user("member")
    busy = await _a_listed_guild(session, name="Crowded Hall")
    for _ in range(3):
        await acting_user(guild_role=GuildRole.member, guild=busy)
    await _a_listed_guild(session, name="Dice Goblins")

    response = await client.get(
        "/api/v1/guilds/communities?q=goblins&page_size=1",
        headers=browser.headers,
    )

    body = response.json()
    assert [item["name"] for item in body["items"]] == ["Dice Goblins"]
    assert body["total"] == 1


@pytest.mark.integration
async def test_directory_paginates(
    client: AsyncClient, session: AsyncSession, acting_user
):
    browser = await acting_user("member")
    for index in range(3):
        await _a_listed_guild(session, name=f"Guild {index}")

    first = await client.get(
        "/api/v1/guilds/communities?page=1&page_size=2", headers=browser.headers
    )
    second = await client.get(
        "/api/v1/guilds/communities?page=2&page_size=2", headers=browser.headers
    )

    # The total counts everything that matched, not just this page.
    assert first.json()["total"] == 3
    assert len(first.json()["items"]) == 2
    assert len(second.json()["items"]) == 1


@pytest.mark.integration
async def test_directory_requires_authentication(client: AsyncClient):
    response = await client.get("/api/v1/guilds/communities")

    assert response.status_code == 401


@pytest.mark.integration
async def test_joining_a_listed_guild_needs_no_invite_and_repeats_harmlessly(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The listing is the authorization, and joining twice returns the guild
    rather than erroring or seating the same person twice."""
    joiner = await acting_user("member")
    guild = await _a_listed_guild(session, name="Open Table")
    url = f"/api/v1/guilds/communities/{guild.id}/join"

    first = await client.post(url, headers=joiner.headers)
    second = await client.post(url, headers=joiner.headers)

    assert first.status_code == 200
    assert first.json()["id"] == guild.id
    assert first.json()["role"] == GuildRole.member.value
    assert second.status_code == 200
    memberships = (
        await session.exec(
            select(GuildMembership).where(
                GuildMembership.guild_id == guild.id,
                GuildMembership.user_id == joiner.user.id,
            )
        )
    ).all()
    assert [m.role for m in memberships] == [GuildRole.member]


@pytest.mark.integration
@pytest.mark.parametrize(
    "condition,expected_detail",
    [
        pytest.param("never listed", "GUILD_NOT_A_COMMUNITY", id="never listed"),
        pytest.param("suspended", "GUILD_NOT_A_COMMUNITY", id="suspended"),
        pytest.param("one seat", "GUILD_NOT_A_COMMUNITY", id="one seat"),
        pytest.param("no such guild", "GUILD_NOT_FOUND", id="no such guild"),
    ],
)
async def test_a_guild_the_directory_would_not_show_cannot_be_joined(
    client: AsyncClient,
    session: AsyncSession,
    acting_user,
    condition: str,
    expected_detail: str,
):
    """A join by id applies the directory's own filter, and an unlisted guild
    has published nothing — its id included. Only an id that names no guild at
    all is answered as a missing guild."""
    joiner = await acting_user("member")
    if condition == "never listed":
        guild = await create_guild(session, name="Private Office")
    else:
        guild = await _a_listed_guild(session, name="Open Table")
        if condition == "suspended":
            guild.status = GuildStatus.suspended.value
            session.add(guild)
            await session.commit()
        elif condition == "one seat":
            await guild_administration(session, guild, max_users=1)

    guild_id = 999999 if condition == "no such guild" else guild.id
    response = await client.post(
        f"/api/v1/guilds/communities/{guild_id}/join", headers=joiner.headers
    )

    assert response.status_code == 404
    assert response.json()["detail"] == expected_detail
    if condition != "no such guild":
        assert (
            await _membership_of(session, guild=guild, user_id=joiner.user.id) is None
        )


@pytest.mark.integration
async def test_join_respects_the_member_cap(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The directory does not bypass the guild's operator-set seat limit.

    Two seats, both taken: a listable guild (one seat could never admit anyone,
    so it would be refused as unlisted instead) that happens to be full today.
    """
    joiner = await acting_user("member")
    guild = await _a_listed_guild(session, name="Open Table")
    for _ in range(2):
        await acting_user(guild_role=GuildRole.member, guild=guild)
    await guild_administration(session, guild, max_users=2)

    response = await client.post(
        f"/api/v1/guilds/communities/{guild.id}/join", headers=joiner.headers
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "GUILD_USER_LIMIT_REACHED"


@pytest.mark.integration
async def test_a_member_cannot_opt_the_guild_in(
    client: AsyncClient, session: AsyncSession, acting_user
):
    guild = await create_guild(session, name="Open Table")
    member = await acting_user(guild_role=GuildRole.member, guild=guild)

    response = await client.patch(
        f"/api/v1/guilds/{guild.id}",
        json={"is_community": True},
        headers=member.headers,
    )

    assert response.status_code == 403
    await session.refresh(guild)
    assert guild.is_community is False


@pytest.mark.integration
async def test_an_unknown_category_is_rejected(
    client: AsyncClient, session: AsyncSession, acting_user
):
    guild, headers = await _admin_of(session, acting_user, name="Open Table")

    response = await client.patch(
        f"/api/v1/guilds/{guild.id}",
        json={"categories": ["underwater-basket-weaving"]},
        headers=headers,
    )

    assert response.status_code == 422


# ---------------------------------------------------------------------------
# What a guild must be before it can be listed
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_the_adult_content_declaration_starts_unanswered(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """It is a question only the directory asks, so an ordinary guild has no
    answer on file rather than a default one."""
    guild, headers = await _admin_of(session, acting_user)

    response = await client.get("/api/v1/guilds/", headers=headers)

    assert response.status_code == 200
    entry = next(item for item in response.json() if item["id"] == guild.id)
    assert entry["has_adult_content"] is None
    assert entry["is_community"] is False


#: The listing rules, each as the PATCH that breaks it. ``guild_fields`` go to
#: the guild, ``listed_with`` puts it on the directory first (so the rule is
#: met from the other side), and the guild must come back unchanged.
REFUSED_LISTINGS = (
    pytest.param(
        {},
        None,
        {"is_community": True, "has_adult_content": False},
        "GUILD_COMMUNITY_REQUIRES_CATEGORY",
        id="a card nobody could reach by browsing",
    ),
    pytest.param(
        {},
        None,
        {"is_community": True, "categories": ["art"]},
        "GUILD_COMMUNITY_CONTENT_NOT_DECLARED",
        id="the content question left unanswered",
    ),
    pytest.param(
        {},
        None,
        {"is_community": True, "categories": ["art"], "has_adult_content": True},
        "GUILD_COMMUNITY_ADULT_CONTENT",
        id="an adult guild",
    ),
    pytest.param(
        {"max_users": 1},
        None,
        {"is_community": True, "categories": ["art"], "has_adult_content": False},
        "GUILD_COMMUNITY_REQUIRES_CAPACITY",
        id="one seat, so no joiner could ever take one",
    ),
    pytest.param(
        {},
        ["art"],
        {"categories": []},
        "GUILD_COMMUNITY_REQUIRES_CATEGORY",
        id="a listed guild clearing its shelves",
    ),
    pytest.param(
        {},
        ["art"],
        {"has_adult_content": True},
        "GUILD_COMMUNITY_ADULT_CONTENT",
        id="a listed guild turning itself adult",
    ),
)


@pytest.mark.integration
@pytest.mark.parametrize(
    "guild_fields,listed_with,body,expected_detail", REFUSED_LISTINGS
)
async def test_a_listing_that_breaks_a_rule_is_refused_and_changes_nothing(
    client: AsyncClient,
    session: AsyncSession,
    acting_user,
    guild_fields: dict,
    listed_with: list[str] | None,
    body: dict,
    expected_detail: str,
):
    """Every rule is about the guild the PATCH would leave behind, not about
    what this request happened to carry — so listing one that breaks it and
    breaking it on one already listed are refused the same way, and the stored
    guild is left exactly as it was."""
    guild, headers = await _admin_of(session, acting_user, **guild_fields)
    if listed_with is not None:
        await _list_as_community(session, guild, categories=listed_with)
    before = (guild.is_community, guild.categories, guild.has_adult_content)

    response = await client.patch(
        f"/api/v1/guilds/{guild.id}", json=body, headers=headers
    )

    assert response.status_code == 400
    assert response.json()["detail"] == expected_detail
    await session.refresh(guild)
    assert (guild.is_community, guild.categories, guild.has_adult_content) == before


#: The PATCHes the rules let through, each with what the guild must read back
#: as afterwards — in the reply and in the row.
ACCEPTED_LISTINGS = (
    pytest.param(
        {},
        None,
        {
            "is_community": True,
            "categories": ["gaming", "ttrpg"],
            "has_adult_content": False,
        },
        {
            "is_community": True,
            "categories": ["gaming", "ttrpg"],
            "has_adult_content": False,
        },
        id="opting in",
    ),
    pytest.param(
        {"max_users": 2},
        None,
        {"is_community": True, "categories": ["art"], "has_adult_content": False},
        {"is_community": True},
        id="two seats, room for one more",
    ),
    pytest.param(
        {},
        None,
        {"categories": ["ttrpg", "art", "ttrpg"]},
        {"categories": ["art", "ttrpg"]},
        id="categories deduplicated and ordered",
    ),
    pytest.param(
        {},
        None,
        {"has_adult_content": True},
        {"has_adult_content": True, "is_community": False},
        id="an unlisted guild declaring adult content",
    ),
    pytest.param(
        {},
        ["gaming"],
        {"name": "Open Table Renamed"},
        {"name": "Open Table Renamed", "is_community": True, "categories": ["gaming"]},
        id="a rename leaving the listing alone",
    ),
    pytest.param(
        {},
        ["art"],
        {"is_community": False, "categories": []},
        {"is_community": False},
        id="delisting, which asks nothing of the guild",
    ),
)


@pytest.mark.integration
@pytest.mark.parametrize("guild_fields,listed_with,body,expected", ACCEPTED_LISTINGS)
async def test_an_accepted_listing_patch_is_stored_as_it_reads_back(
    client: AsyncClient,
    session: AsyncSession,
    acting_user,
    guild_fields: dict,
    listed_with: list[str] | None,
    body: dict,
    expected: dict,
):
    """A guild admin sets its shelves, its content declaration and whether it
    is listed at all. Whatever order the boxes were ticked in, storage is
    canonical — and the reply says the same thing as the row."""
    guild, headers = await _admin_of(
        session, acting_user, name="Open Table", **guild_fields
    )
    if listed_with is not None:
        await _list_as_community(session, guild, categories=listed_with)

    response = await client.patch(
        f"/api/v1/guilds/{guild.id}", json=body, headers=headers
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    await session.refresh(guild)
    for field, value in expected.items():
        assert payload[field] == value
        assert getattr(guild, field) == value


# ---------------------------------------------------------------------------
# The platform-owner switch
# ---------------------------------------------------------------------------


async def _switch_directory_off(session: AsyncSession) -> None:
    await app_settings_service.update_community_settings(
        session, community_directory_enabled=False
    )


@pytest.mark.integration
@pytest.mark.parametrize("surface", ["browsing", "joining", "listing itself"])
async def test_every_directory_surface_is_refused_where_it_is_switched_off(
    client: AsyncClient, session: AsyncSession, acting_user, surface: str
):
    """Refused outright, not answered with an empty page: a deployment without a
    directory has no directory, as distinct from one where nobody has listed.
    The invite-free join and the opt-in are the directory's other halves, so
    they go the same way — and nothing moves on the way."""
    guild, admin_headers = await _admin_of(session, acting_user, name="Open Table")
    caller = await acting_user("member")
    listed = surface != "listing itself"
    if listed:
        await _list_as_community(session, guild)
    await _switch_directory_off(session)

    if surface == "browsing":
        response = await client.get(
            "/api/v1/guilds/communities", headers=caller.headers
        )
    elif surface == "joining":
        response = await client.post(
            f"/api/v1/guilds/communities/{guild.id}/join", headers=caller.headers
        )
    else:
        response = await client.patch(
            f"/api/v1/guilds/{guild.id}",
            json={
                "is_community": True,
                "categories": ["gaming"],
                "has_adult_content": False,
            },
            headers=admin_headers,
        )

    assert response.status_code == 403
    assert response.json()["detail"] == "COMMUNITY_DIRECTORY_DISABLED"
    assert await _membership_of(session, guild=guild, user_id=caller.user.id) is None
    await session.refresh(guild)
    assert guild.is_community is listed


@pytest.mark.integration
async def test_a_listed_guild_can_still_unlist_where_the_directory_is_off(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Switching the directory off must not strand a guild inside a listing it
    can no longer withdraw."""
    guild, headers = await _admin_of(session, acting_user, name="Open Table")
    await _list_as_community(session, guild)
    await _switch_directory_off(session)

    response = await client.patch(
        f"/api/v1/guilds/{guild.id}",
        json={"is_community": False},
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["is_community"] is False


@pytest.mark.integration
async def test_switching_the_directory_off_keeps_the_guilds_opt_in(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Off hides the listings; it does not unpublish anybody. Switching it back
    on shows the same guilds."""
    browser = await acting_user("member")
    await _a_listed_guild(session, name="Open Table")
    await _switch_directory_off(session)
    await app_settings_service.update_community_settings(
        session, community_directory_enabled=True
    )

    response = await client.get("/api/v1/guilds/communities", headers=browser.headers)

    assert response.status_code == 200
    assert [item["name"] for item in response.json()["items"]] == ["Open Table"]


# ============================================================================
# Auto-join enrolment on arrival (discovery §5)
# ============================================================================


async def _initiative_with_shared_project(
    session: AsyncSession, guild: Guild, owner, *, name: str, auto_join: bool
):
    """An initiative plus a project shared with everyone in it.

    Gate 4 is satisfied for any member, so initiative membership is the only
    thing that decides whether the project is reachable.
    """
    initiative = await create_initiative(
        session, guild, owner, name=name, join_policy="open", auto_join=auto_join
    )
    project = await create_project(session, initiative, owner, name=f"{name} work")
    await route_session_to_guild(session, guild.id)
    session.add(
        ResourceGrant(
            resource_type="project",
            resource_id=project.id,
            all_initiative_members=True,
            level=ResourceAccessLevel.read,
            guild_id=guild.id,
            initiative_id=initiative.id,
        )
    )
    await session.commit()
    return initiative, project


@pytest.mark.integration
async def test_community_join_enrols_in_auto_join_initiatives(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Joining a public guild lands the arrival in real content.

    The membership row is the only thing that moves, and RLS does the rest: the
    auto-join initiative's project is reachable the moment the join returns,
    while its opt-in sibling in the same guild stays hidden. Which initiatives
    qualify is settled in ``app/services/platform/guilds_test.py``; this is the
    endpoint reaching that enrolment at all.
    """
    owner = await create_user(session)
    guild = await _a_listed_guild(session, name="Open Table", creator=owner)
    welcome, welcome_project = await _initiative_with_shared_project(
        session, guild, owner, name="Welcome", auto_join=True
    )
    _optin, optin_project = await _initiative_with_shared_project(
        session, guild, owner, name="Opt in", auto_join=False
    )

    joiner = await acting_user("member")

    # Not in the guild yet: the guild gate refuses before RLS is ever consulted.
    before = await client.get(
        f"/api/v1/g/{guild.id}/projects/{welcome_project.id}", headers=joiner.headers
    )
    assert before.status_code == 403

    response = await client.post(
        f"/api/v1/guilds/communities/{guild.id}/join", headers=joiner.headers
    )
    assert response.status_code == 200

    after = await client.get(
        f"/api/v1/g/{guild.id}/projects/{welcome_project.id}", headers=joiner.headers
    )
    assert after.status_code == 200
    assert after.json()["name"] == "Welcome work"

    # The initiative that did not ask for arrivals is still hidden — so the
    # enrolment, not plain guild membership, is what opened the first one.
    sibling = await client.get(
        f"/api/v1/g/{guild.id}/projects/{optin_project.id}", headers=joiner.headers
    )
    assert sibling.status_code == 404

    await route_session_to_guild(session, guild.id)
    rows = (
        await session.exec(
            select(InitiativeMember).where(InitiativeMember.user_id == joiner.user.id)
        )
    ).all()
    assert [row.initiative_id for row in rows] == [welcome.id]
    assert rows[0].oidc_provider_id is None


@pytest.mark.integration
async def test_a_profile_names_only_the_listed_communities(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A profile says which shelves someone is on, and nothing about the
    guilds they are in that never opted onto one. The count of who is there
    comes from asking — nothing about a guild row carries it."""
    listed = await _a_listed_guild(session)
    private = await create_guild(session)
    subject = await acting_user(
        guild_role=GuildRole.member, guild=listed, username="tinker"
    )
    await create_guild_membership(session, user=subject.user, guild=private)
    reader = await acting_user(guild_role=GuildRole.member, guild=listed)

    response = await client.get(
        f"/api/v1/users/{url_handle(subject.user.username, subject.user.discriminator)}/communities",
        headers=reader.headers,
    )

    assert response.status_code == 200
    assert [row["name"] for row in response.json()] == [listed.name]
    # The subject and the reader, at least.
    assert response.json()[0]["member_count"] >= 2


@pytest.mark.integration
async def test_a_profile_names_no_communities_where_the_directory_is_off(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Nothing is published on a deployment that publishes nothing."""
    listed = await _a_listed_guild(session)
    subject = await acting_user(
        guild_role=GuildRole.member, guild=listed, username="tinker"
    )
    reader = await acting_user("member")
    await _switch_directory_off(session)

    response = await client.get(
        f"/api/v1/users/{url_handle(subject.user.username, subject.user.discriminator)}/communities",
        headers=reader.headers,
    )

    assert response.status_code == 200
    assert response.json() == []


# ---------------------------------------------------------------------------
# The age gate: who is asked, who is not, and what the answer is worth.
# ---------------------------------------------------------------------------


def _birthdate_for_age(years: int) -> str:
    """A date somebody of this age could have been born on, as ISO text."""
    from datetime import datetime, timezone

    today = datetime.now(timezone.utc).date()
    return today.replace(year=today.year - years).isoformat()


def _birthdate_days_before_turning(years: int, days: int) -> str:
    """A date that is ``days`` short of a ``years``-th birthday."""
    from datetime import datetime, timedelta, timezone

    today = datetime.now(timezone.utc).date()
    return (today.replace(year=today.year - years) + timedelta(days=days)).isoformat()


def _tomorrow() -> str:
    from datetime import datetime, timedelta, timezone

    return (datetime.now(timezone.utc).date() + timedelta(days=1)).isoformat()


#: Comfortably past the minimum, for the tests that are not about the boundary.
ADULT_BIRTHDATE = _birthdate_for_age(30)


@pytest.mark.parametrize(
    "birthdate,expected_status,expected_detail",
    [
        pytest.param(ADULT_BIRTHDATE, 200, None, id="an adult"),
        pytest.param(
            _birthdate_for_age(13), 200, None, id="thirteen today, on the boundary"
        ),
        pytest.param(
            _birthdate_days_before_turning(13, 1),
            422,
            "USER_AGE_BELOW_MINIMUM",
            id="thirteen tomorrow, so twelve today",
        ),
        pytest.param(
            _birthdate_for_age(11), 422, "USER_AGE_BELOW_MINIMUM", id="eleven"
        ),
        pytest.param(
            _tomorrow(), 422, "USER_AGE_INVALID_BIRTHDATE", id="a date still to come"
        ),
        pytest.param(
            _birthdate_for_age(200),
            422,
            "USER_AGE_INVALID_BIRTHDATE",
            id="a date nobody was born on",
        ),
    ],
)
async def test_the_age_a_birthdate_states_is_what_the_answer_turns_on(
    client: AsyncClient,
    session: AsyncSession,
    acting_user,
    birthdate: str,
    expected_status: int,
    expected_detail: str | None,
):
    """The boundary belongs to the person on it: thirteen today is thirteen,
    and a birthday that has not come round is a year that has not happened. A
    date nobody could have been born on is refused separately, so the reply
    says which it was."""
    a = await acting_user("member", age_confirmed_at=None)

    response = await client.post(
        "/api/v1/users/me/age-confirmation",
        json={"birthdate": birthdate},
        headers=a.headers,
    )

    assert response.status_code == expected_status, response.text
    await session.refresh(a.user)
    if expected_detail is None:
        assert response.json()["age_confirmed_at"] is not None
        assert a.user.age_confirmed_at is not None
    else:
        assert response.json()["detail"] == expected_detail
        assert a.user.age_confirmed_at is None


@pytest.mark.parametrize(
    "prior_answer",
    ["never asked", "answered under age"],
)
async def test_join_refuses_an_account_that_has_not_confirmed_its_age(
    client: AsyncClient, session: AsyncSession, acting_user, prior_answer: str
):
    """Unanswered and answered-too-young are both "not confirmed" to the join."""
    a = await acting_user("member", age_confirmed_at=None)
    guild = await _a_listed_guild(session, name="Open Table")
    if prior_answer == "answered under age":
        await client.post(
            "/api/v1/users/me/age-confirmation",
            json={"birthdate": _birthdate_for_age(9)},
            headers=a.headers,
        )

    response = await client.post(
        f"/api/v1/guilds/communities/{guild.id}/join", headers=a.headers
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "GUILD_AGE_CONFIRMATION_REQUIRED"
    assert await _membership_of(session, guild=guild, user_id=a.user.id) is None


async def test_confirming_age_lets_the_same_account_join(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The whole loop: refused, tick the box, join."""
    a = await acting_user("member", age_confirmed_at=None)
    guild = await _a_listed_guild(session, name="Open Table")

    refused = await client.post(
        f"/api/v1/guilds/communities/{guild.id}/join", headers=a.headers
    )
    assert refused.status_code == 403

    confirmed = await client.post(
        "/api/v1/users/me/age-confirmation",
        json={"birthdate": ADULT_BIRTHDATE},
        headers=a.headers,
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["age_confirmed_at"] is not None

    joined = await client.post(
        f"/api/v1/guilds/communities/{guild.id}/join", headers=a.headers
    )
    assert joined.status_code == 200
    assert joined.json()["id"] == guild.id


async def test_join_allows_an_unconfirmed_account_when_the_gate_is_off(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """An owner who asserts every account here is an adult is not asking."""
    await app_settings_service.update_community_settings(
        session, community_directory_enabled=True, community_age_gate_enabled=False
    )
    a = await acting_user("member", age_confirmed_at=None)
    guild = await _a_listed_guild(session, name="Open Table")

    response = await client.post(
        f"/api/v1/guilds/communities/{guild.id}/join", headers=a.headers
    )

    assert response.status_code == 200


@pytest.mark.parametrize(
    "listed,directory_on,confirmed,expected",
    [
        pytest.param(True, True, False, True, id="a listed guild, unanswered"),
        pytest.param(False, True, False, False, id="a private guild asks nobody"),
        pytest.param(True, False, False, False, id="no directory, so nothing listed"),
        pytest.param(True, True, True, False, id="already answered"),
    ],
)
async def test_the_standing_gate_is_asked_of_members_of_listed_guilds(
    client: AsyncClient,
    session: AsyncSession,
    acting_user,
    listed: bool,
    directory_on: bool,
    confirmed: bool,
    expected: bool,
):
    """The catch-all for a membership that arrived without anyone to ask — a
    group sync, or an admin adding somebody. It is asked, not stored: it holds
    for as long as the guild is listed and the answer is outstanding."""
    guild = (
        await _a_listed_guild(session, name="Open Table")
        if listed
        else await create_guild(session, name="Just Us")
    )
    a = await acting_user(
        guild_role=GuildRole.member, guild=guild, age_confirmed_at=None
    )
    if confirmed:
        await client.post(
            "/api/v1/users/me/age-confirmation",
            json={"birthdate": ADULT_BIRTHDATE},
            headers=a.headers,
        )
    if not directory_on:
        await _switch_directory_off(session)

    response = await client.get("/api/v1/users/me", headers=a.headers)

    assert response.status_code == 200
    assert response.json()["age_confirmation_required"] is expected


async def test_listing_a_guild_asks_the_members_it_already_had(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The gate follows the guild onto the shelf."""
    guild = await create_guild(session, name="Open Table")
    a = await acting_user(
        guild_role=GuildRole.member, guild=guild, age_confirmed_at=None
    )

    before = await client.get("/api/v1/users/me", headers=a.headers)
    assert before.json()["age_confirmation_required"] is False

    await _list_as_community(session, guild)

    after = await client.get("/api/v1/users/me", headers=a.headers)
    assert after.json()["age_confirmation_required"] is True


async def test_confirming_twice_keeps_the_first_answer(
    client: AsyncClient, acting_user
):
    """The record is when they first said it, not when they last clicked."""
    a = await acting_user("member", age_confirmed_at=None)

    first = await client.post(
        "/api/v1/users/me/age-confirmation",
        json={"birthdate": ADULT_BIRTHDATE},
        headers=a.headers,
    )
    second = await client.post(
        "/api/v1/users/me/age-confirmation",
        json={"birthdate": ADULT_BIRTHDATE},
        headers=a.headers,
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["age_confirmed_at"] == second.json()["age_confirmed_at"]


async def test_the_answer_stands_against_a_second_try(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A question you can re-answer until it comes out right is not a question."""
    a = await acting_user("member", age_confirmed_at=None)

    await client.post(
        "/api/v1/users/me/age-confirmation",
        json={"birthdate": _birthdate_for_age(9)},
        headers=a.headers,
    )
    second = await client.post(
        "/api/v1/users/me/age-confirmation",
        json={"birthdate": ADULT_BIRTHDATE},
        headers=a.headers,
    )

    assert second.status_code == 409
    assert second.json()["detail"] == "USER_AGE_ANSWER_STANDS"
    await session.refresh(a.user)
    assert a.user.age_confirmed_at is None


@pytest.mark.parametrize(
    "years,expected_status",
    [
        pytest.param(30, 200, id="an answer that passes"),
        pytest.param(9, 422, id="an answer that does not"),
    ],
)
async def test_the_date_is_not_kept_anywhere(
    client: AsyncClient,
    session: AsyncSession,
    acting_user,
    years: int,
    expected_status: int,
):
    """The promise the surface makes: we asked, we did not write it down. The
    fact is recorded either way — confirmed, or answered under the minimum.

    Checked against the row rather than against intent — every column of the
    account is searched for the date that was just sent.
    """
    a = await acting_user("member", age_confirmed_at=None)
    birthdate = _birthdate_for_age(years)

    response = await client.post(
        "/api/v1/users/me/age-confirmation",
        json={"birthdate": birthdate},
        headers=a.headers,
    )
    assert response.status_code == expected_status, response.text

    # Nothing in the reply carries it back either.
    assert birthdate not in response.text

    await session.refresh(a.user)
    if expected_status == 200:
        assert a.user.age_confirmed_at is not None
        assert a.user.age_below_minimum_at is None
    else:
        assert a.user.age_below_minimum_at is not None
        assert a.user.age_confirmed_at is None

    year, month, day = birthdate.split("-")
    for column in a.user.__table__.columns.keys():  # noqa: SIM118
        rendered = str(getattr(a.user, column))
        assert birthdate not in rendered, f"users.{column} holds the date"
        # The date reshaped is still the date.
        assert f"{day}/{month}/{year}" not in rendered, f"users.{column} holds the date"


@pytest.mark.parametrize(
    "tier,expected_status",
    [
        pytest.param(UserRole.support, 200, id="support, the lowest rung that has it"),
        pytest.param(UserRole.member, 403, id="an ordinary member"),
    ],
)
async def test_lifting_an_age_block_is_a_platform_capability(
    client: AsyncClient,
    session: AsyncSession,
    acting_user,
    tier: UserRole,
    expected_status: int,
):
    """The way back from a mistyped year, and who holds it."""
    subject = await acting_user("member", age_confirmed_at=None)
    await client.post(
        "/api/v1/users/me/age-confirmation",
        json={"birthdate": _birthdate_for_age(9)},
        headers=subject.headers,
    )
    await session.refresh(subject.user)
    assert subject.user.age_below_minimum_at is not None

    staff = await acting_user(tier)
    response = await client.delete(
        f"/api/v1/admin/users/{subject.user.id}/age-block", headers=staff.headers
    )

    assert response.status_code == expected_status, response.text
    if expected_status != 200:
        return

    # And the question is answerable again, from scratch.
    retry = await client.post(
        "/api/v1/users/me/age-confirmation",
        json={"birthdate": ADULT_BIRTHDATE},
        headers=subject.headers,
    )
    assert retry.status_code == 200


async def test_lifting_a_block_that_is_not_there_says_so(
    client: AsyncClient, acting_user
):
    subject = await acting_user("member")
    support = await acting_user(UserRole.support)

    response = await client.delete(
        f"/api/v1/admin/users/{subject.user.id}/age-block", headers=support.headers
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "USER_AGE_NOT_BLOCKED"
