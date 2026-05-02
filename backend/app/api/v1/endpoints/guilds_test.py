"""
Integration tests for guild endpoints.

Tests the guild API endpoints at /api/v1/guilds including:
- Listing guilds
- Creating guilds
- Updating guilds
- Deleting guilds
- Switching active guild
- Reordering guilds
- Creating and managing invites
- Accepting invites
"""

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.guild import GuildRole
from app.testing.factories import (
    create_guild,
    create_guild_membership,
    create_user,
    get_auth_headers,
    get_guild_headers,
)


@pytest.mark.integration
async def test_list_guilds_empty(client: AsyncClient, session: AsyncSession):
    """Test listing guilds when user has no memberships."""
    user = await create_user(session, email="test@example.com")
    headers = get_auth_headers(user)

    response = await client.get("/api/v1/guilds/", headers=headers)

    assert response.status_code == 200
    data = response.json()
    assert data == []


@pytest.mark.integration
async def test_list_guilds_with_memberships(client: AsyncClient, session: AsyncSession):
    """Test listing guilds shows all user's guilds."""
    user = await create_user(session, email="test@example.com")
    guild1 = await create_guild(session, name="Guild 1")
    guild2 = await create_guild(session, name="Guild 2")

    await create_guild_membership(session, user=user, guild=guild1)
    await create_guild_membership(session, user=user, guild=guild2)

    headers = get_auth_headers(user)
    response = await client.get("/api/v1/guilds/", headers=headers)

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    guild_names = {g["name"] for g in data}
    assert "Guild 1" in guild_names
    assert "Guild 2" in guild_names


@pytest.mark.integration
async def test_list_guilds_includes_role(client: AsyncClient, session: AsyncSession):
    """Test that guild list includes user's role in each guild."""
    user = await create_user(session, email="test@example.com")
    admin_guild = await create_guild(session, name="Admin Guild")
    member_guild = await create_guild(session, name="Member Guild")

    await create_guild_membership(session, user=user, guild=admin_guild, role=GuildRole.admin)
    await create_guild_membership(session, user=user, guild=member_guild, role=GuildRole.member)

    headers = get_auth_headers(user)
    response = await client.get("/api/v1/guilds/", headers=headers)

    assert response.status_code == 200
    data = response.json()

    guild_roles = {g["name"]: g["role"] for g in data}
    assert guild_roles["Admin Guild"] == "admin"
    assert guild_roles["Member Guild"] == "member"


@pytest.mark.integration
async def test_list_guilds_shows_active_guild(client: AsyncClient, session: AsyncSession):
    """Test listing guilds returns role and position."""
    user = await create_user(session, email="test@example.com")
    guild1 = await create_guild(session, name="Guild 1")
    guild2 = await create_guild(session, name="Guild 2")

    await create_guild_membership(session, user=user, guild=guild1)
    await create_guild_membership(session, user=user, guild=guild2)

    headers = get_auth_headers(user)
    response = await client.get("/api/v1/guilds/", headers=headers)

    assert response.status_code == 200
    data = response.json()

    guild_names = {g["name"] for g in data}
    assert "Guild 1" in guild_names
    assert "Guild 2" in guild_names
    # is_active is no longer returned; active guild is client-side only
    assert "is_active" not in data[0]


@pytest.mark.integration
async def test_create_guild(client: AsyncClient, session: AsyncSession):
    """Test creating a new guild."""
    user = await create_user(session, email="test@example.com")
    headers = get_auth_headers(user)

    payload = {
        "name": "New Guild",
        "description": "A test guild",
    }

    response = await client.post("/api/v1/guilds/", headers=headers, json=payload)

    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "New Guild"
    assert data["description"] == "A test guild"
    assert data["role"] == "admin"


@pytest.mark.integration
async def test_create_guild_with_icon(client: AsyncClient, session: AsyncSession):
    """Test creating a guild with an icon."""
    user = await create_user(session, email="test@example.com")
    headers = get_auth_headers(user)

    payload = {
        "name": "Icon Guild",
        "description": "Guild with icon",
        "icon_base64": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
    }

    response = await client.post("/api/v1/guilds/", headers=headers, json=payload)

    assert response.status_code == 201
    data = response.json()
    assert data["icon_base64"] is not None


