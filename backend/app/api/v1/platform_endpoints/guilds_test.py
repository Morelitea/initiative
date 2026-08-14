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

from sqlmodel import select

from app.testing.schema_harness import route_session_to_guild
from app.models.platform.guild import Guild, GuildMembership, GuildRole
from app.models.platform.user import UserRole, UserStatus
from app.models.tenant.initiative import InitiativeMember
from app.services.platform import guilds as guilds_service
from app.testing.factories import (
    create_federated_identity,
    create_guild,
    create_guild_membership,
    create_user,
    get_auth_headers,
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

    await create_guild_membership(
        session, user=user, guild=admin_guild, role=GuildRole.admin
    )
    await create_guild_membership(
        session, user=user, guild=member_guild, role=GuildRole.member
    )

    headers = get_auth_headers(user)
    response = await client.get("/api/v1/guilds/", headers=headers)

    assert response.status_code == 200
    data = response.json()

    guild_roles = {g["name"]: g["role"] for g in data}
    assert guild_roles["Admin Guild"] == "admin"
    assert guild_roles["Member Guild"] == "member"


#: The administration half of ``GuildRead`` — caps, plan label, retention
#: window, lifecycle status, sign-in entitlement. Each backs an admin-only
#: surface, so a plain member's entry carries ``None`` for all of them.
ADMIN_ONLY_GUILD_FIELDS = (
    "retention_days",
    "max_storage_bytes",
    "max_users",
    "tier_name",
    "status",
    "guild_auth_enabled",
)


@pytest.mark.integration
async def test_list_guilds_administration_fields_are_admin_only(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The guild list serves two audiences from one schema: every member gets
    the guild's identity, their own membership and the roster size; only guild
    admins get the administration fields."""
    admin = await acting_user(guild_role=GuildRole.admin)
    member = await acting_user(guild_role=GuildRole.member, guild=admin.guild)

    guild = await session.get(Guild, admin.guild.id)
    assert guild is not None
    administration = await guilds_service.get_administration(session, guild_id=guild.id)
    administration.max_storage_bytes = 5_000_000
    administration.max_users = 25
    administration.tier_name = "Bespoke Plan"
    administration.guild_auth_enabled = True
    session.add(administration)
    await session.commit()

    async def entry(headers: dict[str, str]) -> dict:
        resp = await client.get("/api/v1/guilds/", headers=headers)
        assert resp.status_code == 200, resp.text
        return next(g for g in resp.json() if g["id"] == admin.guild.id)

    member_row = await entry(member.headers)
    for field in ADMIN_ONLY_GUILD_FIELDS:
        assert member_row[field] is None, f"{field} must not reach a plain member"
    # What a member does get: the guild itself, their membership, the roster
    # size, and whether content is frozen.
    assert member_row["name"] == guild.name
    assert member_row["role"] == "member"
    assert member_row["member_count"] == 2
    assert member_row["content_read_only"] is False

    admin_row = await entry(admin.headers)
    for field in ADMIN_ONLY_GUILD_FIELDS:
        assert admin_row[field] is not None, f"{field} must reach the guild admin"
    assert admin_row["max_storage_bytes"] == 5_000_000
    assert admin_row["max_users"] == 25
    assert admin_row["tier_name"] == "Bespoke Plan"
    assert admin_row["retention_days"] == 90
    assert admin_row["guild_auth_enabled"] is True


@pytest.mark.integration
async def test_accepted_invite_withholds_administration_fields(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Joining by invite answers with the same member-tier payload — the new
    member is not an admin, so the administration fields come back ``None``."""
    admin = await acting_user(guild_role=GuildRole.admin)
    guild = await session.get(Guild, admin.guild.id)
    assert guild is not None
    administration = await guilds_service.get_administration(session, guild_id=guild.id)
    administration.max_users = 25
    administration.tier_name = "Bespoke Plan"
    session.add(administration)
    await session.commit()

    invite = await client.post(
        f"/api/v1/guilds/{guild.id}/invites",
        headers=admin.headers,
        json={},
    )
    assert invite.status_code == 201, invite.text

    joiner = await create_user(session, email="joiner@example.com")
    resp = await client.post(
        "/api/v1/guilds/invite/accept",
        headers=get_auth_headers(joiner),
        json={"code": invite.json()["code"]},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["role"] == "member"
    for field in ADMIN_ONLY_GUILD_FIELDS:
        assert body[field] is None, f"{field} must not reach a plain member"


@pytest.mark.integration
async def test_list_guilds_shows_active_guild(
    client: AsyncClient, session: AsyncSession
):
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


# --- creating a guild for another account ----------------------------------


@pytest.mark.integration
async def test_staff_can_create_a_guild_owned_by_someone_else(
    client: AsyncClient, session: AsyncSession
):
    staff = await create_user(session, email="staff@example.com", role=UserRole.owner)
    customer = await create_user(session, email="customer@example.com")

    response = await client.post(
        "/api/v1/guilds/",
        headers=get_auth_headers(staff),
        json={"name": "Acme", "owner_user_id": customer.id},
    )

    assert response.status_code == 201, response.text
    guild_id = response.json()["id"]

    # The named account is its admin...
    memberships = (
        await session.exec(
            select(GuildMembership).where(GuildMembership.guild_id == guild_id)
        )
    ).all()
    assert [(m.user_id, m.role) for m in memberships] == [
        (customer.id, GuildRole.admin)
    ]
    # ...and the creator holds nothing in it.
    assert staff.id not in {m.user_id for m in memberships}


@pytest.mark.integration
async def test_creating_for_someone_else_records_both_identities(
    client: AsyncClient, session: AsyncSession
):
    """Who did it and who it was for, in the row rather than only a log line."""
    staff = await create_user(session, email="staff@example.com", role=UserRole.owner)
    customer = await create_user(session, email="customer@example.com")

    response = await client.post(
        "/api/v1/guilds/",
        headers=get_auth_headers(staff),
        json={"name": "Acme", "owner_user_id": customer.id},
    )

    guild = await session.get(Guild, response.json()["id"])
    assert guild.created_by_user_id == staff.id
    membership = (
        await session.exec(
            select(GuildMembership).where(GuildMembership.guild_id == guild.id)
        )
    ).one()
    assert membership.user_id == customer.id


@pytest.mark.integration
async def test_the_owner_gets_the_default_initiative_not_the_staff_creator(
    client: AsyncClient, session: AsyncSession
):
    """A guild made for another account must not leave its creator inside the
    content either — the default initiative belongs to the owner."""
    staff = await create_user(session, email="staff@example.com", role=UserRole.owner)
    customer = await create_user(session, email="customer@example.com")

    response = await client.post(
        "/api/v1/guilds/",
        headers=get_auth_headers(staff),
        json={"name": "Acme", "owner_user_id": customer.id},
    )
    guild_id = response.json()["id"]

    await route_session_to_guild(session, guild_id)
    members = (await session.exec(select(InitiativeMember))).all()
    assert {m.user_id for m in members} == {customer.id}


@pytest.mark.integration
async def test_an_ordinary_user_cannot_name_another_owner(
    client: AsyncClient, session: AsyncSession
):
    """Refused, not silently ignored: creating the guild under the caller would
    answer 201 for a request that named someone else."""
    user = await create_user(session, email="member@example.com")
    other = await create_user(session, email="other@example.com")

    response = await client.post(
        "/api/v1/guilds/",
        headers=get_auth_headers(user),
        json={"name": "Not yours", "owner_user_id": other.id},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "GUILD_OWNER_REQUIRES_CAPABILITY"
    assert (
        await session.exec(select(Guild).where(Guild.name == "Not yours"))
    ).all() == []


@pytest.mark.integration
async def test_naming_yourself_needs_no_capability(
    client: AsyncClient, session: AsyncSession
):
    """The field is about handing a guild to someone else; spelling out your
    own id is the ordinary path."""
    user = await create_user(session, email="member@example.com")

    response = await client.post(
        "/api/v1/guilds/",
        headers=get_auth_headers(user),
        json={"name": "Mine", "owner_user_id": user.id},
    )

    assert response.status_code == 201, response.text
    assert response.json()["role"] == "admin"


@pytest.mark.integration
@pytest.mark.parametrize(
    "owner_id_of",
    ["missing", "deactivated"],
    ids=["unknown user", "deactivated user"],
)
async def test_an_unusable_owner_is_refused(
    client: AsyncClient, session: AsyncSession, owner_id_of: str
):
    """This never creates an account, and never hands a guild to one that
    cannot sign in to run it."""
    staff = await create_user(session, email="staff@example.com", role=UserRole.owner)
    if owner_id_of == "missing":
        owner_id = 999_999_999
    else:
        deactivated = await create_user(
            session, email="gone@example.com", status=UserStatus.deactivated
        )
        owner_id = deactivated.id

    response = await client.post(
        "/api/v1/guilds/",
        headers=get_auth_headers(staff),
        json={"name": "Acme", "owner_user_id": owner_id},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "GUILD_OWNER_NOT_FOUND"


@pytest.mark.integration
async def test_update_guild_as_admin(client: AsyncClient, session: AsyncSession):
    """Test that admin can update guild."""
    user = await create_user(session, email="admin@example.com")
    guild = await create_guild(session, name="Old Name", description="Old description")
    await create_guild_membership(session, user=user, guild=guild, role=GuildRole.admin)

    headers = get_auth_headers(user)
    payload = {"name": "New Name", "description": "New description"}

    response = await client.patch(
        f"/api/v1/guilds/{guild.id}", headers=headers, json=payload
    )

    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "New Name"
    assert data["description"] == "New description"


@pytest.mark.integration
async def test_update_guild_as_member_forbidden(
    client: AsyncClient, session: AsyncSession
):
    """Test that regular members cannot update guild."""
    user = await create_user(session, email="member@example.com")
    guild = await create_guild(session, name="Test Guild")
    await create_guild_membership(
        session, user=user, guild=guild, role=GuildRole.member
    )

    headers = get_auth_headers(user)
    payload = {"name": "Hacked Name"}

    response = await client.patch(
        f"/api/v1/guilds/{guild.id}", headers=headers, json=payload
    )

    assert response.status_code == 403


@pytest.mark.integration
async def test_update_guild_without_membership_forbidden(
    client: AsyncClient, session: AsyncSession
):
    """Test that users without membership cannot update guild."""
    user = await create_user(session, email="outsider@example.com")
    guild = await create_guild(session, name="Test Guild")

    headers = get_auth_headers(user)
    payload = {"name": "Hacked Name"}

    response = await client.patch(
        f"/api/v1/guilds/{guild.id}", headers=headers, json=payload
    )

    assert response.status_code == 403


@pytest.mark.integration
async def test_delete_guild_as_admin(client: AsyncClient, session: AsyncSession):
    """Test that admin can delete guild with the right password and phrase."""
    user = await create_user(session, email="admin@example.com")
    guild = await create_guild(session, name="To Delete")
    await create_guild_membership(session, user=user, guild=guild, role=GuildRole.admin)

    headers = get_auth_headers(user)
    body = {
        "password": "testpassword123",
        "confirmation_text": "DELETE GUILD TO DELETE",
    }
    response = await client.request(
        "DELETE", f"/api/v1/guilds/{guild.id}", headers=headers, json=body
    )

    assert response.status_code == 204


@pytest.mark.integration
async def test_delete_guild_as_member_forbidden(
    client: AsyncClient, session: AsyncSession
):
    """Test that regular members cannot delete guild."""
    user = await create_user(session, email="member@example.com")
    guild = await create_guild(session, name="Test Guild")
    await create_guild_membership(
        session, user=user, guild=guild, role=GuildRole.member
    )

    headers = get_auth_headers(user)
    body = {
        "password": "testpassword123",
        "confirmation_text": "DELETE GUILD TEST GUILD",
    }
    response = await client.request(
        "DELETE", f"/api/v1/guilds/{guild.id}", headers=headers, json=body
    )

    assert response.status_code == 403


@pytest.mark.integration
async def test_delete_guild_wrong_password(client: AsyncClient, session: AsyncSession):
    """A wrong password is rejected with 400 (not 401, to avoid logout)."""
    user = await create_user(session, email="admin@example.com")
    guild = await create_guild(session, name="To Delete")
    await create_guild_membership(session, user=user, guild=guild, role=GuildRole.admin)

    headers = get_auth_headers(user)
    body = {"password": "wrongpassword", "confirmation_text": "DELETE GUILD TO DELETE"}
    response = await client.request(
        "DELETE", f"/api/v1/guilds/{guild.id}", headers=headers, json=body
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "GUILD_INVALID_PASSWORD"


@pytest.mark.integration
async def test_delete_guild_wrong_confirmation(
    client: AsyncClient, session: AsyncSession
):
    """A mismatched confirmation phrase is rejected with 400."""
    user = await create_user(session, email="admin@example.com")
    guild = await create_guild(session, name="To Delete")
    await create_guild_membership(session, user=user, guild=guild, role=GuildRole.admin)

    headers = get_auth_headers(user)
    body = {"password": "testpassword123", "confirmation_text": "To Delete"}
    response = await client.request(
        "DELETE", f"/api/v1/guilds/{guild.id}", headers=headers, json=body
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "GUILD_CONFIRMATION_MISMATCH"


@pytest.mark.integration
async def test_delete_guild_oidc_user_skips_password(
    client: AsyncClient, session: AsyncSession
):
    """SSO-only users delete with just the phrase — no password required."""
    user = await create_user(session, email="sso@example.com")
    await create_federated_identity(session, user, subject="sso-123")
    guild = await create_guild(session, name="To Delete")
    await create_guild_membership(session, user=user, guild=guild, role=GuildRole.admin)

    headers = get_auth_headers(user)
    body = {"confirmation_text": "DELETE GUILD TO DELETE"}
    response = await client.request(
        "DELETE", f"/api/v1/guilds/{guild.id}", headers=headers, json=body
    )

    assert response.status_code == 204


@pytest.mark.integration
@pytest.mark.parametrize(
    "role", ["member", "support", "moderator", "operator", "owner"]
)
async def test_reorder_guilds(client: AsyncClient, session: AsyncSession, role: str):
    """EVERY platform tier can reorder their own guilds in personal mode.

    The request runs as ``platform_<role>`` with no guild context. The
    ``guild_memberships_update`` RLS policy (``guild_id = current_guild_id``)
    rejects that for every tier, so the SECURITY DEFINER ``reorder_guild_memberships``
    function (migration 0107) is the uniform self-service path — no role relies on
    a standing all-guild bypass. Parametrized across the whole ladder so a member
    (lowest) and an owner (highest) are both proven to work the same way.
    """
    user = await create_user(session, email="test@example.com", role=UserRole(role))
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

    response = await client.post(
        f"/api/v1/guilds/{guild.id}/invites", headers=headers, json=payload
    )

    assert response.status_code == 201
    data = response.json()
    assert data["guild_id"] == guild.id
    assert data["max_uses"] == 5
    assert data["invitee_email"] == "invitee@example.com"
    assert data["uses"] == 0
    assert len(data["code"]) == 22


@pytest.mark.integration
async def test_create_guild_invite_with_expiration(
    client: AsyncClient, session: AsyncSession
):
    """Test creating an invite with expiration date."""
    user = await create_user(session, email="admin@example.com")
    guild = await create_guild(session, name="Test Guild")
    await create_guild_membership(session, user=user, guild=guild, role=GuildRole.admin)

    headers = get_auth_headers(user)
    payload = {
        "max_uses": 1,
        "expires_at": "2025-12-31T23:59:59Z",
    }

    response = await client.post(
        f"/api/v1/guilds/{guild.id}/invites", headers=headers, json=payload
    )

    assert response.status_code == 201
    data = response.json()
    assert data["expires_at"] is not None
    assert "2025-12-31" in data["expires_at"]


@pytest.mark.integration
async def test_create_guild_invite_as_member_forbidden(
    client: AsyncClient, session: AsyncSession
):
    """Test that regular members cannot create invites."""
    user = await create_user(session, email="member@example.com")
    guild = await create_guild(session, name="Test Guild")
    await create_guild_membership(
        session, user=user, guild=guild, role=GuildRole.member
    )

    headers = get_auth_headers(user)
    payload = {"max_uses": 5}

    response = await client.post(
        f"/api/v1/guilds/{guild.id}/invites", headers=headers, json=payload
    )

    assert response.status_code == 403


@pytest.mark.integration
async def test_list_guild_invites_as_admin(client: AsyncClient, session: AsyncSession):
    """Test that admin can list guild invites."""
    from app.services.platform import guilds as guild_service

    user = await create_user(session, email="admin@example.com")
    guild = await create_guild(session, name="Test Guild")
    await create_guild_membership(session, user=user, guild=guild, role=GuildRole.admin)

    # Create some invites
    await guild_service.create_guild_invite(
        session, guild_id=guild.id, created_by_user_id=user.id, max_uses=1
    )
    await guild_service.create_guild_invite(
        session, guild_id=guild.id, created_by_user_id=user.id, max_uses=2
    )
    await session.commit()

    headers = get_auth_headers(user)
    response = await client.get(f"/api/v1/guilds/{guild.id}/invites", headers=headers)

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2


@pytest.mark.integration
async def test_list_guild_invites_as_member_forbidden(
    client: AsyncClient, session: AsyncSession
):
    """Test that regular members cannot list invites."""
    user = await create_user(session, email="member@example.com")
    guild = await create_guild(session, name="Test Guild")
    await create_guild_membership(
        session, user=user, guild=guild, role=GuildRole.member
    )

    headers = get_auth_headers(user)
    response = await client.get(f"/api/v1/guilds/{guild.id}/invites", headers=headers)

    assert response.status_code == 403


@pytest.mark.integration
async def test_delete_guild_invite_as_admin(client: AsyncClient, session: AsyncSession):
    """Test that admin can delete guild invites."""
    from app.services.platform import guilds as guild_service

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
async def test_delete_guild_invite_as_member_forbidden(
    client: AsyncClient, session: AsyncSession
):
    """Test that regular members cannot delete invites."""
    from app.services.platform import guilds as guild_service

    admin = await create_user(session, email="admin@example.com")
    member = await create_user(session, email="member@example.com")
    guild = await create_guild(session, name="Test Guild")
    await create_guild_membership(
        session, user=admin, guild=guild, role=GuildRole.admin
    )
    await create_guild_membership(
        session, user=member, guild=guild, role=GuildRole.member
    )

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
    from app.services.platform import guilds as guild_service

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
async def test_get_invite_status_invalid_code(
    client: AsyncClient, session: AsyncSession
):
    """Test getting status of invalid invite code."""
    response = await client.get("/api/v1/guilds/invite/invalidcode123")

    assert response.status_code == 200
    data = response.json()
    assert data["is_valid"] is False
    assert data["reason"] is not None


@pytest.mark.integration
async def test_accept_invite(client: AsyncClient, session: AsyncSession):
    """Test accepting a guild invite."""
    from app.services.platform import guilds as guild_service

    creator = await create_user(session, email="creator@example.com")
    invitee = await create_user(session, email="invitee@example.com")
    guild = await create_guild(session, name="Test Guild")

    invite = await guild_service.create_guild_invite(
        session, guild_id=guild.id, created_by_user_id=creator.id, max_uses=5
    )
    await session.commit()

    headers = get_auth_headers(invitee)
    payload = {"code": invite.code}

    response = await client.post(
        "/api/v1/guilds/invite/accept", headers=headers, json=payload
    )

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == guild.id
    assert data["name"] == "Test Guild"
    assert data["role"] == "member"


@pytest.mark.integration
async def test_accept_invite_blocked_when_guild_full(
    client: AsyncClient, session: AsyncSession
):
    """Accepting an invite into a guild at its user cap returns 403."""
    from app.services.platform import guilds as guild_service

    creator = await create_user(session, email="full-creator@example.com")
    seat_holder = await create_user(session, email="full-seat@example.com")
    invitee = await create_user(session, email="full-invitee@example.com")
    guild = await create_guild(session, name="Full Guild", max_users=1)

    await guild_service.ensure_membership(
        session, guild_id=guild.id, user_id=seat_holder.id, role=GuildRole.member
    )
    invite = await guild_service.create_guild_invite(
        session, guild_id=guild.id, created_by_user_id=creator.id, max_uses=5
    )
    await session.commit()

    response = await client.post(
        "/api/v1/guilds/invite/accept",
        headers=get_auth_headers(invitee),
        json={"code": invite.code},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "GUILD_USER_LIMIT_REACHED"


@pytest.mark.integration
async def test_accept_invalid_invite_fails(client: AsyncClient, session: AsyncSession):
    """Test that accepting invalid invite fails."""
    user = await create_user(session, email="test@example.com")
    headers = get_auth_headers(user)
    payload = {"code": "invalidcode123"}

    response = await client.post(
        "/api/v1/guilds/invite/accept", headers=headers, json=payload
    )

    assert response.status_code == 400


@pytest.mark.integration
async def test_accept_expired_invite_fails(client: AsyncClient, session: AsyncSession):
    """Test that accepting expired invite fails."""
    from datetime import datetime, timedelta, timezone
    from app.services.platform import guilds as guild_service

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

    response = await client.post(
        "/api/v1/guilds/invite/accept", headers=headers, json=payload
    )

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


# --- Billing-portal handoff endpoint --------------------------------------


@pytest.mark.integration
async def test_guild_billing_handoff_returns_404_when_billing_url_unset(
    client: AsyncClient, session: AsyncSession, monkeypatch
):
    """No BILLING_URL configured -> 404."""
    from app.core.config import settings as app_settings

    monkeypatch.setattr(app_settings, "BILLING_URL", None)

    admin = await create_user(session, email="admin@example.com")
    guild = await create_guild(session)
    await create_guild_membership(
        session, user=admin, guild=guild, role=GuildRole.admin
    )

    response = await client.post(
        f"/api/v1/guilds/{guild.id}/billing/handoff", headers=get_auth_headers(admin)
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "BILLING_PORTAL_NOT_CONFIGURED"


@pytest.mark.integration
async def test_guild_billing_handoff_rejects_non_admin(
    client: AsyncClient, session: AsyncSession, monkeypatch
):
    """A plain member is refused (admin only)."""
    from app.core.config import settings as app_settings

    monkeypatch.setattr(app_settings, "BILLING_URL", "https://billing.example.com")

    member = await create_user(session, email="member@example.com")
    guild = await create_guild(session)
    await create_guild_membership(
        session, user=member, guild=guild, role=GuildRole.member
    )

    response = await client.post(
        f"/api/v1/guilds/{guild.id}/billing/handoff", headers=get_auth_headers(member)
    )
    assert response.status_code == 403


@pytest.mark.integration
async def test_guild_billing_handoff_rejects_non_member(
    client: AsyncClient, session: AsyncSession, monkeypatch
):
    """A user can't mint a billing token for a guild they don't belong to."""
    from app.core.config import settings as app_settings

    monkeypatch.setattr(app_settings, "BILLING_URL", "https://billing.example.com")

    outsider = await create_user(session, email="outsider@example.com")
    other_guild = await create_guild(session, name="Other guild")
    await create_guild_membership(
        session, user=outsider, guild=other_guild, role=GuildRole.admin
    )
    target_guild = await create_guild(session, name="Target guild")

    response = await client.post(
        f"/api/v1/guilds/{target_guild.id}/billing/handoff",
        headers=get_auth_headers(outsider),
    )
    assert response.status_code == 403


@pytest.mark.integration
async def test_guild_billing_handoff_succeeds_for_admin(
    client: AsyncClient, session: AsyncSession, monkeypatch
):
    """Admin gets an RS256 token with the billing-portal audience and role."""
    from app.core.config import settings as app_settings
    from app.core.security import BILLING_PORTAL_AUDIENCE
    import jwt

    monkeypatch.setattr(app_settings, "BILLING_URL", "https://billing.example.com")

    admin = await create_user(session, email="admin@example.com")
    guild = await create_guild(session)
    await create_guild_membership(
        session, user=admin, guild=guild, role=GuildRole.admin
    )

    response = await client.post(
        f"/api/v1/guilds/{guild.id}/billing/handoff", headers=get_auth_headers(admin)
    )
    assert response.status_code == 200
    body = response.json()
    assert body["expires_in_seconds"] > 0

    assert jwt.get_unverified_header(body["handoff_token"])["alg"] == "RS256"
    payload = jwt.decode(body["handoff_token"], options={"verify_signature": False})
    assert payload["aud"] == BILLING_PORTAL_AUDIENCE
    assert payload["iss"] == "initiative"
    assert payload["sub"] == str(admin.id)
    assert payload["guild_id"] == guild.id
    assert payload["guild_role"] == "admin"


@pytest.mark.integration
async def test_guild_billing_handoff_requires_authentication(
    client: AsyncClient, monkeypatch
):
    """Unauthenticated -> 401."""
    from app.core.config import settings as app_settings

    monkeypatch.setattr(app_settings, "BILLING_URL", "https://billing.example.com")

    response = await client.post("/api/v1/guilds/1/billing/handoff")
    assert response.status_code == 401


@pytest.mark.integration
async def test_guild_billing_handoff_503_when_signing_key_unset(
    client: AsyncClient, session: AsyncSession, monkeypatch
):
    """BILLING_URL set but no signing key -> 503."""
    from app.core.config import settings as app_settings

    monkeypatch.setattr(app_settings, "BILLING_URL", "https://billing.example.com")
    monkeypatch.setattr(app_settings, "HANDOFF_SIGNING_PRIVATE_KEY_PEM", None)

    admin = await create_user(session, email="admin@example.com")
    guild = await create_guild(session)
    await create_guild_membership(
        session, user=admin, guild=guild, role=GuildRole.admin
    )

    response = await client.post(
        f"/api/v1/guilds/{guild.id}/billing/handoff", headers=get_auth_headers(admin)
    )
    assert response.status_code == 503
    assert response.json()["detail"] == "BILLING_PORTAL_SIGNING_NOT_CONFIGURED"


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
    from app.testing.factories import (
        create_initiative,
        create_initiative_member,
        create_project,
    )

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
    await create_initiative_member(session, initiative=initiative, user=leaver)
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
    from app.testing.factories import (
        create_initiative,
        create_initiative_member,
        create_project,
    )

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
    await create_initiative_member(session, initiative=initiative, user=leaver)
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
    from app.models.tenant.project import Project
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
async def test_leave_eligibility_filters_candidates_to_pms(
    client: AsyncClient, session: AsyncSession
):
    """The transfer-recipient picker should only show initiative
    managers — they're the role that actually administers projects.
    Non-manager members shouldn't appear even though they're active
    members of the same initiative."""
    from app.testing.factories import (
        create_initiative,
        create_initiative_member,
        create_project,
    )

    admin = await create_user(session, email="admin@example.com")
    pm = await create_user(session, email="pm@example.com")
    member = await create_user(session, email="member@example.com")
    leaver = await create_user(session, email="leaver@example.com")
    guild = await create_guild(session, creator=admin)
    await create_guild_membership(
        session, user=admin, guild=guild, role=GuildRole.admin
    )
    await create_guild_membership(session, user=pm, guild=guild, role=GuildRole.member)
    await create_guild_membership(
        session, user=member, guild=guild, role=GuildRole.member
    )
    await create_guild_membership(
        session, user=leaver, guild=guild, role=GuildRole.member
    )
    initiative = await create_initiative(session, guild=guild, creator=admin)
    await create_initiative_member(
        session, initiative=initiative, user=pm, role_name="project_manager"
    )
    await create_initiative_member(
        session, initiative=initiative, user=member, role_name="member"
    )
    await create_initiative_member(session, initiative=initiative, user=leaver)
    await create_project(session, initiative=initiative, owner=leaver)

    response = await client.get(
        f"/api/v1/guilds/{guild.id}/leave/eligibility",
        headers=get_auth_headers(leaver),
    )
    assert response.status_code == 200
    data = response.json()
    project = data["owned_projects"][0]
    candidate_ids = {c["id"] for c in project["candidates"]}
    # Initiative creator (admin) is auto-promoted to PM by the
    # initiative factory; pm explicitly added. Both should appear.
    assert admin.id in candidate_ids
    assert pm.id in candidate_ids
    # The non-manager member must NOT appear, and neither should the
    # leaving user themselves.
    assert member.id not in candidate_ids
    assert leaver.id not in candidate_ids


@pytest.mark.integration
async def test_leave_with_deletion_soft_deletes_project(
    client: AsyncClient, session: AsyncSession
):
    """Per-project ``project_deletions`` is the alternative to
    ``project_transfers`` — it sends the row to trash instead of
    handing it off, so a user with no obvious successor can still
    leave without orphaning the project."""
    from app.models.tenant.project import Project
    from app.testing.factories import (
        create_initiative,
        create_initiative_member,
        create_project,
    )

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
    await create_initiative_member(session, initiative=initiative, user=leaver)
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
