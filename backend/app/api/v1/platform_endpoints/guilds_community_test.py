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
from app.models.tenant.initiative import InitiativeMember
from app.models.tenant.resource_grant import ResourceAccessLevel, ResourceGrant
from app.services.platform import app_settings as app_settings_service
from app.testing.factories import (
    create_guild,
    create_guild_membership,
    create_initiative,
    create_project,
    create_user,
    get_auth_headers,
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


@pytest.mark.integration
async def test_directory_lists_only_opted_in_guilds(
    client: AsyncClient, session: AsyncSession
):
    """A guild appears only once it has opted in — invite-only guilds do not."""
    user = await create_user(session, email="browser@example.com")
    listed = await create_guild(session, name="Open Table")
    await create_guild(session, name="Private Office")
    await _list_as_community(session, listed)

    response = await client.get(
        "/api/v1/guilds/communities", headers=get_auth_headers(user)
    )

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert [item["name"] for item in data["items"]] == ["Open Table"]


@pytest.mark.integration
async def test_directory_hides_non_active_guilds(
    client: AsyncClient, session: AsyncSession
):
    """A frozen or suspended guild takes no new members, so it is not offered."""
    user = await create_user(session, email="browser@example.com")
    for name, status_value in (
        ("Suspended Hall", GuildStatus.suspended.value),
        ("Frozen Hall", GuildStatus.read_only.value),
    ):
        guild = await create_guild(session, name=name)
        await _list_as_community(session, guild)
        guild.status = status_value
        session.add(guild)
    await session.commit()

    response = await client.get(
        "/api/v1/guilds/communities", headers=get_auth_headers(user)
    )

    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 0}


@pytest.mark.integration
async def test_directory_card_carries_only_published_fields(
    client: AsyncClient, session: AsyncSession
):
    """The card is what the guild published, plus its roster size — no more."""
    user = await create_user(session, email="browser@example.com")
    owner = await create_user(session, email="owner@example.com")
    guild = await create_guild(
        session, name="Riverside Players", description="Community theatre."
    )
    await create_guild_membership(session, user=owner, guild=guild)
    await _list_as_community(session, guild, categories=["art", "writing"])

    response = await client.get(
        "/api/v1/guilds/communities", headers=get_auth_headers(user)
    )

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
    client: AsyncClient, session: AsyncSession
):
    user = await create_user(session, email="member@example.com")
    guild = await create_guild(session, name="Open Table")
    await create_guild_membership(session, user=user, guild=guild)
    await _list_as_community(session, guild)

    response = await client.get(
        "/api/v1/guilds/communities", headers=get_auth_headers(user)
    )

    assert response.json()["items"][0]["already_member"] is True


@pytest.mark.integration
async def test_directory_filters_by_category(
    client: AsyncClient, session: AsyncSession
):
    user = await create_user(session, email="browser@example.com")
    await _list_as_community(
        session, await create_guild(session, name="Dice Goblins"), categories=["ttrpg"]
    )
    await _list_as_community(
        session, await create_guild(session, name="Life Drawing"), categories=["art"]
    )
    # A guild on two shelves is reachable from either.
    await _list_as_community(
        session,
        await create_guild(session, name="Painted Minis"),
        categories=["art", "ttrpg"],
    )

    response = await client.get(
        "/api/v1/guilds/communities?category=ttrpg", headers=get_auth_headers(user)
    )

    assert response.status_code == 200
    assert sorted(item["name"] for item in response.json()["items"]) == [
        "Dice Goblins",
        "Painted Minis",
    ]


@pytest.mark.integration
async def test_directory_rejects_an_unknown_category(
    client: AsyncClient, session: AsyncSession
):
    user = await create_user(session, email="browser@example.com")

    response = await client.get(
        "/api/v1/guilds/communities?category=nonsense", headers=get_auth_headers(user)
    )

    assert response.status_code == 422


@pytest.mark.integration
async def test_directory_searches_name_and_description(
    client: AsyncClient, session: AsyncSession
):
    user = await create_user(session, email="browser@example.com")
    await _list_as_community(session, await create_guild(session, name="Dice Goblins"))
    await _list_as_community(
        session,
        await create_guild(
            session, name="Painted Minis", description="We paint dice trays too."
        ),
    )
    await _list_as_community(session, await create_guild(session, name="Life Drawing"))

    response = await client.get(
        "/api/v1/guilds/communities?q=dice", headers=get_auth_headers(user)
    )

    assert sorted(item["name"] for item in response.json()["items"]) == [
        "Dice Goblins",
        "Painted Minis",
    ]


@pytest.mark.integration
async def test_directory_lists_the_busiest_guilds_first(
    client: AsyncClient, session: AsyncSession
):
    """Who is already in a guild is what someone with none is choosing between."""
    user = await create_user(session, email="browser@example.com")
    # Named against the order they belong in, so an alphabetical sort cannot
    # pass this by accident.
    await _list_as_community(session, await create_guild(session, name="Aardvark Club"))
    busy = await _list_as_community(
        session, await create_guild(session, name="Zebra Hall")
    )
    for index in range(3):
        await create_guild_membership(
            session,
            user=await create_user(session, email=f"joiner{index}@example.com"),
            guild=busy,
        )

    response = await client.get(
        "/api/v1/guilds/communities", headers=get_auth_headers(user)
    )

    items = response.json()["items"]
    assert [item["name"] for item in items] == ["Zebra Hall", "Aardvark Club"]
    assert [item["member_count"] for item in items] == [3, 0]