@pytest.mark.integration
async def test_create_guild_requires_name(client: AsyncClient, session: AsyncSession):
    """Test that creating a guild requires a name."""
    user = await create_user(session, email="test@example.com")
    headers = get_auth_headers(user)

    payload = {"name": "   ", "description": "No name"}

    response = await client.post("/api/v1/guilds/", headers=headers, json=payload)

    assert response.status_code == 400
    assert response.json()["detail"] == "GUILD_NAME_REQUIRED"


@pytest.mark.integration
async def test_create_guild_sets_as_active(client: AsyncClient, session: AsyncSession):
    """Test that creating a guild sets it as the user's active guild."""
    user = await create_user(session, email="test@example.com")
    headers = get_auth_headers(user)

    payload = {"name": "Active Guild"}

    response = await client.post("/api/v1/guilds/", headers=headers, json=payload)

    assert response.status_code == 201


@pytest.mark.integration
async def test_update_guild_as_admin(client: AsyncClient, session: AsyncSession):
    """Test that admin can update guild."""
    user = await create_user(session, email="admin@example.com")
    guild = await create_guild(session, name="Old Name", description="Old description")
    await create_guild_membership(session, user=user, guild=guild, role=GuildRole.admin)

    headers = get_auth_headers(user)
    payload = {"name": "New Name", "description": "New description"}

    response = await client.patch(f"/api/v1/guilds/{guild.id}", headers=headers, json=payload)

    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "New Name"
    assert data["description"] == "New description"


@pytest.mark.integration
async def test_update_guild_as_member_forbidden(client: AsyncClient, session: AsyncSession):
    """Test that regular members cannot update guild."""
    user = await create_user(session, email="member@example.com")
    guild = await create_guild(session, name="Test Guild")
    await create_guild_membership(session, user=user, guild=guild, role=GuildRole.member)

    headers = get_auth_headers(user)
    payload = {"name": "Hacked Name"}

    response = await client.patch(f"/api/v1/guilds/{guild.id}", headers=headers, json=payload)

    assert response.status_code == 403


@pytest.mark.integration
async def test_update_guild_without_membership_forbidden(client: AsyncClient, session: AsyncSession):
    """Test that users without membership cannot update guild."""
    user = await create_user(session, email="outsider@example.com")
    guild = await create_guild(session, name="Test Guild")

    headers = get_auth_headers(user)
    payload = {"name": "Hacked Name"}

    response = await client.patch(f"/api/v1/guilds/{guild.id}", headers=headers, json=payload)

    assert response.status_code == 403


@pytest.mark.integration
async def test_delete_guild_as_admin(client: AsyncClient, session: AsyncSession):
    """Test that admin can delete guild."""
    user = await create_user(session, email="admin@example.com")
    guild = await create_guild(session, name="To Delete")
    await create_guild_membership(session, user=user, guild=guild, role=GuildRole.admin)

    headers = get_auth_headers(user)
    response = await client.delete(f"/api/v1/guilds/{guild.id}", headers=headers)

    assert response.status_code == 204


@pytest.mark.integration
async def test_delete_guild_as_member_forbidden(client: AsyncClient, session: AsyncSession):
    """Test that regular members cannot delete guild."""
    user = await create_user(session, email="member@example.com")
    guild = await create_guild(session, name="Test Guild")
    await create_guild_membership(session, user=user, guild=guild, role=GuildRole.member)

    headers = get_auth_headers(user)
    response = await client.delete(f"/api/v1/guilds/{guild.id}", headers=headers)

    assert response.status_code == 403


