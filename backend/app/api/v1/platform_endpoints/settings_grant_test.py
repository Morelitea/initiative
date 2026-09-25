"""A grant for a community's settings, and nothing inside it."""

from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.guild import GuildRole
from app.models.platform.user import UserRole
from app.models.tenant.ai_member_key import GuildAIMemberKey
from app.models.tenant.ai_member_pref import GuildAIMemberPref
from app.services.platform import access_grants as access_grants_service
from app.testing.factories import (
    create_auth_provider,
    create_guild,
    create_guild_auth_policy,
    create_guild_membership,
    create_initiative,
    create_user,
    get_auth_headers,
)
from app.testing.schema_harness import route_session_to_guild


async def _request_and_approve(client, *, requester, approver, guild, rung):
    asked = await client.post(
        "/api/v1/access-grants/",
        headers=get_auth_headers(requester),
        json={
            "guild_id": guild.id,
            "settings_level": rung,
            "reason": "billing question from the community",
        },
    )
    assert asked.status_code == 201, asked.text
    assert asked.json()["purpose"] == "settings"
    assert asked.json()["access_level"] == rung

    decided = await client.post(
        f"/api/v1/access-grants/{asked.json()['id']}/approve",
        headers=get_auth_headers(approver),
        json={},
    )
    assert decided.status_code == 200, decided.text
    return decided.json()


async def _request_pair_and_approve(
    client, session, *, requester, approver, guild, access, rung
):
    """One request asking for both axes, and both grants approved.

    A request names the content rung and, beside it, the settings rung. Each
    axis becomes its own row, so each is approved and audited on its own.
    """
    from app.models.platform.access_grant import AccessGrant

    asked = await client.post(
        "/api/v1/access-grants/",
        headers=get_auth_headers(requester),
        json={
            "guild_id": guild.id,
            "access_level": access,
            "settings_level": rung,
            "reason": "the community cannot sign in",
        },
    )
    assert asked.status_code == 201, asked.text

    pending = (
        await session.exec(
            select(AccessGrant).where(
                AccessGrant.user_id == requester.id,
                AccessGrant.guild_id == guild.id,
            )
        )
    ).all()
    assert {grant.purpose for grant in pending} == {"content", "settings"}
    for grant in pending:
        decided = await client.post(
            f"/api/v1/access-grants/{grant.id}/approve",
            headers=get_auth_headers(approver),
            json={},
        )
        assert decided.status_code == 200, decided.text


async def test_a_settings_grant_reaches_settings_and_no_content(
    client: AsyncClient, session: AsyncSession
):
    """The whole point of splitting the axes: somebody sent to help with
    billing or moderation settings reaches the configuration and reads
    nobody's work."""
    owner = await create_user(session, role=UserRole.owner)
    support = await create_user(session, role=UserRole.support)
    guild = await create_guild(session, creator=owner)
    await create_initiative(session, guild, owner, name="Private Wing")

    await _request_and_approve(
        client, requester=support, approver=owner, guild=guild, rung="superadmin"
    )
    headers = get_auth_headers(support)

    # The community's own configuration: reachable.
    policy = await client.get(
        f"/api/v1/communities/{guild.id}/auth-policy", headers=headers
    )
    assert policy.status_code == 200, policy.text

    # Its content: not. A settings grant carries no content level at all, so
    # the guild's initiatives are not this grantee's to read.
    content = await client.get(f"/api/v1/c/{guild.id}/initiatives/", headers=headers)
    assert content.status_code in (403, 404), content.text


async def test_a_settings_only_superadmin_grant_reaches_ai_configuration(
    client: AsyncClient, session: AsyncSession
):
    owner = await create_user(session, role=UserRole.owner)
    support = await create_user(session, role=UserRole.support)
    guild = await create_guild(session, creator=owner)

    await _request_and_approve(
        client, requester=support, approver=owner, guild=guild, rung="superadmin"
    )

    response = await client.get(
        f"/api/v1/c/{guild.id}/settings/ai/connections",
        headers=get_auth_headers(support),
    )

    assert response.status_code == 200, response.text


