"""
Integration tests for user endpoints.

Tests the user API endpoints at /api/v1/users including:
- Getting current user info
- Listing users in a guild
- Updating user profile
- User deletion
"""

import pytest
from httpx import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.encryption import encrypt_field, hash_email, SALT_EMAIL
from app.models.guild import GuildRole

from app.testing.factories import (
    create_guild,
    create_guild_membership,
    create_user,
    get_auth_headers,
    get_guild_headers,
)


@pytest.mark.integration
async def test_get_current_user(client: AsyncClient, session: AsyncSession):
    """Test getting current user's profile."""
    user = await create_user(
        session,
        email="test@example.com",
        full_name="Test User",
    )
    headers = get_auth_headers(user)

    response = await client.get("/api/v1/users/me", headers=headers)

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == user.id
    assert data["email"] == "test@example.com"
    assert data["full_name"] == "Test User"
    assert data["status"] == "active"


@pytest.mark.integration
async def test_get_current_user_requires_auth(client: AsyncClient):
    """Test that getting current user requires authentication."""
    response = await client.get("/api/v1/users/me")

    assert response.status_code == 401


@pytest.mark.integration
async def test_update_current_user_profile(client: AsyncClient, session: AsyncSession):
    """Test updating current user's profile."""
    user = await create_user(session, email="test@example.com", full_name="Old Name")
    headers = get_auth_headers(user)

    update_data = {
        "full_name": "New Name",
        "timezone": "America/New_York",
    }

    response = await client.patch("/api/v1/users/me", headers=headers, json=update_data)

    assert response.status_code == 200
    data = response.json()
    assert data["full_name"] == "New Name"
    assert data["timezone"] == "America/New_York"


@pytest.mark.integration
async def test_update_current_user_notification_preferences(
    client: AsyncClient, session: AsyncSession
):
    """Test updating notification preferences."""
    user = await create_user(session)
    headers = get_auth_headers(user)

    update_data = {
        "email_task_assignment": False,
        "email_overdue_tasks": False,
    }

    response = await client.patch("/api/v1/users/me", headers=headers, json=update_data)

    assert response.status_code == 200
    data = response.json()
    assert data["email_task_assignment"] is False
    assert data["email_overdue_tasks"] is False


@pytest.mark.integration
async def test_list_users_in_guild(client: AsyncClient, session: AsyncSession):
    """Test listing users in a guild."""
    guild = await create_guild(session)
    user1 = await create_user(session, email="user1@example.com", full_name="User One")
    user2 = await create_user(session, email="user2@example.com", full_name="User Two")

    await create_guild_membership(session, user=user1, guild=guild)
    await create_guild_membership(session, user=user2, guild=guild)

    headers = get_guild_headers(guild, user1)

    response = await client.get("/api/v1/users/", headers=headers)

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    emails = {user["email"] for user in data}
    assert "user1@example.com" in emails
    assert "user2@example.com" in emails


@pytest.mark.integration
async def test_list_users_requires_guild_context(client: AsyncClient, session: AsyncSession):
    """Test that listing users requires guild context."""
    user = await create_user(session)
    headers = get_auth_headers(user)

    response = await client.get("/api/v1/users/", headers=headers)

    # Should fail without guild membership
    assert response.status_code == 403


@pytest.mark.integration
async def test_update_user_by_id_as_admin(client: AsyncClient, session: AsyncSession):
    """Test that guild admin can update other users."""
    guild = await create_guild(session)
    admin = await create_user(session, email="admin@example.com")
    member = await create_user(session, email="member@example.com", full_name="Old Name")

    await create_guild_membership(session, user=admin, guild=guild, role=GuildRole.admin)
    await create_guild_membership(session, user=member, guild=guild, role=GuildRole.member)

    headers = get_guild_headers(guild, admin)

    update_data = {"full_name": "New Name"}

    response = await client.patch(
        f"/api/v1/users/{member.id}",
        headers=headers,
        json=update_data,
    )

    assert response.status_code == 200
    data = response.json()
    assert data["full_name"] == "New Name"


@pytest.mark.integration
async def test_update_user_as_member_forbidden(client: AsyncClient, session: AsyncSession):
    """Test that regular members cannot update other users."""
    guild = await create_guild(session)
    member1 = await create_user(session, email="member1@example.com")
    member2 = await create_user(session, email="member2@example.com")

    await create_guild_membership(session, user=member1, guild=guild, role=GuildRole.member)
    await create_guild_membership(session, user=member2, guild=guild, role=GuildRole.member)

    headers = get_guild_headers(guild, member1)

    update_data = {"full_name": "Hacked Name"}

    response = await client.patch(
        f"/api/v1/users/{member2.id}",
        headers=headers,
        json=update_data,
    )

    assert response.status_code == 403