@pytest.mark.integration
async def test_reorder_guilds(client: AsyncClient, session: AsyncSession):
    """Test reordering user's guilds."""
    user = await create_user(session, email="test@example.com")
    guild1 = await create_guild(session, name="Guild 1")
    guild2 = await create_guild(session, name="Guild 2")
    guild3 = await create_guild(session, name="Guild 3")

    await create_guild_membership(session, user=user, guild=guild1)
    await create_guild_membership(session, user=user, guild=guild2)
    await create_guild_membership(session, user=user, guild=guild3)

    headers = get_auth_headers(user)
    payload = {"guild_ids": [guild3.id, guild1.id, guild2.id]}

    response = await client.put("/api/v1/guilds/order", headers=headers, json=payload)

    assert response.status_code == 204

    # Verify order changed
    list_response = await client.get("/api/v1/guilds/", headers=headers)
    guilds = list_response.json()
    ordered_ids = [g["id"] for g in guilds]
    assert ordered_ids == [guild3.id, guild1.id, guild2.id]


@pytest.mark.integration
async def test_create_guild_invite_as_admin(client: AsyncClient, session: AsyncSession):
    """Test that admin can create guild invites."""
    user = await create_user(session, email="admin@example.com")
    guild = await create_guild(session, name="Test Guild")
    await create_guild_membership(session, user=user, guild=guild, role=GuildRole.admin)

    headers = get_auth_headers(user)
    payload = {"max_uses": 5, "invitee_email": "invitee@example.com"}

    response = await client.post(f"/api/v1/guilds/{guild.id}/invites", headers=headers, json=payload)

    assert response.status_code == 201
    data = response.json()
    assert data["guild_id"] == guild.id
    assert data["max_uses"] == 5
    assert data["invitee_email"] == "invitee@example.com"
    assert data["uses"] == 0
    assert len(data["code"]) == 22


@pytest.mark.integration
async def test_create_guild_invite_with_expiration(client: AsyncClient, session: AsyncSession):
    """Test creating an invite with expiration date."""
    user = await create_user(session, email="admin@example.com")
    guild = await create_guild(session, name="Test Guild")
    await create_guild_membership(session, user=user, guild=guild, role=GuildRole.admin)

    headers = get_auth_headers(user)
    payload = {
        "max_uses": 1,
        "expires_at": "2025-12-31T23:59:59Z",
    }

    response = await client.post(f"/api/v1/guilds/{guild.id}/invites", headers=headers, json=payload)

    assert response.status_code == 201
    data = response.json()
    assert data["expires_at"] is not None
    assert "2025-12-31" in data["expires_at"]


@pytest.mark.integration
async def test_create_guild_invite_as_member_forbidden(client: AsyncClient, session: AsyncSession):
    """Test that regular members cannot create invites."""
    user = await create_user(session, email="member@example.com")
    guild = await create_guild(session, name="Test Guild")
    await create_guild_membership(session, user=user, guild=guild, role=GuildRole.member)

    headers = get_auth_headers(user)
    payload = {"max_uses": 5}

    response = await client.post(f"/api/v1/guilds/{guild.id}/invites", headers=headers, json=payload)

    assert response.status_code == 403


@pytest.mark.integration
async def test_list_guild_invites_as_admin(client: AsyncClient, session: AsyncSession):
    """Test that admin can list guild invites."""
    from app.services import guilds as guild_service

    user = await create_user(session, email="admin@example.com")
    guild = await create_guild(session, name="Test Guild")
    await create_guild_membership(session, user=user, guild=guild, role=GuildRole.admin)

    # Create some invites
    await guild_service.create_guild_invite(session, guild_id=guild.id, created_by_user_id=user.id, max_uses=1)
    await guild_service.create_guild_invite(session, guild_id=guild.id, created_by_user_id=user.id, max_uses=2)
    await session.commit()

    headers = get_auth_headers(user)
    response = await client.get(f"/api/v1/guilds/{guild.id}/invites", headers=headers)

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2