async def test_settings_grantee_deletion_purges_every_members_reference(
    client: AsyncClient, session: AsyncSession
):
    owner = await create_user(session, role=UserRole.owner)
    member = await create_user(session)
    support = await create_user(session, role=UserRole.support)
    guild = await create_guild(session, creator=owner)
    await create_guild_membership(
        session, user=owner, guild=guild, role=GuildRole.superadmin
    )
    await create_guild_membership(
        session, user=member, guild=guild, role=GuildRole.member
    )
    mode = await client.put(
        "/api/v1/settings/ai/platform/mode",
        headers=get_auth_headers(owner),
        json={"mode": "guild"},
    )
    assert mode.status_code == 200, mode.text

    created = await client.post(
        f"/api/v1/c/{guild.id}/settings/ai/connections",
        headers=get_auth_headers(owner),
        json={"label": "Team", "provider": "openai"},
    )
    assert created.status_code == 200, created.text
    connection_id = created.json()["id"]

    member_headers = get_auth_headers(member)
    key = await client.put(
        f"/api/v1/c/{guild.id}/settings/ai/me/key",
        headers=member_headers,
        json={
            "scope": "guild",
            "connection_id": connection_id,
            "api_key": "sk-member",
        },
    )
    assert key.status_code == 200, key.text
    pref = await client.put(
        f"/api/v1/c/{guild.id}/settings/ai/me/pref",
        headers=member_headers,
        json={
            "scope": "guild",
            "connection_id": connection_id,
            "enabled": True,
        },
    )
    assert pref.status_code == 200, pref.text

    await _request_pair_and_approve(
        client,
        session,
        requester=support,
        approver=owner,
        guild=guild,
        access="read_write",
        rung="superadmin",
    )
    deleted = await client.delete(
        f"/api/v1/c/{guild.id}/settings/ai/connections/{connection_id}",
        headers=get_auth_headers(support),
    )
    assert deleted.status_code == 204, deleted.text

    await route_session_to_guild(session, guild.id)
    keys = (
        await session.exec(
            select(GuildAIMemberKey).where(
                GuildAIMemberKey.connection_id == connection_id
            )
        )
    ).all()
    prefs = (
        await session.exec(
            select(GuildAIMemberPref).where(
                GuildAIMemberPref.connection_id == connection_id
            )
        )
    ).all()
    assert keys == []
    assert prefs == []


async def test_the_superadmin_grantee_reads_the_auth_controls(
    client: AsyncClient, session: AsyncSession
):
    """The temporary seat gets the current values before changing them."""
    owner = await create_user(session, role=UserRole.owner)
    support = await create_user(session, role=UserRole.support)
    guild = await create_guild(
        session,
        creator=owner,
        allow_api_keys=False,
        enforce_compliance_session=True,
    )
    await _request_and_approve(
        client, requester=support, approver=owner, guild=guild, rung="superadmin"
    )

    response = await client.get(
        f"/api/v1/communities/{guild.id}/auth-settings",
        headers=get_auth_headers(support),
    )

    assert response.status_code == 200, response.text
    assert response.json() == {
        "auth_options": ["providers", "restrictions"],
        "allow_api_keys": False,
        "enforce_compliance_session": True,
        "require_second_factor": False,
        "allow_email_notifications": True,
        "allow_push_notifications": True,
        "redact_notification_content": False,
    }


async def test_the_admin_rung_does_not_reach_the_seat(
    client: AsyncClient, session: AsyncSession
):
    """Two rungs, and the lower one stops short of what the seat holds."""
    owner = await create_user(session, role=UserRole.owner)
    support = await create_user(session, role=UserRole.support)
    guild = await create_guild(session, creator=owner)

    await _request_and_approve(
        client, requester=support, approver=owner, guild=guild, rung="admin"
    )
    headers = get_auth_headers(support)

    refused = await client.put(
        f"/api/v1/communities/{guild.id}/api-access",
        headers=headers,
        json={"allow_api_keys": False},
    )
    assert refused.status_code == 403, refused.text

    read = await client.get(
        f"/api/v1/communities/{guild.id}/auth-settings", headers=headers
    )
    assert read.status_code == 403, read.text


async def test_a_bare_request_is_a_content_read(
    client: AsyncClient, session: AsyncSession
):
    """Naming neither axis means what it always meant."""
    support = await create_user(session, role=UserRole.support)
    guild = await create_guild(session)

    response = await client.post(
        "/api/v1/access-grants/",
        headers=get_auth_headers(support),
        json={"guild_id": guild.id, "reason": "having a look"},
    )
    assert response.status_code == 201, response.text
    assert response.json()["purpose"] == "content"
    assert response.json()["access_level"] == "read"