@pytest.mark.integration
async def test_check_deletion_eligibility(client: AsyncClient, session: AsyncSession):
    """Test checking if user can delete their account."""
    guild = await create_guild(session)
    admin = await create_user(session, email="admin@example.com")
    member = await create_user(session, email="member@example.com")

    await create_guild_membership(session, user=admin, guild=guild, role=GuildRole.admin)
    await create_guild_membership(session, user=member, guild=guild, role=GuildRole.member)

    headers = get_auth_headers(member)

    response = await client.get("/api/v1/users/me/deletion-eligibility", headers=headers)

    assert response.status_code == 200
    data = response.json()
    assert "can_delete" in data
    assert "blockers" in data
    assert "warnings" in data


@pytest.mark.integration
async def test_delete_user_as_admin(client: AsyncClient, session: AsyncSession):
    """Test that guild admin can delete users."""
    guild = await create_guild(session)
    admin = await create_user(session, email="admin@example.com")
    member = await create_user(session, email="member@example.com")

    await create_guild_membership(session, user=admin, guild=guild, role=GuildRole.admin)
    await create_guild_membership(session, user=member, guild=guild, role=GuildRole.member)

    headers = get_guild_headers(guild, admin)

    response = await client.delete(f"/api/v1/users/{member.id}", headers=headers)

    assert response.status_code == 204


@pytest.mark.integration
async def test_delete_user_as_member_forbidden(client: AsyncClient, session: AsyncSession):
    """Test that regular members cannot delete users."""
    guild = await create_guild(session)
    member1 = await create_user(session, email="member1@example.com")
    member2 = await create_user(session, email="member2@example.com")

    await create_guild_membership(session, user=member1, guild=guild, role=GuildRole.member)
    await create_guild_membership(session, user=member2, guild=guild, role=GuildRole.member)

    headers = get_guild_headers(guild, member1)

    response = await client.delete(f"/api/v1/users/{member2.id}", headers=headers)

    assert response.status_code == 403


@pytest.mark.integration
async def test_guild_removal_eligibility_lists_owned_projects(
    client: AsyncClient, session: AsyncSession
):
    """The pre-flight endpoint surfaces every project the target user
    owns in the active guild so the SPA can prompt the admin for
    transfer recipients before issuing DELETE."""
    from app.testing.factories import create_initiative, create_project

    guild = await create_guild(session)
    admin = await create_user(session, email="admin@example.com")
    member = await create_user(session, email="member@example.com")
    await create_guild_membership(session, user=admin, guild=guild, role=GuildRole.admin)
    await create_guild_membership(session, user=member, guild=guild, role=GuildRole.member)
    initiative = await create_initiative(session, guild=guild, creator=admin)
    project = await create_project(session, initiative=initiative, owner=member)

    response = await client.get(
        f"/api/v1/users/{member.id}/guild-removal-eligibility",
        headers=get_guild_headers(guild, admin),
    )
    assert response.status_code == 200
    data = response.json()
    assert data["can_remove"] is False
    assert len(data["owned_projects"]) == 1
    assert data["owned_projects"][0]["id"] == project.id