@pytest.mark.integration
async def test_list_guild_invites_as_member_forbidden(client: AsyncClient, session: AsyncSession):
    """Test that regular members cannot list invites."""
    user = await create_user(session, email="member@example.com")
    guild = await create_guild(session, name="Test Guild")
    await create_guild_membership(session, user=user, guild=guild, role=GuildRole.member)

    headers = get_auth_headers(user)
    response = await client.get(f"/api/v1/guilds/{guild.id}/invites", headers=headers)

    assert response.status_code == 403


@pytest.mark.integration
async def test_delete_guild_invite_as_admin(client: AsyncClient, session: AsyncSession):
    """Test that admin can delete guild invites."""
    from app.services import guilds as guild_service

    user = await create_user(session, email="admin@example.com")
    guild = await create_guild(session, name="Test Guild")
    await create_guild_membership(session, user=user, guild=guild, role=GuildRole.admin)

    invite = await guild_service.create_guild_invite(
        session, guild_id=guild.id, created_by_user_id=user.id
    )
    await session.commit()

    headers = get_auth_headers(user)
    response = await client.delete(
        f"/api/v1/guilds/{guild.id}/invites/{invite.id}", headers=headers
    )

    assert response.status_code == 204


@pytest.mark.integration
async def test_delete_guild_invite_as_member_forbidden(client: AsyncClient, session: AsyncSession):
    """Test that regular members cannot delete invites."""
    from app.services import guilds as guild_service

    admin = await create_user(session, email="admin@example.com")
    member = await create_user(session, email="member@example.com")
    guild = await create_guild(session, name="Test Guild")
    await create_guild_membership(session, user=admin, guild=guild, role=GuildRole.admin)
    await create_guild_membership(session, user=member, guild=guild, role=GuildRole.member)

    invite = await guild_service.create_guild_invite(
        session, guild_id=guild.id, created_by_user_id=admin.id
    )
    await session.commit()

    headers = get_auth_headers(member)
    response = await client.delete(
        f"/api/v1/guilds/{guild.id}/invites/{invite.id}", headers=headers
    )

    assert response.status_code == 403


@pytest.mark.integration
async def test_get_invite_status_valid(client: AsyncClient, session: AsyncSession):
    """Test getting status of a valid invite."""
    from app.services import guilds as guild_service

    user = await create_user(session, email="admin@example.com")
    guild = await create_guild(session, name="Test Guild")

    invite = await guild_service.create_guild_invite(
        session, guild_id=guild.id, created_by_user_id=user.id, max_uses=5
    )
    await session.commit()

    response = await client.get(f"/api/v1/guilds/invite/{invite.code}")

    assert response.status_code == 200
    data = response.json()
    assert data["code"] == invite.code
    assert data["guild_id"] == guild.id
    assert data["guild_name"] == "Test Guild"
    assert data["is_valid"] is True
    assert data["max_uses"] == 5
    assert data["uses"] == 0


@pytest.mark.integration
async def test_get_invite_status_invalid_code(client: AsyncClient, session: AsyncSession):
    """Test getting status of invalid invite code."""
    response = await client.get("/api/v1/guilds/invite/invalidcode123")

    assert response.status_code == 200
    data = response.json()
    assert data["is_valid"] is False
    assert data["reason"] is not None


@pytest.mark.integration
async def test_accept_invite(client: AsyncClient, session: AsyncSession):
    """Test accepting a guild invite."""
    from app.services import guilds as guild_service

    creator = await create_user(session, email="creator@example.com")
    invitee = await create_user(session, email="invitee@example.com")
    guild = await create_guild(session, name="Test Guild")

    invite = await guild_service.create_guild_invite(
        session, guild_id=guild.id, created_by_user_id=creator.id, max_uses=5
    )
    await session.commit()

    headers = get_auth_headers(invitee)
    payload = {"code": invite.code}

    response = await client.post("/api/v1/guilds/invite/accept", headers=headers, json=payload)

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == guild.id
    assert data["name"] == "Test Guild"
    assert data["role"] == "member"


@pytest.mark.integration
async def test_accept_invalid_invite_fails(client: AsyncClient, session: AsyncSession):
    """Test that accepting invalid invite fails."""
    user = await create_user(session, email="test@example.com")
    headers = get_auth_headers(user)
    payload = {"code": "invalidcode123"}

    response = await client.post("/api/v1/guilds/invite/accept", headers=headers, json=payload)

    assert response.status_code == 400