async def test_a_lesser_grant_does_not_stand_in_the_way_of_breaking_glass(
    client: AsyncClient, session: AsyncSession
):
    """The moment glass is broken is the moment a standing grant is most likely
    to be open. It is superseded, not an obstacle."""
    owner = await create_user(session, role=UserRole.owner)
    operator = await create_user(session, role=UserRole.operator)
    guild = await create_guild(session, creator=owner)

    lesser = await _request_and_approve(
        client, requester=operator, approver=owner, guild=guild, rung="admin"
    )

    broken = await client.post(
        "/api/v1/access-grants/break-glass",
        headers=get_auth_headers(operator),
        json={"guild_id": guild.id, "reason": "incident, and I already had one"},
    )
    assert broken.status_code == 201, broken.text

    listed = await client.get(
        "/api/v1/access-grants/?mine=true", headers=get_auth_headers(operator)
    )
    grants = {g["id"]: g for g in listed.json()}
    # The pair is live...
    live = {(g["purpose"], g["access_level"]) for g in grants.values() if g["is_live"]}
    assert live == {("content", "read_write"), ("settings", "superadmin")}
    # ...and the one it replaced is revoked rather than gone, so the log keeps
    # both.
    assert grants[lesser["id"]]["status"] == "revoked"


async def test_one_request_can_ask_for_both(client: AsyncClient, session: AsyncSession):
    """Clearing up after an incident takes write access to the content *and*
    the settings that govern it. One ask, two grants — so an approver decides
    about each and the log keeps them apart."""
    support = await create_user(session, role=UserRole.support)
    guild = await create_guild(session)
    headers = get_auth_headers(support)

    response = await client.post(
        "/api/v1/access-grants/",
        headers=headers,
        json={
            "guild_id": guild.id,
            "access_level": "read_write",
            "settings_level": "admin",
            "reason": "clearing up after the incident",
        },
    )
    assert response.status_code == 201, response.text
    # The content one comes back, being what a caller routes in under.
    assert response.json()["purpose"] == "content"

    listed = await client.get("/api/v1/access-grants/?mine=true", headers=headers)
    asked = {(g["purpose"], g["access_level"]) for g in listed.json()}
    assert asked == {("content", "read_write"), ("settings", "admin")}


def test_every_level_has_its_own_label():
    """A level with no label of its own reads as somebody else's.

    The two vocabularies share one column, so a lookup that fell through to a
    default would announce a ``superadmin`` settings grant as "read-only" to
    the person being asked to approve it. Checked against the catalogues
    themselves, in every locale, rather than against the map that produced
    them.
    """
    from app.core.email_i18n import translate
    from app.models.platform.access_grant import (
        LEVEL_LABEL_KEYS,
        LEVELS_BY_PURPOSE,
    )

    every_level = {level for levels in LEVELS_BY_PURPOSE.values() for level in levels}
    assert every_level <= set(LEVEL_LABEL_KEYS), (
        f"no label for {sorted(every_level - set(LEVEL_LABEL_KEYS))}"
    )

    for locale in ("en", "de", "es", "fr"):
        rendered = {
            level: translate(key, locale, namespace="notifications")
            for level, key in LEVEL_LABEL_KEYS.items()
        }
        # Distinct, so no two levels are announced the same way, and none of
        # them came back as the key itself.
        assert len(set(rendered.values())) == len(rendered), f"{locale}: {rendered}"
        for level, text in rendered.items():
            assert not text.startswith("accessGrant."), f"{locale}/{level} unresolved"


async def test_a_combined_conflict_sends_no_external_notification(
    client: AsyncClient, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
):
    owner = await create_user(session, role=UserRole.owner)
    support = await create_user(session, role=UserRole.support)
    guild = await create_guild(session, creator=owner)
    headers = get_auth_headers(support)

    existing = await client.post(
        "/api/v1/access-grants/",
        headers=headers,
        json={
            "guild_id": guild.id,
            "settings_level": "admin",
            "reason": "already pending",
        },
    )
    assert existing.status_code == 201, existing.text

    send = AsyncMock()
    monkeypatch.setattr(access_grants_service, "_push_and_email", send)
    response = await client.post(
        "/api/v1/access-grants/",
        headers=headers,
        json={
            "guild_id": guild.id,
            "access_level": "read",
            "settings_level": "superadmin",
            "reason": "combined request",
        },
    )

    assert response.status_code == 409, response.text
    send.assert_not_awaited()