@pytest.mark.integration
async def test_directory_searches_every_guild_not_only_a_loaded_page(
    client: AsyncClient, session: AsyncSession
):
    """The search is the query's, not the caller's.

    The match is the quietest guild here and the page holds one guild, so it is
    on no page a browser would have loaded by the time it searched.
    """
    user = await create_user(session, email="browser@example.com")
    busy = await _list_as_community(
        session, await create_guild(session, name="Crowded Hall")
    )
    for index in range(3):
        await create_guild_membership(
            session,
            user=await create_user(session, email=f"joiner{index}@example.com"),
            guild=busy,
        )
    await _list_as_community(session, await create_guild(session, name="Dice Goblins"))

    response = await client.get(
        "/api/v1/guilds/communities?q=goblins&page_size=1",
        headers=get_auth_headers(user),
    )

    body = response.json()
    assert [item["name"] for item in body["items"]] == ["Dice Goblins"]
    assert body["total"] == 1


@pytest.mark.integration
async def test_directory_paginates(client: AsyncClient, session: AsyncSession):
    user = await create_user(session, email="browser@example.com")
    for index in range(3):
        await _list_as_community(
            session, await create_guild(session, name=f"Guild {index}")
        )

    headers = get_auth_headers(user)
    first = await client.get(
        "/api/v1/guilds/communities?page=1&page_size=2", headers=headers
    )
    second = await client.get(
        "/api/v1/guilds/communities?page=2&page_size=2", headers=headers
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
async def test_join_a_community_guild_without_an_invite(
    client: AsyncClient, session: AsyncSession
):
    user = await create_user(session, email="joiner@example.com")
    guild = await create_guild(session, name="Open Table")
    await _list_as_community(session, guild)

    response = await client.post(
        f"/api/v1/guilds/communities/{guild.id}/join", headers=get_auth_headers(user)
    )

    assert response.status_code == 200
    assert response.json()["id"] == guild.id
    assert response.json()["role"] == GuildRole.member.value
    membership = (
        await session.exec(
            select(GuildMembership).where(
                GuildMembership.guild_id == guild.id,
                GuildMembership.user_id == user.id,
            )
        )
    ).one_or_none()
    assert membership is not None
    assert membership.role == GuildRole.member


@pytest.mark.integration
async def test_join_is_idempotent(client: AsyncClient, session: AsyncSession):
    """Joining twice returns the guild rather than erroring or duplicating."""
    user = await create_user(session, email="joiner@example.com")
    guild = await create_guild(session, name="Open Table")
    await _list_as_community(session, guild)
    headers = get_auth_headers(user)

    first = await client.post(
        f"/api/v1/guilds/communities/{guild.id}/join", headers=headers
    )
    second = await client.post(
        f"/api/v1/guilds/communities/{guild.id}/join", headers=headers
    )

    assert first.status_code == 200
    assert second.status_code == 200
    memberships = (
        await session.exec(
            select(GuildMembership).where(
                GuildMembership.guild_id == guild.id,
                GuildMembership.user_id == user.id,
            )
        )
    ).all()
    assert len(memberships) == 1


@pytest.mark.integration
async def test_join_refuses_a_guild_that_is_not_listed(
    client: AsyncClient, session: AsyncSession
):
    """An unlisted guild has published nothing, its id included — so, 404."""
    user = await create_user(session, email="joiner@example.com")
    guild = await create_guild(session, name="Private Office")

    response = await client.post(
        f"/api/v1/guilds/communities/{guild.id}/join", headers=get_auth_headers(user)
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "GUILD_NOT_A_COMMUNITY"
    membership = (
        await session.exec(
            select(GuildMembership).where(
                GuildMembership.guild_id == guild.id,
                GuildMembership.user_id == user.id,
            )
        )
    ).one_or_none()
    assert membership is None


@pytest.mark.integration
async def test_join_refuses_a_suspended_community(
    client: AsyncClient, session: AsyncSession
):
    user = await create_user(session, email="joiner@example.com")
    guild = await create_guild(session, name="Open Table")
    await _list_as_community(session, guild)
    guild.status = GuildStatus.suspended.value
    session.add(guild)
    await session.commit()

    response = await client.post(
        f"/api/v1/guilds/communities/{guild.id}/join", headers=get_auth_headers(user)
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "GUILD_NOT_A_COMMUNITY"


@pytest.mark.integration
async def test_join_refuses_a_missing_guild(client: AsyncClient, session: AsyncSession):
    user = await create_user(session, email="joiner@example.com")

    response = await client.post(
        "/api/v1/guilds/communities/999999/join", headers=get_auth_headers(user)
    )

    assert response.status_code == 404


@pytest.mark.integration
async def test_join_respects_the_member_cap(client: AsyncClient, session: AsyncSession):
    """The directory does not bypass the guild's operator-set seat limit.

    Two seats, both taken: a listable guild (one seat could never admit anyone,
    so it would be refused as unlisted instead) that happens to be full today.
    """
    user = await create_user(session, email="joiner@example.com")
    guild = await create_guild(session, name="Open Table")
    await _list_as_community(session, guild)
    await create_guild_membership(session, guild=guild)
    await create_guild_membership(session, guild=guild)
    await guild_administration(session, guild, max_users=2)

    response = await client.post(
        f"/api/v1/guilds/communities/{guild.id}/join", headers=get_auth_headers(user)
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "GUILD_USER_LIMIT_REACHED"


@pytest.mark.integration
async def test_guild_admin_opts_into_the_directory(
    client: AsyncClient, session: AsyncSession
):
    admin = await create_user(session, email="admin@example.com")
    guild = await create_guild(session, name="Open Table")
    await create_guild_membership(
        session, user=admin, guild=guild, role=GuildRole.admin
    )

    response = await client.patch(
        f"/api/v1/guilds/{guild.id}",
        json={
            "is_community": True,
            "categories": ["gaming", "ttrpg"],
            "has_adult_content": False,
        },
        headers=get_auth_headers(admin),
    )

    assert response.status_code == 200
    assert response.json()["is_community"] is True
    assert response.json()["categories"] == ["gaming", "ttrpg"]
    assert response.json()["has_adult_content"] is False
    await session.refresh(guild)
    assert guild.is_community is True
    assert guild.categories == ["gaming", "ttrpg"]
    assert guild.has_adult_content is False


@pytest.mark.integration
async def test_categories_are_deduplicated_and_ordered(
    client: AsyncClient, session: AsyncSession
):
    """Whatever order the boxes were ticked in, storage is canonical."""
    admin = await create_user(session, email="admin@example.com")
    guild = await create_guild(session, name="Open Table")
    await create_guild_membership(
        session, user=admin, guild=guild, role=GuildRole.admin
    )

    response = await client.patch(
        f"/api/v1/guilds/{guild.id}",
        json={"categories": ["ttrpg", "art", "ttrpg"]},
        headers=get_auth_headers(admin),
    )

    assert response.status_code == 200
    assert response.json()["categories"] == ["art", "ttrpg"]


@pytest.mark.integration
async def test_patch_leaves_the_listing_alone_when_not_mentioned(
    client: AsyncClient, session: AsyncSession
):
    """Renaming a guild must not silently de-list it."""
    admin = await create_user(session, email="admin@example.com")
    guild = await create_guild(session, name="Open Table")
    await create_guild_membership(
        session, user=admin, guild=guild, role=GuildRole.admin
    )
    await _list_as_community(session, guild, categories=["gaming"])

    response = await client.patch(
        f"/api/v1/guilds/{guild.id}",
        json={"name": "Open Table Renamed"},
        headers=get_auth_headers(admin),
    )

    assert response.status_code == 200
    assert response.json()["is_community"] is True
    assert response.json()["categories"] == ["gaming"]


@pytest.mark.integration
async def test_a_member_cannot_opt_the_guild_in(
    client: AsyncClient, session: AsyncSession
):
    member = await create_user(session, email="member@example.com")
    guild = await create_guild(session, name="Open Table")
    await create_guild_membership(
        session, user=member, guild=guild, role=GuildRole.member
    )

    response = await client.patch(
        f"/api/v1/guilds/{guild.id}",
        json={"is_community": True},
        headers=get_auth_headers(member),
    )

    assert response.status_code == 403
    await session.refresh(guild)
    assert guild.is_community is False


@pytest.mark.integration
async def test_an_unknown_category_is_rejected(
    client: AsyncClient, session: AsyncSession
):
    admin = await create_user(session, email="admin@example.com")
    guild = await create_guild(session, name="Open Table")
    await create_guild_membership(
        session, user=admin, guild=guild, role=GuildRole.admin
    )

    response = await client.patch(
        f"/api/v1/guilds/{guild.id}",
        json={"categories": ["underwater-basket-weaving"]},
        headers=get_auth_headers(admin),
    )

    assert response.status_code == 422


# ---------------------------------------------------------------------------
# What a guild must be before it can be listed
# ---------------------------------------------------------------------------


async def _admin_of(session: AsyncSession, **guild_fields) -> tuple[Guild, dict]:
    """A guild plus the headers of one of its admins."""
    admin = await create_user(session)
    guild = await create_guild(session, **guild_fields)
    await create_guild_membership(
        session, user=admin, guild=guild, role=GuildRole.admin
    )
    return guild, get_auth_headers(admin)


@pytest.mark.integration
async def test_the_adult_content_declaration_starts_unanswered(
    client: AsyncClient, session: AsyncSession
):
    """It is a question only the directory asks, so an ordinary guild has no
    answer on file rather than a default one."""
    guild, headers = await _admin_of(session)

    response = await client.get("/api/v1/guilds/", headers=headers)

    assert response.status_code == 200
    entry = next(item for item in response.json() if item["id"] == guild.id)
    assert entry["has_adult_content"] is None
    assert entry["is_community"] is False


@pytest.mark.integration
async def test_listing_needs_at_least_one_category(
    client: AsyncClient, session: AsyncSession
):
    """A card nobody can reach by browsing is not a listing."""
    guild, headers = await _admin_of(session)

    response = await client.patch(
        f"/api/v1/guilds/{guild.id}",
        json={"is_community": True, "has_adult_content": False},
        headers=headers,
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "GUILD_COMMUNITY_REQUIRES_CATEGORY"
    await session.refresh(guild)
    assert guild.is_community is False


@pytest.mark.integration
async def test_listing_needs_the_content_question_answered(
    client: AsyncClient, session: AsyncSession
):
    """Unanswered is not the same as answered "no" — the admin has to certify."""
    guild, headers = await _admin_of(session)

    response = await client.patch(
        f"/api/v1/guilds/{guild.id}",
        json={"is_community": True, "categories": ["art"]},
        headers=headers,
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "GUILD_COMMUNITY_CONTENT_NOT_DECLARED"
    await session.refresh(guild)
    assert guild.is_community is False


@pytest.mark.integration
async def test_an_adult_guild_cannot_be_listed(
    client: AsyncClient, session: AsyncSession
):
    guild, headers = await _admin_of(session)

    response = await client.patch(
        f"/api/v1/guilds/{guild.id}",
        json={
            "is_community": True,
            "categories": ["art"],
            "has_adult_content": True,
        },
        headers=headers,
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "GUILD_COMMUNITY_ADULT_CONTENT"
    await session.refresh(guild)
    assert guild.is_community is False


@pytest.mark.integration
async def test_an_unlisted_guild_may_declare_adult_content(
    client: AsyncClient, session: AsyncSession
):
    """The declaration is the guild's to make; it only closes off the directory."""
    guild, headers = await _admin_of(session)

    response = await client.patch(
        f"/api/v1/guilds/{guild.id}",
        json={"has_adult_content": True},
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["has_adult_content"] is True
    await session.refresh(guild)
    assert guild.has_adult_content is True


@pytest.mark.integration
async def test_a_one_seat_guild_cannot_be_listed(
    client: AsyncClient, session: AsyncSession
):
    """One seat means no joiner can ever take one, so the card would be a
    button that is guaranteed to fail."""
    guild, headers = await _admin_of(session, max_users=1)

    response = await client.patch(
        f"/api/v1/guilds/{guild.id}",
        json={
            "is_community": True,
            "categories": ["art"],
            "has_adult_content": False,
        },
        headers=headers,
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "GUILD_COMMUNITY_REQUIRES_CAPACITY"
    await session.refresh(guild)
    assert guild.is_community is False


@pytest.mark.integration
async def test_a_two_seat_guild_can_be_listed(
    client: AsyncClient, session: AsyncSession
):
    """Room for one more is room enough — the cap itself is not the objection."""
    guild, headers = await _admin_of(session, max_users=2)

    response = await client.patch(
        f"/api/v1/guilds/{guild.id}",
        json={
            "is_community": True,
            "categories": ["art"],
            "has_adult_content": False,
        },
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["is_community"] is True


@pytest.mark.integration
async def test_the_rules_are_checked_against_the_resulting_guild(
    client: AsyncClient, session: AsyncSession
):
    """Clearing the shelves of a guild that is already listed has to fail for
    the same reason as listing one with none — the rule is about the state the
    guild ends up in, not about what this request happened to carry."""
    guild, headers = await _admin_of(session)
    await _list_as_community(session, guild, categories=["art"])

    response = await client.patch(
        f"/api/v1/guilds/{guild.id}",
        json={"categories": []},
        headers=headers,
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "GUILD_COMMUNITY_REQUIRES_CATEGORY"
    await session.refresh(guild)
    assert guild.categories == ["art"]


@pytest.mark.integration
async def test_a_listed_guild_cannot_turn_itself_adult(
    client: AsyncClient, session: AsyncSession
):
    guild, headers = await _admin_of(session)
    await _list_as_community(session, guild, categories=["art"])

    response = await client.patch(
        f"/api/v1/guilds/{guild.id}",
        json={"has_adult_content": True},
        headers=headers,
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "GUILD_COMMUNITY_ADULT_CONTENT"
    await session.refresh(guild)
    assert guild.has_adult_content is False


@pytest.mark.integration
async def test_delisting_is_never_blocked_by_the_listing_rules(
    client: AsyncClient, session: AsyncSession
):
    """Coming off the directory asks nothing of the guild."""
    guild, headers = await _admin_of(session)
    await _list_as_community(session, guild, categories=["art"])

    response = await client.patch(
        f"/api/v1/guilds/{guild.id}",
        json={"is_community": False, "categories": []},
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["is_community"] is False


@pytest.mark.integration
async def test_the_directory_drops_a_guild_whose_cap_was_lowered_later(
    client: AsyncClient, session: AsyncSession
):
    """Only an operator sets the cap, and they can set it after the listing was
    made — so the directory re-checks it rather than trusting the opt-in."""
    user = await create_user(session, email="browser@example.com")
    guild = await create_guild(session, name="Open Table")
    await _list_as_community(session, guild)
    await guild_administration(session, guild, max_users=1)

    response = await client.get(
        "/api/v1/guilds/communities", headers=get_auth_headers(user)
    )

    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 0}


@pytest.mark.integration
async def test_join_refuses_a_guild_the_directory_would_not_show(
    client: AsyncClient, session: AsyncSession
):
    """Asking for it by id is not a way around the directory's own filter."""
    user = await create_user(session, email="joiner@example.com")
    guild = await create_guild(session, name="Open Table")
    await _list_as_community(session, guild)
    await guild_administration(session, guild, max_users=1)

    response = await client.post(
        f"/api/v1/guilds/communities/{guild.id}/join", headers=get_auth_headers(user)
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "GUILD_NOT_A_COMMUNITY"


# ---------------------------------------------------------------------------
# The platform-owner switch
# ---------------------------------------------------------------------------


async def _switch_directory_off(session: AsyncSession) -> None:
    await app_settings_service.update_community_settings(
        session, community_directory_enabled=False
    )


@pytest.mark.integration
async def test_browsing_is_refused_where_the_directory_is_off(
    client: AsyncClient, session: AsyncSession
):
    """Refused outright, not answered with an empty page: a deployment without a
    directory has no directory, as distinct from one where nobody has listed."""
    user = await create_user(session, email="browser@example.com")
    guild = await create_guild(session, name="Open Table")
    await _list_as_community(session, guild)
    await _switch_directory_off(session)

    response = await client.get(
        "/api/v1/guilds/communities", headers=get_auth_headers(user)
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "COMMUNITY_DIRECTORY_DISABLED"


@pytest.mark.integration
async def test_joining_is_refused_where_the_directory_is_off(
    client: AsyncClient, session: AsyncSession
):
    """The invite-free join exists only as the directory's other half."""
    user = await create_user(session, email="joiner@example.com")
    guild = await create_guild(session, name="Open Table")
    await _list_as_community(session, guild)
    await _switch_directory_off(session)

    response = await client.post(
        f"/api/v1/guilds/communities/{guild.id}/join", headers=get_auth_headers(user)
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "COMMUNITY_DIRECTORY_DISABLED"
    membership = (
        await session.exec(
            select(GuildMembership).where(
                GuildMembership.guild_id == guild.id,
                GuildMembership.user_id == user.id,
            )
        )
    ).one_or_none()
    assert membership is None


@pytest.mark.integration
async def test_a_guild_cannot_list_itself_where_the_directory_is_off(
    client: AsyncClient, session: AsyncSession
):
    guild, headers = await _admin_of(session, name="Open Table")
    await _switch_directory_off(session)

    response = await client.patch(
        f"/api/v1/guilds/{guild.id}",
        json={
            "is_community": True,
            "categories": ["gaming"],
            "has_adult_content": False,
        },
        headers=headers,
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "COMMUNITY_DIRECTORY_DISABLED"
    await session.refresh(guild)
    assert guild.is_community is False


@pytest.mark.integration
async def test_a_listed_guild_can_still_unlist_where_the_directory_is_off(
    client: AsyncClient, session: AsyncSession
):
    """Switching the directory off must not strand a guild inside a listing it
    can no longer withdraw."""
    guild, headers = await _admin_of(session, name="Open Table")
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
    client: AsyncClient, session: AsyncSession
):
    """Off hides the listings; it does not unpublish anybody. Switching it back
    on shows the same guilds."""
    user = await create_user(session, email="browser@example.com")
    guild = await create_guild(session, name="Open Table")
    await _list_as_community(session, guild)
    await _switch_directory_off(session)
    await app_settings_service.update_community_settings(
        session, community_directory_enabled=True
    )

    response = await client.get(
        "/api/v1/guilds/communities", headers=get_auth_headers(user)
    )

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
    client: AsyncClient, session: AsyncSession
):
    """Joining a public guild lands the arrival in real content.

    The membership row is the only thing that moves, and RLS does the rest: the
    auto-join initiative's project is reachable the moment the join returns,
    while its opt-in sibling in the same guild stays hidden.
    """
    owner = await create_user(session, email="owner@example.com")
    guild = await create_guild(session, name="Open Table", creator=owner)
    await _list_as_community(session, guild)
    welcome, welcome_project = await _initiative_with_shared_project(
        session, guild, owner, name="Welcome", auto_join=True
    )
    _optin, optin_project = await _initiative_with_shared_project(
        session, guild, owner, name="Opt in", auto_join=False
    )

    joiner = await create_user(session, email="joiner@example.com")
    headers = get_auth_headers(joiner)

    # Not in the guild yet: the guild gate refuses before RLS is ever consulted.
    before = await client.get(
        f"/api/v1/g/{guild.id}/projects/{welcome_project.id}", headers=headers
    )
    assert before.status_code == 403

    response = await client.post(
        f"/api/v1/guilds/communities/{guild.id}/join", headers=headers
    )
    assert response.status_code == 200

    after = await client.get(
        f"/api/v1/g/{guild.id}/projects/{welcome_project.id}", headers=headers
    )
    assert after.status_code == 200
    assert after.json()["name"] == "Welcome work"

    # The initiative that did not ask for arrivals is still hidden — so the
    # enrolment, not plain guild membership, is what opened the first one.
    sibling = await client.get(
        f"/api/v1/g/{guild.id}/projects/{optin_project.id}", headers=headers
    )
    assert sibling.status_code == 404

    await route_session_to_guild(session, guild.id)
    rows = (
        await session.exec(
            select(InitiativeMember).where(InitiativeMember.user_id == joiner.id)
        )
    ).all()
    assert [row.initiative_id for row in rows] == [welcome.id]
    assert rows[0].oidc_managed is False


@pytest.mark.integration
async def test_community_join_of_a_guild_with_no_auto_join_initiatives(
    client: AsyncClient, session: AsyncSession
):
    """The unchanged path: nothing flagged, so the join behaves exactly as it
    did before the feature."""
    owner = await create_user(session, email="owner@example.com")
    guild = await create_guild(session, name="Open Table", creator=owner)
    await _list_as_community(session, guild)
    await create_initiative(session, guild, owner, name="Private")

    joiner = await create_user(session, email="joiner@example.com")
    response = await client.post(
        f"/api/v1/guilds/communities/{guild.id}/join", headers=get_auth_headers(joiner)
    )

    assert response.status_code == 200
    assert response.json()["role"] == GuildRole.member.value
    await route_session_to_guild(session, guild.id)
    rows = (
        await session.exec(
            select(InitiativeMember).where(InitiativeMember.user_id == joiner.id)
        )
    ).all()
    assert rows == []


@pytest.mark.integration
async def test_repeat_community_join_does_not_duplicate_enrolment(
    client: AsyncClient, session: AsyncSession
):
    """A second join is still a no-op, enrolment included."""
    owner = await create_user(session, email="owner@example.com")
    guild = await create_guild(session, name="Open Table", creator=owner)
    await _list_as_community(session, guild)
    welcome = await create_initiative(
        session, guild, owner, name="Welcome", join_policy="open", auto_join=True
    )

    joiner = await create_user(session, email="joiner@example.com")
    headers = get_auth_headers(joiner)
    first = await client.post(
        f"/api/v1/guilds/communities/{guild.id}/join", headers=headers
    )
    second = await client.post(
        f"/api/v1/guilds/communities/{guild.id}/join", headers=headers
    )

    assert first.status_code == 200
    assert second.status_code == 200
    await route_session_to_guild(session, guild.id)
    rows = (
        await session.exec(
            select(InitiativeMember).where(
                InitiativeMember.user_id == joiner.id,
                InitiativeMember.initiative_id == welcome.id,
            )
        )
    ).all()
    assert len(rows) == 1


@pytest.mark.integration
async def test_a_profile_names_only_the_listed_communities(
    client: AsyncClient, session: AsyncSession
):
    """A profile says which shelves someone is on, and nothing about the
    guilds they are in that never opted onto one."""
    subject = await create_user(session, username="tinker")
    reader = await create_user(session)
    listed = await _list_as_community(session, await create_guild(session))
    private = await create_guild(session)
    for guild in (listed, private):
        await create_guild_membership(session, user=subject, guild=guild)

    response = await client.get(
        f"/api/v1/users/{url_handle(subject.username, subject.discriminator)}/communities",
        headers=get_auth_headers(reader),
    )

    assert response.status_code == 200
    assert [row["name"] for row in response.json()] == [listed.name]


@pytest.mark.integration
async def test_a_profile_names_no_communities_where_the_directory_is_off(
    client: AsyncClient, session: AsyncSession
):
    """Nothing is published on a deployment that publishes nothing."""
    subject = await create_user(session, username="tinker")
    reader = await create_user(session)
    listed = await _list_as_community(session, await create_guild(session))
    await create_guild_membership(session, user=subject, guild=listed)
    await app_settings_service.update_community_settings(
        session, community_directory_enabled=False
    )

    response = await client.get(
        f"/api/v1/users/{url_handle(subject.username, subject.discriminator)}/communities",
        headers=get_auth_headers(reader),
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


#: Comfortably past the minimum, for the tests that are not about the boundary.
ADULT_BIRTHDATE = _birthdate_for_age(30)


async def test_join_refuses_an_account_that_has_not_confirmed_its_age(
    client: AsyncClient, session: AsyncSession
):
    user = await create_user(session, email="minor@example.com", age_confirmed_at=None)
    guild = await create_guild(session, name="Open Table")
    await _list_as_community(session, guild)

    response = await client.post(
        f"/api/v1/guilds/communities/{guild.id}/join", headers=get_auth_headers(user)
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "GUILD_AGE_CONFIRMATION_REQUIRED"
    membership = (
        await session.exec(
            select(GuildMembership).where(
                GuildMembership.guild_id == guild.id,
                GuildMembership.user_id == user.id,
            )
        )
    ).one_or_none()
    assert membership is None


async def test_confirming_age_lets_the_same_account_join(
    client: AsyncClient, session: AsyncSession
):
    """The whole loop: refused, tick the box, join."""
    user = await create_user(session, email="joiner@example.com", age_confirmed_at=None)
    guild = await create_guild(session, name="Open Table")
    await _list_as_community(session, guild)
    headers = get_auth_headers(user)

    refused = await client.post(
        f"/api/v1/guilds/communities/{guild.id}/join", headers=headers
    )
    assert refused.status_code == 403

    confirmed = await client.post(
        "/api/v1/users/me/age-confirmation",
        json={"birthdate": ADULT_BIRTHDATE},
        headers=headers,
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["age_confirmed_at"] is not None

    joined = await client.post(
        f"/api/v1/guilds/communities/{guild.id}/join", headers=headers
    )
    assert joined.status_code == 200
    assert joined.json()["id"] == guild.id


async def test_join_allows_an_unconfirmed_account_when_the_gate_is_off(
    client: AsyncClient, session: AsyncSession
):
    """An owner who asserts every account here is an adult is not asking."""
    await app_settings_service.update_community_settings(
        session, community_directory_enabled=True, community_age_gate_enabled=False
    )
    user = await create_user(session, email="adult@example.com", age_confirmed_at=None)
    guild = await create_guild(session, name="Open Table")
    await _list_as_community(session, guild)

    response = await client.post(
        f"/api/v1/guilds/communities/{guild.id}/join", headers=get_auth_headers(user)
    )

    assert response.status_code == 200


async def test_unconfirmed_member_of_a_listed_guild_is_asked_on_next_read(
    client: AsyncClient, session: AsyncSession
):
    """The catch-all: a membership that arrived without anyone to ask.

    Written straight to the table the way a group sync or an admin would, so
    the join endpoint's refusal is not what is under test here.
    """
    user = await create_user(session, email="synced@example.com", age_confirmed_at=None)
    guild = await create_guild(session, name="Open Table")
    await _list_as_community(session, guild)
    session.add(
        GuildMembership(guild_id=guild.id, user_id=user.id, role=GuildRole.member)
    )
    await session.commit()

    response = await client.get("/api/v1/users/me", headers=get_auth_headers(user))

    assert response.status_code == 200
    assert response.json()["age_confirmation_required"] is True


async def test_unlisted_guild_asks_nobody_their_age(
    client: AsyncClient, session: AsyncSession
):
    """A private guild is not a public community, so the gate never applies."""
    user = await create_user(
        session, email="private@example.com", age_confirmed_at=None
    )
    guild = await create_guild(session, name="Just Us")
    await create_guild_membership(session, user=user, guild=guild)

    response = await client.get("/api/v1/users/me", headers=get_auth_headers(user))

    assert response.status_code == 200
    assert response.json()["age_confirmation_required"] is False


async def test_listing_a_guild_asks_the_members_it_already_had(
    client: AsyncClient, session: AsyncSession
):
    """The gate is asked, not stored: it follows the guild onto the shelf."""
    user = await create_user(session, email="early@example.com", age_confirmed_at=None)
    guild = await create_guild(session, name="Open Table")
    await create_guild_membership(session, user=user, guild=guild)
    headers = get_auth_headers(user)

    before = await client.get("/api/v1/users/me", headers=headers)
    assert before.json()["age_confirmation_required"] is False

    await _list_as_community(session, guild)

    after = await client.get("/api/v1/users/me", headers=headers)
    assert after.json()["age_confirmation_required"] is True


async def test_confirmation_clears_the_standing_gate(
    client: AsyncClient, session: AsyncSession
):
    user = await create_user(
        session, email="answers@example.com", age_confirmed_at=None
    )
    guild = await create_guild(session, name="Open Table")
    await _list_as_community(session, guild)
    await create_guild_membership(session, user=user, guild=guild)
    headers = get_auth_headers(user)

    assert (await client.get("/api/v1/users/me", headers=headers)).json()[
        "age_confirmation_required"
    ] is True

    await client.post(
        "/api/v1/users/me/age-confirmation",
        json={"birthdate": ADULT_BIRTHDATE},
        headers=headers,
    )

    assert (await client.get("/api/v1/users/me", headers=headers)).json()[
        "age_confirmation_required"
    ] is False


async def test_somebody_too_young_confirms_nothing(
    client: AsyncClient, session: AsyncSession
):
    user = await create_user(
        session, email="declines@example.com", age_confirmed_at=None
    )

    response = await client.post(
        "/api/v1/users/me/age-confirmation",
        json={"birthdate": _birthdate_for_age(11)},
        headers=get_auth_headers(user),
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "USER_AGE_BELOW_MINIMUM"
    await session.refresh(user)
    assert user.age_confirmed_at is None


async def test_confirming_twice_keeps_the_first_answer(
    client: AsyncClient, session: AsyncSession
):
    """The record is when they first said it, not when they last clicked."""
    user = await create_user(
        session, email="repeats@example.com", age_confirmed_at=None
    )
    headers = get_auth_headers(user)

    first = await client.post(
        "/api/v1/users/me/age-confirmation",
        json={"birthdate": ADULT_BIRTHDATE},
        headers=headers,
    )
    second = await client.post(
        "/api/v1/users/me/age-confirmation",
        json={"birthdate": ADULT_BIRTHDATE},
        headers=headers,
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["age_confirmed_at"] == second.json()["age_confirmed_at"]


async def test_directory_off_asks_nobody(client: AsyncClient, session: AsyncSession):
    """With no directory there is no listed guild for anyone to be asked about."""
    user = await create_user(
        session, email="nowhere@example.com", age_confirmed_at=None
    )
    guild = await create_guild(session, name="Open Table")
    await _list_as_community(session, guild)
    await create_guild_membership(session, user=user, guild=guild)
    await app_settings_service.update_community_settings(
        session, community_directory_enabled=False
    )

    response = await client.get("/api/v1/users/me", headers=get_auth_headers(user))

    assert response.json()["age_confirmation_required"] is False


async def test_the_birthday_itself_counts(client: AsyncClient, session: AsyncSession):
    """Thirteen today is thirteen — the boundary belongs to the person on it."""
    user = await create_user(session, email="today@example.com", age_confirmed_at=None)

    response = await client.post(
        "/api/v1/users/me/age-confirmation",
        json={"birthdate": _birthdate_for_age(13)},
        headers=get_auth_headers(user),
    )

    assert response.status_code == 200


async def test_the_day_before_the_birthday_does_not(
    client: AsyncClient, session: AsyncSession
):
    """A birthday that has not come round yet is a year that has not happened."""
    from datetime import datetime, timedelta, timezone

    today = datetime.now(timezone.utc).date()
    # Thirteen tomorrow, so twelve today.
    almost = today.replace(year=today.year - 13) + timedelta(days=1)
    user = await create_user(
        session, email="tomorrow@example.com", age_confirmed_at=None
    )

    response = await client.post(
        "/api/v1/users/me/age-confirmation",
        json={"birthdate": almost.isoformat()},
        headers=get_auth_headers(user),
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "USER_AGE_BELOW_MINIMUM"


async def test_a_date_nobody_was_born_on_is_refused(
    client: AsyncClient, session: AsyncSession
):
    """Separately from being too young, so the reply says which it was."""
    from datetime import datetime, timedelta, timezone

    today = datetime.now(timezone.utc).date()
    user = await create_user(session, email="typo@example.com", age_confirmed_at=None)
    headers = get_auth_headers(user)

    future = await client.post(
        "/api/v1/users/me/age-confirmation",
        json={"birthdate": (today + timedelta(days=1)).isoformat()},
        headers=headers,
    )
    ancient = await client.post(
        "/api/v1/users/me/age-confirmation",
        json={"birthdate": _birthdate_for_age(200)},
        headers=headers,
    )

    assert future.status_code == 422
    assert future.json()["detail"] == "USER_AGE_INVALID_BIRTHDATE"
    assert ancient.status_code == 422
    assert ancient.json()["detail"] == "USER_AGE_INVALID_BIRTHDATE"


async def test_the_date_is_not_kept_anywhere(
    client: AsyncClient, session: AsyncSession
):
    """The promise the surface makes: we asked, we did not write it down.

    Checked against the row rather than against intent — every column of the
    account is searched for the date that was just sent, and the only thing the
    confirmation may leave behind is the timestamp saying it happened.
    """
    user = await create_user(
        session, email="private@example.com", age_confirmed_at=None
    )
    birthdate = _birthdate_for_age(30)

    response = await client.post(
        "/api/v1/users/me/age-confirmation",
        json={"birthdate": birthdate},
        headers=get_auth_headers(user),
    )
    assert response.status_code == 200

    # Nothing in the reply carries it back either.
    assert birthdate not in response.text

    await session.refresh(user)
    assert user.age_confirmed_at is not None
    stored = {
        column: getattr(user, column)
        for column in user.__table__.columns.keys()  # noqa: SIM118
    }
    year, month, day = birthdate.split("-")
    for column, value in stored.items():
        rendered = str(value)
        assert birthdate not in rendered, f"users.{column} holds the date"
        # The date reshaped is still the date.
        assert f"{day}/{month}/{year}" not in rendered, f"users.{column} holds the date"


async def test_answering_under_age_is_recorded_without_the_date(
    client: AsyncClient, session: AsyncSession
):
    """The fact, not the birthday — the promise holds on this path too."""
    user = await create_user(session, email="young@example.com", age_confirmed_at=None)
    birthdate = _birthdate_for_age(9)

    response = await client.post(
        "/api/v1/users/me/age-confirmation",
        json={"birthdate": birthdate},
        headers=get_auth_headers(user),
    )

    assert response.status_code == 422
    await session.refresh(user)
    assert user.age_below_minimum_at is not None
    assert user.age_confirmed_at is None
    for column in user.__table__.columns.keys():  # noqa: SIM118
        assert birthdate not in str(getattr(user, column))


async def test_the_answer_stands_against_a_second_try(
    client: AsyncClient, session: AsyncSession
):
    """A question you can re-answer until it comes out right is not a question."""
    user = await create_user(session, email="retry@example.com", age_confirmed_at=None)
    headers = get_auth_headers(user)

    await client.post(
        "/api/v1/users/me/age-confirmation",
        json={"birthdate": _birthdate_for_age(9)},
        headers=headers,
    )
    second = await client.post(
        "/api/v1/users/me/age-confirmation",
        json={"birthdate": ADULT_BIRTHDATE},
        headers=headers,
    )

    assert second.status_code == 409
    assert second.json()["detail"] == "USER_AGE_ANSWER_STANDS"
    await session.refresh(user)
    assert user.age_confirmed_at is None


async def test_a_blocked_account_still_cannot_join(
    client: AsyncClient, session: AsyncSession
):
    user = await create_user(
        session, email="blocked@example.com", age_confirmed_at=None
    )
    guild = await create_guild(session, name="Open Table")
    await _list_as_community(session, guild)
    headers = get_auth_headers(user)

    await client.post(
        "/api/v1/users/me/age-confirmation",
        json={"birthdate": _birthdate_for_age(9)},
        headers=headers,
    )
    response = await client.post(
        f"/api/v1/guilds/communities/{guild.id}/join", headers=headers
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "GUILD_AGE_CONFIRMATION_REQUIRED"


async def test_support_can_let_them_answer_again(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The way back from a mistyped year, at the lowest rung that has it."""
    from app.models.platform.user import UserRole

    subject = await create_user(
        session, email="typo@example.com", age_confirmed_at=None
    )
    await client.post(
        "/api/v1/users/me/age-confirmation",
        json={"birthdate": _birthdate_for_age(9)},
        headers=get_auth_headers(subject),
    )
    await session.refresh(subject)
    assert subject.age_below_minimum_at is not None

    support = await acting_user(UserRole.support.value)
    cleared = await client.delete(
        f"/api/v1/admin/users/{subject.id}/age-block", headers=support.headers
    )
    assert cleared.status_code == 200

    # And the question is answerable again, from scratch.
    retry = await client.post(
        "/api/v1/users/me/age-confirmation",
        json={"birthdate": ADULT_BIRTHDATE},
        headers=get_auth_headers(subject),
    )
    assert retry.status_code == 200


async def test_an_ordinary_member_cannot_lift_an_age_block(
    client: AsyncClient, session: AsyncSession, acting_user
):
    subject = await create_user(
        session, email="subject@example.com", age_confirmed_at=None
    )
    await client.post(
        "/api/v1/users/me/age-confirmation",
        json={"birthdate": _birthdate_for_age(9)},
        headers=get_auth_headers(subject),
    )

    nobody = await acting_user("member")
    response = await client.delete(
        f"/api/v1/admin/users/{subject.id}/age-block", headers=nobody.headers
    )

    assert response.status_code == 403


async def test_lifting_a_block_that_is_not_there_says_so(
    client: AsyncClient, session: AsyncSession, acting_user
):
    from app.models.platform.user import UserRole

    subject = await create_user(session, email="fine@example.com")
    support = await acting_user(UserRole.support.value)

    response = await client.delete(
        f"/api/v1/admin/users/{subject.id}/age-block", headers=support.headers
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "USER_AGE_NOT_BLOCKED"