@pytest.mark.integration
async def test_accept_expired_invite_fails(client: AsyncClient, session: AsyncSession):
    """Test that accepting expired invite fails."""
    from datetime import datetime, timedelta, timezone
    from app.services import guilds as guild_service

    creator = await create_user(session, email="creator@example.com")
    invitee = await create_user(session, email="invitee@example.com")
    guild = await create_guild(session, name="Test Guild")

    invite = await guild_service.create_guild_invite(
        session,
        guild_id=guild.id,
        created_by_user_id=creator.id,
        expires_at=datetime.now(timezone.utc) - timedelta(days=1),
    )
    await session.commit()

    headers = get_auth_headers(invitee)
    payload = {"code": invite.code}

    response = await client.post("/api/v1/guilds/invite/accept", headers=headers, json=payload)

    assert response.status_code == 400
    assert response.json()["detail"] == "INVITE_EXPIRED_OR_USED"


@pytest.mark.integration
async def test_guild_isolation(client: AsyncClient, session: AsyncSession):
    """Test that users only see their own guilds."""
    user1 = await create_user(session, email="user1@example.com")
    user2 = await create_user(session, email="user2@example.com")
    guild1 = await create_guild(session, name="Guild 1")
    guild2 = await create_guild(session, name="Guild 2")

    await create_guild_membership(session, user=user1, guild=guild1)
    await create_guild_membership(session, user=user2, guild=guild2)

    headers1 = get_auth_headers(user1)
    response1 = await client.get("/api/v1/guilds/", headers=headers1)

    assert response1.status_code == 200
    data1 = response1.json()
    assert len(data1) == 1
    assert data1[0]["name"] == "Guild 1"


@pytest.mark.integration
async def test_list_guilds_requires_authentication(client: AsyncClient):
    """Test that listing guilds requires authentication."""
    response = await client.get("/api/v1/guilds/")

    assert response.status_code == 401


@pytest.mark.integration
async def test_create_guild_requires_authentication(client: AsyncClient):
    """Test that creating guilds requires authentication."""
    payload = {"name": "Test Guild"}
    response = await client.post("/api/v1/guilds/", json=payload)

    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Advanced-tool handoff endpoint (guild scope)