# --- What each rung actually reaches -----------------------------------------


async def test_the_admin_rung_runs_the_community_without_entering_it(
    client: AsyncClient, session: AsyncSession
):
    """``admin`` is "what a guild admin administers" — the community's own
    settings and its roster, and none of the work inside it. On its own the
    rung reads; changing what it reaches takes a read_write grant beside it."""
    owner = await create_user(session, role=UserRole.owner)
    support = await create_user(session, role=UserRole.support)
    guild = await create_guild(session, creator=owner)
    await create_initiative(session, guild, owner, name="Private Wing")

    await _request_and_approve(
        client, requester=support, approver=owner, guild=guild, rung="admin"
    )
    headers = get_auth_headers(support)

    entry = await client.get(f"/api/v1/communities/{guild.id}", headers=headers)
    assert entry.status_code == 200, entry.text
    assert entry.json()["role"] == "admin"
    assert entry.json()["can_write_settings"] is False

    renamed = await client.patch(
        f"/api/v1/communities/{guild.id}",
        headers=headers,
        json={"name": "Renamed By Support"},
    )
    assert renamed.status_code == 403, renamed.text
    assert renamed.json()["detail"] == "ACCESS_GRANT_WRITE_REQUIRED"

    roster = await client.get(f"/api/v1/c/{guild.id}/users/", headers=headers)
    assert roster.status_code == 200, roster.text
    assert {row["id"] for row in roster.json()} == {owner.id}

    content = await client.get(f"/api/v1/c/{guild.id}/initiatives/", headers=headers)
    assert content.status_code in (403, 404), content.text