@pytest.mark.integration
async def test_delete_user_blocks_when_owned_projects_lack_transfer(
    client: AsyncClient, session: AsyncSession
):
    """Removing a member who owns projects without supplying transfers
    is rejected so the admin doesn't silently orphan the rows."""
    from app.testing.factories import create_initiative, create_project

    guild = await create_guild(session)
    admin = await create_user(session, email="admin@example.com")
    member = await create_user(session, email="member@example.com")
    await create_guild_membership(session, user=admin, guild=guild, role=GuildRole.admin)
    await create_guild_membership(session, user=member, guild=guild, role=GuildRole.member)
    initiative = await create_initiative(session, guild=guild, creator=admin)
    await create_project(session, initiative=initiative, owner=member)

    response = await client.delete(
        f"/api/v1/users/{member.id}",
        headers=get_guild_headers(guild, admin),
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "CANNOT_REMOVE_OWNS_PROJECTS"


@pytest.mark.integration
async def test_delete_user_with_transfers_reassigns_and_succeeds(
    client: AsyncClient, session: AsyncSession
):
    """Supplying transfers for every owned project lets the admin
    proceed; ``owner_id`` is reassigned before the membership row is
    dropped so the project survives the removal."""
    from app.models.project import Project
    from app.testing.factories import (
        create_initiative,
        create_initiative_member,
        create_project,
    )

    guild = await create_guild(session)
    admin = await create_user(session, email="admin@example.com")
    successor = await create_user(session, email="successor@example.com")
    member = await create_user(session, email="member@example.com")
    await create_guild_membership(session, user=admin, guild=guild, role=GuildRole.admin)
    await create_guild_membership(session, user=successor, guild=guild, role=GuildRole.member)
    await create_guild_membership(session, user=member, guild=guild, role=GuildRole.member)
    initiative = await create_initiative(session, guild=guild, creator=admin)
    await create_initiative_member(session, initiative=initiative, user=successor)
    await create_initiative_member(session, initiative=initiative, user=member)
    project = await create_project(session, initiative=initiative, owner=member)

    response = await client.request(
        "DELETE",
        f"/api/v1/users/{member.id}",
        headers=get_guild_headers(guild, admin),
        json={"project_transfers": {str(project.id): successor.id}},
    )
    assert response.status_code == 204

    refreshed = (
        await session.exec(select(Project).where(Project.id == project.id))
    ).one()
    assert refreshed.owner_id == successor.id


@pytest.mark.integration
async def test_user_cannot_update_email_via_patch(client: AsyncClient, session: AsyncSession):
    """Test that users cannot change their email via PATCH /me."""
    user = await create_user(session, email="original@example.com")
    headers = get_auth_headers(user)

    update_data = {"email": "hacked@example.com"}

    response = await client.patch("/api/v1/users/me", headers=headers, json=update_data)

    # Should succeed but email should not change
    assert response.status_code == 200
    data = response.json()
    assert data["email"] == "original@example.com"


@pytest.mark.integration
async def test_user_can_change_password(client: AsyncClient, session: AsyncSession):
    """Test that users can change their password."""
    user = await create_user(session, email="test@example.com")
    headers = get_auth_headers(user)

    update_data = {"password": "newpassword123"}

    response = await client.patch("/api/v1/users/me", headers=headers, json=update_data)

    assert response.status_code == 200

    # TODO: Verify password actually changed by trying to login with new password


@pytest.mark.integration
async def test_inactive_user_cannot_access_endpoints(client: AsyncClient, session: AsyncSession):
    """Test that inactive users cannot access protected endpoints."""
    from app.models.user import User, UserStatus

    # Create inactive user
    user = User(
        email_hash=hash_email("inactive@example.com"),
        email_encrypted=encrypt_field("inactive@example.com", SALT_EMAIL),
        full_name="Inactive User",
        hashed_password="dummy",
        status=UserStatus.deactivated,
    )
    session.add(user)
    await session.commit()

    headers = get_auth_headers(user)

    response = await client.get("/api/v1/users/me", headers=headers)

    # Should be rejected because user is inactive
    assert response.status_code == 400
    assert "inactive" in response.json()["detail"].lower()


@pytest.mark.integration
async def test_user_timezone_validation(client: AsyncClient, session: AsyncSession):
    """Test that invalid timezones are rejected."""
    user = await create_user(session)
    headers = get_auth_headers(user)

    update_data = {"timezone": "Invalid/Timezone"}

    response = await client.patch("/api/v1/users/me", headers=headers, json=update_data)

    assert response.status_code == 400
    assert "timezone" in response.json()["detail"].lower()


@pytest.mark.integration
async def test_user_week_starts_on_validation(client: AsyncClient, session: AsyncSession):
    """Test that week_starts_on only accepts 0-6."""
    user = await create_user(session)
    headers = get_auth_headers(user)

    # Invalid value (7)
    update_data = {"week_starts_on": 7}

    response = await client.patch("/api/v1/users/me", headers=headers, json=update_data)

    assert response.status_code in [400, 422]  # Validation error


@pytest.mark.integration
async def test_task_completion_visual_feedback_round_trip(
    client: AsyncClient, session: AsyncSession
):
    """Each known visual-feedback option round-trips through PATCH /users/me."""
    user = await create_user(session)
    headers = get_auth_headers(user)

    # Default value before any update
    me = await client.get("/api/v1/users/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["task_completion_visual_feedback"] == "none"

    for value in ("confetti", "heart", "d20", "gold_coin", "random", "none"):
        response = await client.patch(
            "/api/v1/users/me",
            headers=headers,
            json={"task_completion_visual_feedback": value},
        )
        assert response.status_code == 200, value
        assert response.json()["task_completion_visual_feedback"] == value


@pytest.mark.integration
async def test_task_completion_visual_feedback_rejects_unknown(
    client: AsyncClient, session: AsyncSession
):
    """Unknown values are rejected with 422 so garbage doesn't reach the column."""
    user = await create_user(session)
    headers = get_auth_headers(user)

    response = await client.patch(
        "/api/v1/users/me",
        headers=headers,
        json={"task_completion_visual_feedback": "fireworks"},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "USER_INVALID_TASK_COMPLETION_VISUAL_FEEDBACK"


@pytest.mark.integration
async def test_task_completion_audio_and_haptic_round_trip(
    client: AsyncClient, session: AsyncSession
):
    """Audio + haptic boolean prefs round-trip and default to True."""
    user = await create_user(session)
    headers = get_auth_headers(user)

    # Both default to True for new users.
    me = await client.get("/api/v1/users/me", headers=headers)
    assert me.status_code == 200
    body = me.json()
    assert body["task_completion_audio_feedback"] is True
    assert body["task_completion_haptic_feedback"] is True

    # Toggle both off, then both on.
    for value in (False, True):
        response = await client.patch(
            "/api/v1/users/me",
            headers=headers,
            json={
                "task_completion_audio_feedback": value,
                "task_completion_haptic_feedback": value,
            },
        )
        assert response.status_code == 200, value
        result = response.json()
        assert result["task_completion_audio_feedback"] is value
        assert result["task_completion_haptic_feedback"] is value


@pytest.mark.integration
async def test_list_users_only_shows_guild_members(client: AsyncClient, session: AsyncSession):
    """Test that listing users only shows members of the current guild."""
    guild1 = await create_guild(session, name="Guild 1")
    guild2 = await create_guild(session, name="Guild 2")

    user1 = await create_user(session, email="user1@example.com")
    user2 = await create_user(session, email="user2@example.com")

    await create_guild_membership(session, user=user1, guild=guild1)
    await create_guild_membership(session, user=user2, guild=guild2)

    headers = get_guild_headers(guild1, user1)

    response = await client.get("/api/v1/users/", headers=headers)

    assert response.status_code == 200
    data = response.json()
    # Should only see user1, not user2
    assert len(data) == 1
    assert data[0]["email"] == "user1@example.com"


def _parse_csv(body: bytes) -> tuple[list[str], list[list[str]]]:
    """Strip the UTF-8 BOM and parse the CSV body into (headers, rows)."""
    import csv
    import io

    text = body.decode("utf-8")
    if text.startswith("\ufeff"):
        text = text[1:]
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    return rows[0], rows[1:]


@pytest.mark.integration
async def test_export_users_csv_as_admin(client: AsyncClient, session: AsyncSession):
    """Guild admin can export all members as CSV."""
    guild = await create_guild(session)
    admin = await create_user(session, email="admin@example.com", full_name="Ada Admin")
    member = await create_user(session, email="member@example.com", full_name="Mel Member")
    await create_guild_membership(session, user=admin, guild=guild, role=GuildRole.admin)
    await create_guild_membership(session, user=member, guild=guild, role=GuildRole.member)

    headers = get_guild_headers(guild, admin)
    response = await client.get("/api/v1/users/export.csv", headers=headers)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "attachment; filename=" in response.headers["content-disposition"]
    assert response.content.startswith("\ufeff".encode("utf-8"))

    header_row, data_rows = _parse_csv(response.content)
    assert header_row == [
        "user_id",
        "email",
        "full_name",
        "guild_role",
        "platform_role",
        "oidc_managed",
        "status",
        "email_verified",
        "created_at",
        "initiative_roles",
    ]
    emails = {row[1] for row in data_rows}
    assert emails == {"admin@example.com", "member@example.com"}


@pytest.mark.integration
async def test_export_users_csv_forbidden_for_member(client: AsyncClient, session: AsyncSession):
    """A plain guild member cannot hit the export endpoint."""
    guild = await create_guild(session)
    member = await create_user(session, email="m@example.com")
    await create_guild_membership(session, user=member, guild=guild, role=GuildRole.member)

    headers = get_guild_headers(guild, member)
    response = await client.get("/api/v1/users/export.csv", headers=headers)

    assert response.status_code == 403


@pytest.mark.integration
async def test_export_users_csv_requires_guild_context(client: AsyncClient, session: AsyncSession):
    """Without the guild header the export is rejected."""
    user = await create_user(session)
    headers = get_auth_headers(user)

    response = await client.get("/api/v1/users/export.csv", headers=headers)
    assert response.status_code == 403


@pytest.mark.integration
async def test_export_users_csv_single_user_id(client: AsyncClient, session: AsyncSession):
    """Passing one user_id returns exactly that row with a per-user filename."""
    guild = await create_guild(session)
    admin = await create_user(session, email="admin@example.com")
    target = await create_user(session, email="target@example.com", full_name="Target User")
    await create_guild_membership(session, user=admin, guild=guild, role=GuildRole.admin)
    await create_guild_membership(session, user=target, guild=guild, role=GuildRole.member)

    headers = get_guild_headers(guild, admin)
    response = await client.get(
        f"/api/v1/users/export.csv?user_id={target.id}", headers=headers
    )

    assert response.status_code == 200
    assert f"user-{target.id}-" in response.headers["content-disposition"]
    _, data_rows = _parse_csv(response.content)
    assert len(data_rows) == 1
    assert data_rows[0][0] == str(target.id)
    assert data_rows[0][1] == "target@example.com"


@pytest.mark.integration
async def test_export_users_csv_multi_user_id(client: AsyncClient, session: AsyncSession):
    """Two user_id values return two rows with a bulk-style filename."""
    guild = await create_guild(session)
    admin = await create_user(session, email="admin@example.com")
    a = await create_user(session, email="a@example.com")
    b = await create_user(session, email="b@example.com")
    await create_guild_membership(session, user=admin, guild=guild, role=GuildRole.admin)
    await create_guild_membership(session, user=a, guild=guild, role=GuildRole.member)
    await create_guild_membership(session, user=b, guild=guild, role=GuildRole.member)

    headers = get_guild_headers(guild, admin)
    response = await client.get(
        f"/api/v1/users/export.csv?user_id={a.id}&user_id={b.id}", headers=headers
    )

    assert response.status_code == 200
    assert "-users-" in response.headers["content-disposition"]
    _, data_rows = _parse_csv(response.content)
    emails = {row[1] for row in data_rows}
    assert emails == {"a@example.com", "b@example.com"}


@pytest.mark.integration
async def test_export_users_csv_partial_miss(client: AsyncClient, session: AsyncSession):
    """Unknown ids are dropped silently; known ids are returned."""
    guild = await create_guild(session)
    admin = await create_user(session, email="admin@example.com")
    target = await create_user(session, email="target@example.com")
    await create_guild_membership(session, user=admin, guild=guild, role=GuildRole.admin)
    await create_guild_membership(session, user=target, guild=guild, role=GuildRole.member)

    headers = get_guild_headers(guild, admin)
    response = await client.get(
        f"/api/v1/users/export.csv?user_id={target.id}&user_id=99999", headers=headers
    )

    assert response.status_code == 200
    _, data_rows = _parse_csv(response.content)
    assert len(data_rows) == 1
    assert data_rows[0][0] == str(target.id)


@pytest.mark.integration
async def test_export_users_csv_no_matches_returns_404(client: AsyncClient, session: AsyncSession):
    """All requested ids missing/invisible under RLS -> 404."""
    guild = await create_guild(session)
    admin = await create_user(session, email="admin@example.com")
    await create_guild_membership(session, user=admin, guild=guild, role=GuildRole.admin)

    headers = get_guild_headers(guild, admin)
    response = await client.get(
        "/api/v1/users/export.csv?user_id=99998&user_id=99999", headers=headers
    )

    assert response.status_code == 404


@pytest.mark.integration
async def test_export_users_csv_user_outside_guild(client: AsyncClient, session: AsyncSession):
    """A user who exists but isn't in the active guild is not visible."""
    guild1 = await create_guild(session)
    guild2 = await create_guild(session)
    admin = await create_user(session, email="admin@example.com")
    outsider = await create_user(session, email="outsider@example.com")
    await create_guild_membership(session, user=admin, guild=guild1, role=GuildRole.admin)
    await create_guild_membership(session, user=outsider, guild=guild2, role=GuildRole.member)

    headers = get_guild_headers(guild1, admin)
    response = await client.get(
        f"/api/v1/users/export.csv?user_id={outsider.id}", headers=headers
    )

    assert response.status_code == 404


@pytest.mark.integration
async def test_oidc_user_can_self_delete_without_password(
    client: AsyncClient, session: AsyncSession
):
    """OIDC-provisioned users have no usable password (the random hash
    set at SSO callback was never shown). The self-deletion endpoint
    must skip the password gate for them, otherwise they'd be
    permanently blocked from the "Delete account" flow.
    """
    user = await create_user(session, email="oidc-user@example.com")
    user.oidc_sub = "oidc-subject-123"
    session.add(user)
    await session.commit()

    headers = get_auth_headers(user)
    response = await client.post(
        "/api/v1/users/me/delete-account",
        headers=headers,
        json={
            "action": "soft_delete",
            "password": "",
            "confirmation_text": "DELETE MY ACCOUNT",
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["success"] is True
    assert body["action"] == "soft_delete"


@pytest.mark.integration
async def test_password_user_cannot_skip_password_check(
    client: AsyncClient, session: AsyncSession
):
    """A non-OIDC user still has to satisfy the password gate."""
    from app.core.security import get_password_hash

    user = await create_user(session, email="pwd-user@example.com")
    user.hashed_password = get_password_hash("real-password")
    session.add(user)
    await session.commit()

    headers = get_auth_headers(user)
    response = await client.post(
        "/api/v1/users/me/delete-account",
        headers=headers,
        json={
            "action": "soft_delete",
            "password": "wrong-password",
            "confirmation_text": "DELETE MY ACCOUNT",
        },
    )

    # 400 (not 401): the user IS authenticated; a 401 here would
    # cascade through the SPA's global axios interceptor and force a
    # logout, which is the original bug this status code change fixed.
    assert response.status_code == 400
    assert response.json()["detail"] == "USER_INVALID_PASSWORD"


@pytest.mark.integration
async def test_initiative_members_excludes_anonymized(
    client: AsyncClient, session: AsyncSession
):
    """The transfer-target picker must not return anonymized rows.

    Regression: without the status filter, an anonymized husk would
    appear as a selectable project transfer target — and since the
    backend transfer accepted any user id, a self-deleting user could
    hand a live project to a non-person.
    """
    from app.services import users as users_service
    from app.testing.factories import (
        create_initiative,
        create_initiative_member,
    )

    creator = await create_user(session, email="creator@example.com")
    guild = await create_guild(session, creator=creator)
    initiative = await create_initiative(session, guild=guild, creator=creator)

    departing = await create_user(session, email="departing@example.com")
    await create_initiative_member(session, initiative=initiative, user=departing)

    survivor = await create_user(session, email="survivor@example.com")
    await create_initiative_member(session, initiative=initiative, user=survivor)

    # Anonymize the departing user — they should disappear from the picker.
    await users_service.soft_delete_user(session, departing.id)

    headers = get_auth_headers(creator)
    response = await client.get(
        f"/api/v1/users/me/initiative-members/{initiative.id}", headers=headers
    )
    assert response.status_code == 200
    ids = {member["id"] for member in response.json()}
    assert departing.id not in ids
    assert survivor.id in ids


@pytest.mark.integration
async def test_self_delete_rejects_anonymized_transfer_target(
    client: AsyncClient, session: AsyncSession
):
    """Even if the client crafts a request that targets an anonymized
    user, ``transfer_project_ownership`` refuses and the endpoint
    returns a 400 instead of stranding a project on a husk."""
    from app.services import users as users_service
    from app.testing.factories import (
        create_initiative,
        create_initiative_member,
        create_project,
    )

    owner = await create_user(session, email="leaving@example.com")
    co_admin = await create_user(session, email="co-admin@example.com")
    guild = await create_guild(session, creator=owner)
    await create_guild_membership(session, user=owner, guild=guild, role=GuildRole.admin)
    await create_guild_membership(session, user=co_admin, guild=guild, role=GuildRole.admin)
    initiative = await create_initiative(session, guild=guild, creator=owner)
    # Add co_admin as another PM so the eligibility check passes.
    await create_initiative_member(
        session, initiative=initiative, user=co_admin, role_name="project_manager",
    )

    husk = await create_user(session, email="husk@example.com")
    await create_initiative_member(session, initiative=initiative, user=husk)
    await users_service.soft_delete_user(session, husk.id)

    project = await create_project(session, initiative=initiative, owner=owner)

    headers = get_auth_headers(owner)
    response = await client.post(
        "/api/v1/users/me/delete-account",
        headers=headers,
        json={
            "action": "soft_delete",
            "password": "testpassword123",
            "confirmation_text": "DELETE MY ACCOUNT",
            "project_transfers": {str(project.id): husk.id},
        },
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "USER_INVALID_TRANSFER_RECIPIENT"