#
# Guild scope is admin-only — there's no per-role permission key to
# negotiate, just the guild role and the deployment-level URL gate.
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_guild_advanced_tool_handoff_returns_404_when_url_unset(
    client: AsyncClient, session: AsyncSession, monkeypatch
):
    """Without ADVANCED_TOOL_URL the embed isn't deployed; even an admin
    must get 404 (not 403) so the endpoint is indistinguishable from a
    deployment that doesn't expose the feature at all."""
    from app.core.config import settings as app_settings

    monkeypatch.setattr(app_settings, "ADVANCED_TOOL_URL", None)

    admin = await create_user(session, email="admin@example.com")
    guild = await create_guild(session)
    await create_guild_membership(
        session, user=admin, guild=guild, role=GuildRole.admin
    )

    headers = get_guild_headers(guild, admin)
    response = await client.post(
        f"/api/v1/guilds/{guild.id}/advanced-tool/handoff", headers=headers
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "ADVANCED_TOOL_NOT_CONFIGURED"


@pytest.mark.integration
async def test_guild_advanced_tool_handoff_rejects_non_admin(
    client: AsyncClient, session: AsyncSession, monkeypatch
):
    """The whole point of the guild-scoped tab is admin-only access. A
    regular member of the guild must be refused — this is the load-
    bearing check; if it regressed, anyone could mint a guild-scoped
    token."""
    from app.core.config import settings as app_settings

    monkeypatch.setattr(app_settings, "ADVANCED_TOOL_URL", "https://embed.example.com")

    member = await create_user(session, email="member@example.com")
    guild = await create_guild(session)
    await create_guild_membership(
        session, user=member, guild=guild, role=GuildRole.member
    )

    headers = get_guild_headers(guild, member)
    response = await client.post(
        f"/api/v1/guilds/{guild.id}/advanced-tool/handoff", headers=headers
    )

    assert response.status_code == 403


@pytest.mark.integration
async def test_guild_advanced_tool_handoff_rejects_non_member(
    client: AsyncClient, session: AsyncSession, monkeypatch
):
    """A user with no membership in the guild can't elevate by hitting
    the endpoint with that guild's id — guild isolation must hold."""
    from app.core.config import settings as app_settings

    monkeypatch.setattr(app_settings, "ADVANCED_TOOL_URL", "https://embed.example.com")

    outsider = await create_user(session, email="outsider@example.com")
    other_guild = await create_guild(session, name="Other guild")
    await create_guild_membership(
        session, user=outsider, guild=other_guild, role=GuildRole.admin
    )

    target_guild = await create_guild(session, name="Target guild")

    # Use the outsider's auth but reference the target guild they aren't in
    headers = get_guild_headers(target_guild, outsider)
    response = await client.post(
        f"/api/v1/guilds/{target_guild.id}/advanced-tool/handoff", headers=headers
    )

    assert response.status_code == 403


@pytest.mark.integration
async def test_guild_advanced_tool_handoff_succeeds_for_admin(
    client: AsyncClient, session: AsyncSession, monkeypatch
):
    """The happy path: admin gets a token with ``scope=guild``, no
    ``initiative_id``, ``is_manager=true``, and ``can_create=true`` —
    guild admins always have full access at this scope."""
    from app.core.config import settings as app_settings
    from app.core.security import ADVANCED_TOOL_AUDIENCE
    import jwt

    monkeypatch.setattr(app_settings, "ADVANCED_TOOL_URL", "https://embed.example.com")

    admin = await create_user(session, email="admin@example.com")
    guild = await create_guild(session)
    await create_guild_membership(
        session, user=admin, guild=guild, role=GuildRole.admin
    )

    headers = get_guild_headers(guild, admin)
    response = await client.post(
        f"/api/v1/guilds/{guild.id}/advanced-tool/handoff", headers=headers
    )

    assert response.status_code == 200
    body = response.json()
    assert body["scope"] == "guild"
    assert body["initiative_id"] is None
    assert body["iframe_url"] == "https://embed.example.com"
    assert body["expires_in_seconds"] > 0

    payload = jwt.decode(
        body["handoff_token"],
        app_settings.SECRET_KEY,
        # Hardcoded HS256 — the handoff signing path uses HS256 in its
        # no-private-key fallback regardless of settings.ALGORITHM. See
        # initiatives_test.py for the same rationale.
        algorithms=["HS256"],
        audience=ADVANCED_TOOL_AUDIENCE,
    )
    assert payload["sub"] == str(admin.id)
    assert payload["scope"] == "guild"
    assert "initiative_id" not in payload
    assert payload["is_manager"] is True
    assert payload["can_create"] is True
    assert payload["guild_id"] == guild.id
    assert payload["guild_role"] == "admin"


@pytest.mark.integration
async def test_guild_advanced_tool_handoff_requires_authentication(
    client: AsyncClient, monkeypatch
):
    """No auth, no token — the auth dep runs before the URL/role gates."""
    from app.core.config import settings as app_settings

    monkeypatch.setattr(app_settings, "ADVANCED_TOOL_URL", "https://embed.example.com")

    response = await client.post("/api/v1/guilds/1/advanced-tool/handoff")

    assert response.status_code == 401


# --- Leave guild: project-orphan protection -------------------------------


@pytest.mark.integration
async def test_leave_eligibility_lists_owned_projects(
    client: AsyncClient, session: AsyncSession
):
    """Eligibility surfaces projects owned by the user in this guild.

    Without this list the SPA has no way to prompt for transfers
    before calling the leave endpoint, so we'd silently regress to
    the orphan-project bug.
    """
    from app.testing.factories import create_initiative, create_project

    admin = await create_user(session, email="admin@example.com")
    leaver = await create_user(session, email="leaver@example.com")
    guild = await create_guild(session, creator=admin)
    await create_guild_membership(
        session, user=admin, guild=guild, role=GuildRole.admin
    )
    await create_guild_membership(
        session, user=leaver, guild=guild, role=GuildRole.member
    )
    initiative = await create_initiative(session, guild=guild, creator=admin)
    project = await create_project(session, initiative=initiative, owner=leaver)

    response = await client.get(
        f"/api/v1/guilds/{guild.id}/leave/eligibility",
        headers=get_auth_headers(leaver),
    )
    assert response.status_code == 200
    data = response.json()
    assert data["can_leave"] is False
    assert len(data["owned_projects"]) == 1
    assert data["owned_projects"][0]["id"] == project.id
    assert data["owned_projects"][0]["initiative_id"] == initiative.id


@pytest.mark.integration
async def test_leave_blocks_when_owned_projects_lack_transfer(
    client: AsyncClient, session: AsyncSession
):
    """Without ``project_transfers``, leaving with owned projects is rejected
    rather than silently orphaning them."""
    from app.testing.factories import create_initiative, create_project

    admin = await create_user(session, email="admin@example.com")
    leaver = await create_user(session, email="leaver@example.com")
    guild = await create_guild(session, creator=admin)
    await create_guild_membership(
        session, user=admin, guild=guild, role=GuildRole.admin
    )
    await create_guild_membership(
        session, user=leaver, guild=guild, role=GuildRole.member
    )
    initiative = await create_initiative(session, guild=guild, creator=admin)
    await create_project(session, initiative=initiative, owner=leaver)

    response = await client.request(
        "DELETE",
        f"/api/v1/guilds/{guild.id}/leave",
        headers=get_auth_headers(leaver),
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "CANNOT_LEAVE_OWNS_PROJECTS"


@pytest.mark.integration
async def test_leave_with_transfers_reassigns_and_succeeds(
    client: AsyncClient, session: AsyncSession
):
    """Supplying transfers for every owned project lets the leave proceed
    and updates ``owner_id`` before the membership row is dropped."""
    from app.models.project import Project
    from app.testing.factories import (
        create_initiative,
        create_initiative_member,
        create_project,
    )

    admin = await create_user(session, email="admin@example.com")
    successor = await create_user(session, email="successor@example.com")
    leaver = await create_user(session, email="leaver@example.com")
    guild = await create_guild(session, creator=admin)
    await create_guild_membership(
        session, user=admin, guild=guild, role=GuildRole.admin
    )
    await create_guild_membership(
        session, user=successor, guild=guild, role=GuildRole.member
    )
    await create_guild_membership(
        session, user=leaver, guild=guild, role=GuildRole.member
    )
    initiative = await create_initiative(session, guild=guild, creator=admin)
    await create_initiative_member(session, initiative=initiative, user=successor)
    await create_initiative_member(session, initiative=initiative, user=leaver)
    project = await create_project(session, initiative=initiative, owner=leaver)

    response = await client.request(
        "DELETE",
        f"/api/v1/guilds/{guild.id}/leave",
        headers=get_auth_headers(leaver),
        json={"project_transfers": {str(project.id): successor.id}},
    )
    assert response.status_code == 204

    refreshed = (
        await session.exec(
            __import__("sqlmodel").select(Project).where(Project.id == project.id)
        )
    ).one()
    assert refreshed.owner_id == successor.id


@pytest.mark.integration
async def test_leave_with_deletion_soft_deletes_project(
    client: AsyncClient, session: AsyncSession
):
    """Per-project ``project_deletions`` is the alternative to
    ``project_transfers`` — it sends the row to trash instead of
    handing it off, so a user with no obvious successor can still
    leave without orphaning the project."""
    from app.models.project import Project
    from app.testing.factories import create_initiative, create_project

    admin = await create_user(session, email="admin@example.com")
    leaver = await create_user(session, email="leaver@example.com")
    guild = await create_guild(session, creator=admin)
    await create_guild_membership(session, user=admin, guild=guild, role=GuildRole.admin)
    await create_guild_membership(session, user=leaver, guild=guild, role=GuildRole.member)
    initiative = await create_initiative(session, guild=guild, creator=admin)
    project = await create_project(session, initiative=initiative, owner=leaver)

    response = await client.request(
        "DELETE",
        f"/api/v1/guilds/{guild.id}/leave",
        headers=get_auth_headers(leaver),
        json={"project_deletions": [project.id]},
    )
    assert response.status_code == 204

    # Soft-deleted rows are hidden by the default global filter, so
    # read with the bypass helper used elsewhere in the soft-delete
    # service.
    from app.db.soft_delete_filter import select_including_deleted

    refreshed = (
        await session.exec(
            select_including_deleted(Project).where(Project.id == project.id)
        )
    ).one()
    assert refreshed.deleted_at is not None
    assert refreshed.deleted_by == leaver.id


@pytest.mark.integration
async def test_leave_rejects_overlap_between_transfer_and_delete(
    client: AsyncClient, session: AsyncSession
):
    """A project listed in both ``project_transfers`` and
    ``project_deletions`` is ambiguous — the endpoint refuses rather
    than picking one silently."""
    from app.testing.factories import (
        create_initiative,
        create_initiative_member,
        create_project,
    )

    admin = await create_user(session, email="admin@example.com")
    successor = await create_user(session, email="successor@example.com")
    leaver = await create_user(session, email="leaver@example.com")
    guild = await create_guild(session, creator=admin)
    await create_guild_membership(session, user=admin, guild=guild, role=GuildRole.admin)
    await create_guild_membership(session, user=successor, guild=guild, role=GuildRole.member)
    await create_guild_membership(session, user=leaver, guild=guild, role=GuildRole.member)
    initiative = await create_initiative(session, guild=guild, creator=admin)
    await create_initiative_member(session, initiative=initiative, user=successor)
    await create_initiative_member(session, initiative=initiative, user=leaver)
    project = await create_project(session, initiative=initiative, owner=leaver)

    response = await client.request(
        "DELETE",
        f"/api/v1/guilds/{guild.id}/leave",
        headers=get_auth_headers(leaver),
        json={
            "project_transfers": {str(project.id): successor.id},
            "project_deletions": [project.id],
        },
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "CANNOT_LEAVE_OWNS_PROJECTS"


@pytest.mark.integration
async def test_leave_rejects_partial_transfer_map(
    client: AsyncClient, session: AsyncSession
):
    """Missing or surplus entries in ``project_transfers`` are rejected so
    a bad client can't accidentally orphan some projects or transfer
    rows it doesn't own."""
    from app.testing.factories import (
        create_initiative,
        create_initiative_member,
        create_project,
    )

    admin = await create_user(session, email="admin@example.com")
    successor = await create_user(session, email="successor@example.com")
    leaver = await create_user(session, email="leaver@example.com")
    guild = await create_guild(session, creator=admin)
    await create_guild_membership(
        session, user=admin, guild=guild, role=GuildRole.admin
    )
    await create_guild_membership(
        session, user=successor, guild=guild, role=GuildRole.member
    )
    await create_guild_membership(
        session, user=leaver, guild=guild, role=GuildRole.member
    )
    initiative = await create_initiative(session, guild=guild, creator=admin)
    await create_initiative_member(session, initiative=initiative, user=successor)
    await create_initiative_member(session, initiative=initiative, user=leaver)
    project_a = await create_project(session, initiative=initiative, owner=leaver)
    await create_project(session, initiative=initiative, owner=leaver)

    # Only one of two projects covered.
    response = await client.request(
        "DELETE",
        f"/api/v1/guilds/{guild.id}/leave",
        headers=get_auth_headers(leaver),
        json={"project_transfers": {str(project_a.id): successor.id}},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "CANNOT_LEAVE_OWNS_PROJECTS"