async def test_the_admin_rung_writes_beside_a_read_write_grant(
    client: AsyncClient, session: AsyncSession
):
    """The two asks together: the rung names the surface, the read_write grant
    lets it be changed — and, being a content grant, opens the work too."""
    owner = await create_user(session, role=UserRole.owner)
    support = await create_user(session, role=UserRole.support)
    guild = await create_guild(session, creator=owner)
    await create_initiative(session, guild, owner, name="Private Wing")

    await _request_pair_and_approve(
        client,
        session,
        requester=support,
        approver=owner,
        guild=guild,
        access="read_write",
        rung="admin",
    )
    headers = get_auth_headers(support)

    renamed = await client.patch(
        f"/api/v1/communities/{guild.id}",
        headers=headers,
        json={"name": "Renamed By Support"},
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["name"] == "Renamed By Support"
    assert renamed.json()["can_write_settings"] is True

    entry = await client.get(f"/api/v1/communities/{guild.id}", headers=headers)
    assert entry.json()["can_write_settings"] is True

    content = await client.get(f"/api/v1/c/{guild.id}/initiatives/", headers=headers)
    assert content.status_code == 200, content.text


async def test_the_lent_seat_lifts_the_communitys_sign_in_requirement(
    client: AsyncClient, session: AsyncSession
):
    """The write the seat's own floor carries, made by somebody holding the
    seat for a window rather than by membership — with the read_write grant
    beside the rung that lets a lent seat change what it reads."""
    from app.testing.factories import create_auth_provider, create_guild_auth_policy

    owner = await create_user(session, role=UserRole.owner)
    support = await create_user(session, role=UserRole.support)
    guild = await create_guild(session, creator=owner)
    provider = await create_auth_provider(session, slug="corp")
    await create_guild_auth_policy(session, guild, provider)

    await _request_pair_and_approve(
        client,
        session,
        requester=support,
        approver=owner,
        guild=guild,
        access="read_write",
        rung="superadmin",
    )

    cleared = await client.put(
        f"/api/v1/communities/{guild.id}/auth-policy",
        headers=get_auth_headers(support),
        json={"policy": "open"},
    )

    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["policy"] == "open"

    # Read back through the surface rather than the setup session, which is
    # holding its own view of the row this just removed.
    after = await client.get(
        f"/api/v1/communities/{guild.id}/auth-policy", headers=get_auth_headers(support)
    )
    assert after.status_code == 200, after.text
    assert after.json()["policy"] == "open"


async def test_a_lent_seat_reads_the_sign_in_rule_and_does_not_change_it(
    client: AsyncClient, session: AsyncSession
):
    """The seat's rung on its own is a view of what the seat holds."""
    owner = await create_user(session, role=UserRole.owner)
    support = await create_user(session, role=UserRole.support)
    guild = await create_guild(session, creator=owner)
    provider = await create_auth_provider(session, slug="corp")
    await create_guild_auth_policy(session, guild, provider)

    await _request_and_approve(
        client, requester=support, approver=owner, guild=guild, rung="superadmin"
    )
    headers = get_auth_headers(support)

    read = await client.get(
        f"/api/v1/communities/{guild.id}/auth-policy", headers=headers
    )
    assert read.status_code == 200, read.text
    assert read.json()["policy"] != "open"

    refused = await client.put(
        f"/api/v1/communities/{guild.id}/auth-policy",
        headers=headers,
        json={"policy": "open"},
    )
    assert refused.status_code == 403, refused.text
    assert refused.json()["detail"] == "ACCESS_GRANT_WRITE_REQUIRED"


async def test_the_admin_rung_does_not_reach_the_seats_own_surface(
    client: AsyncClient, session: AsyncSession
):
    """The two rungs are a ladder: the lower one runs the community and does
    not decide who may enter it."""
    owner = await create_user(session, role=UserRole.owner)
    support = await create_user(session, role=UserRole.support)
    guild = await create_guild(session, creator=owner)

    await _request_and_approve(
        client, requester=support, approver=owner, guild=guild, rung="admin"
    )

    response = await client.get(
        f"/api/v1/communities/{guild.id}/auth-settings",
        headers=get_auth_headers(support),
    )

    assert response.status_code == 403, response.text


async def test_the_pair_one_request_asks_for_reaches_both_axes(
    client: AsyncClient, session: AsyncSession
):
    """The ordinary shape of a PAM request: a content rung and, beside it, a
    settings rung. Somebody sent to fix a sign-in that is keeping a community
    out holds both — the configuration to change the rule, and the content
    access they asked for to see what it was doing."""
    from app.testing.factories import create_auth_provider, create_guild_auth_policy

    owner = await create_user(session, role=UserRole.owner)
    support = await create_user(session, role=UserRole.support)
    guild = await create_guild(session, creator=owner)
    await create_initiative(session, guild, owner, name="Private Wing")
    provider = await create_auth_provider(session, slug="corp")
    await create_guild_auth_policy(session, guild, provider)

    await _request_pair_and_approve(
        client,
        session,
        requester=support,
        approver=owner,
        guild=guild,
        access="read_write",
        rung="superadmin",
    )
    headers = get_auth_headers(support)

    # The settings axis: the rule this session cannot itself satisfy is still
    # theirs to lift, which is the errand.
    cleared = await client.put(
        f"/api/v1/communities/{guild.id}/auth-policy",
        headers=headers,
        json={"policy": "open"},
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["policy"] == "open"

    # And the content axis, which the same request asked for separately.
    content = await client.get(f"/api/v1/c/{guild.id}/initiatives/", headers=headers)
    assert content.status_code == 200, content.text
    assert [row["name"] for row in content.json()] == ["Private Wing"]

    # The seat's own surfaces come with the rung, lent as well as held: taking
    # the community out in one file is one of the things that seat does.
    export = await client.get(
        f"/api/v1/c/{guild.id}/exports/community/status", headers=headers
    )
    assert export.status_code == 200, export.text


async def test_a_members_guild_list_says_whether_they_change_its_settings(
    client: AsyncClient, session: AsyncSession
):
    """The membership row answers for a member: its administrator changes the
    settings, an ordinary member has none to change."""
    admin = await create_user(session)
    member = await create_user(session)
    guild = await create_guild(session, creator=admin)
    await create_guild_membership(session, user=member, guild=guild)

    for user, expected in ((admin, True), (member, False)):
        listed = await client.get(
            "/api/v1/communities/", headers=get_auth_headers(user)
        )
        assert listed.status_code == 200, listed.text
        (entry,) = [row for row in listed.json() if row["id"] == guild.id]
        assert entry["can_write_settings"] is expected


async def test_a_member_does_not_read_the_settings_entry(
    client: AsyncClient, session: AsyncSession
):
    """The entry is served on the settings surface, so it asks for its rung."""
    admin = await create_user(session)
    member = await create_user(session)
    guild = await create_guild(session, creator=admin)
    await create_guild_membership(session, user=member, guild=guild)

    refused = await client.get(
        f"/api/v1/communities/{guild.id}", headers=get_auth_headers(member)
    )
    assert refused.status_code == 403, refused.text
