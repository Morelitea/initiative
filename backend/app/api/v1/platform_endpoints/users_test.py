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

from app.core import usernames
from app.core.encryption import encrypt_field, hash_email, SALT_EMAIL
from app.db.query import MAX_ID_FILTER_VALUES
from app.db.session import set_rls_context
from app.models.platform.guild import GuildRole
from app.models.platform.user import User, UserStatus
from app.models.tenant.task_assignment_digest import TaskAssignmentDigestItem

from app.testing.factories import (
    create_federated_identity,
    create_guild,
    create_guild_membership,
    create_initiative,
    create_project,
    create_task,
    create_user,
    get_auth_headers,
    get_auth_token,
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


async def _queue_assignment_item(session: AsyncSession, user, guild) -> None:
    """Put one pending digest item in ``guild``'s schema for ``user``."""
    initiative = await create_initiative(session, guild, user, name="Queue")
    project = await create_project(session, initiative, user, name="Queue Project")
    task = await create_task(session, project, title="Queued")
    await set_rls_context(session, user_id=user.id, guild_id=guild.id)
    session.add(
        TaskAssignmentDigestItem(
            user_id=user.id,
            task_id=task.id,
            project_id=project.id,
            task_title="Queued",
            project_name=project.name,
            assigned_by_name="Assigner",
        )
    )
    await session.commit()


async def _pending_assignment_items(session: AsyncSession, user, guild) -> int:
    session.expunge_all()
    await set_rls_context(session, user_id=user.id, guild_id=guild.id)
    rows = (
        await session.exec(
            select(TaskAssignmentDigestItem).where(
                TaskAssignmentDigestItem.processed_at.is_(None)
            )
        )
    ).all()
    return len(rows)


@pytest.mark.integration
async def test_disabling_assignment_email_keeps_the_push_queue(
    client: AsyncClient, session: AsyncSession
):
    """One queue now backs both channels, so switching the email off must not
    discard the items the push digest is still going to send."""
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    await create_guild_membership(session, user=user, guild=guild)
    await _queue_assignment_item(session, user, guild)

    response = await client.patch(
        "/api/v1/users/me",
        headers=get_auth_headers(user),
        json={"email_task_assignment": False},
    )

    assert response.status_code == 200
    assert response.json()["email_task_assignment"] is False
    assert await _pending_assignment_items(session, user, guild) == 1


@pytest.mark.integration
async def test_disabling_both_assignment_channels_clears_the_queue(
    client: AsyncClient, session: AsyncSession
):
    """With neither channel left on, nothing will ever send the items."""
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    await create_guild_membership(session, user=user, guild=guild)
    await _queue_assignment_item(session, user, guild)

    response = await client.patch(
        "/api/v1/users/me",
        headers=get_auth_headers(user),
        json={"email_task_assignment": False, "push_task_assignment": False},
    )

    assert response.status_code == 200
    assert await _pending_assignment_items(session, user, guild) == 0


@pytest.mark.integration
async def test_list_users_in_guild(client: AsyncClient, session: AsyncSession):
    """Test listing users in a guild."""
    guild = await create_guild(session)
    user1 = await create_user(session, username="user-one", full_name="User One")
    user2 = await create_user(session, username="user-two", full_name="User Two")

    await create_guild_membership(session, user=user1, guild=guild)
    await create_guild_membership(session, user=user2, guild=guild)

    headers = get_auth_headers(user1)

    response = await client.get(f"/api/v1/g/{guild.id}/users/", headers=headers)

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    # Members are named by handle. An address is never a guild's to hand out,
    # so it is absent from the shape entirely.
    assert {user["username"] for user in data} == {"user-one", "user-two"}
    assert all("email" not in user for user in data)


@pytest.mark.integration
async def test_search_users_returns_slim_paginated_envelope(
    client: AsyncClient, session: AsyncSession
):
    """The slim search endpoint returns a UserSummary envelope (no email /
    role / initiative_roles) and honours page_size."""
    guild = await create_guild(session)
    caller = await create_user(session, username="aaa-caller", full_name="Aaa")
    other = await create_user(session, username="bbb-other", full_name="Bbb")
    third = await create_user(session, username="ccc-third", full_name="Ccc")
    for user in (caller, other, third):
        await create_guild_membership(session, user=user, guild=guild)

    headers = get_auth_headers(caller)

    response = await client.get(
        f"/api/v1/g/{guild.id}/users/search",
        headers=headers,
        params={"page_size": 2, "page": 1},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total_count"] == 3
    assert body["page"] == 1
    assert body["page_size"] == 2
    assert body["has_next"] is True
    assert body["has_prev"] is False
    assert len(body["items"]) == 2
    # This guild renders handles, so it orders by them too.
    assert [item["username"] for item in body["items"]] == ["aaa-caller", "bbb-other"]
    # Slim projection: no email, no platform role, no initiative_roles — and
    # no name, because this guild does not show them.
    summary = body["items"][0]
    assert set(summary.keys()) == {
        "id",
        "username",
        "discriminator",
        "full_name",
        "avatar_url",
        "status",
    }
    assert summary["full_name"] is None


@pytest.mark.integration
async def test_search_users_filters_by_name(client: AsyncClient, session: AsyncSession):
    """The `search` param is a case-insensitive substring match on the handle's
    name part — which is what this guild renders, so it is what it matches."""
    guild = await create_guild(session)
    caller = await create_user(session, username="asmith", full_name="Alice Smith")
    bob = await create_user(session, username="bjones", full_name="Bob Jones")
    for user in (caller, bob):
        await create_guild_membership(session, user=user, guild=guild)

    headers = get_auth_headers(caller)

    response = await client.get(
        f"/api/v1/g/{guild.id}/users/search",
        headers=headers,
        params={"search": "SMITH"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total_count"] == 1
    assert [item["username"] for item in body["items"]] == ["asmith"]


@pytest.mark.integration
async def test_search_users_filters_by_user_id(
    client: AsyncClient, session: AsyncSession
):
    """`user_id` resolves a known selection, and only ever narrows the roster
    the caller can already see — an id from another guild returns nothing."""
    guild = await create_guild(session)
    caller = await create_user(
        session, email="caller@example.com", full_name="Alice Smith"
    )
    bob = await create_user(session, email="bob@example.com", full_name="Bob Jones")
    for user in (caller, bob):
        await create_guild_membership(session, user=user, guild=guild)

    other_guild = await create_guild(session)
    stranger = await create_user(
        session, email="stranger@example.com", full_name="Stranger Danger"
    )
    await create_guild_membership(session, user=stranger, guild=other_guild)

    headers = get_auth_headers(caller)

    response = await client.get(
        f"/api/v1/g/{guild.id}/users/search",
        headers=headers,
        params={"user_id": [bob.id]},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total_count"] == 1
    assert [item["username"] for item in body["items"]] == [bob.username]

    # An id outside the guild is filtered out, not resolved.
    response = await client.get(
        f"/api/v1/g/{guild.id}/users/search",
        headers=headers,
        params={"user_id": [bob.id, stranger.id]},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total_count"] == 1
    assert [item["id"] for item in body["items"]] == [bob.id]


@pytest.mark.integration
async def test_search_users_rejects_oversized_user_id_list(
    client: AsyncClient, session: AsyncSession
):
    """The id filter is bounded so one request can't submit an unbounded list."""
    guild = await create_guild(session)
    caller = await create_user(session, email="caller@example.com")
    await create_guild_membership(session, user=caller, guild=guild)

    response = await client.get(
        f"/api/v1/g/{guild.id}/users/search",
        headers=get_auth_headers(caller),
        params={"user_id": list(range(MAX_ID_FILTER_VALUES + 1))},
    )

    assert response.status_code == 422


@pytest.mark.integration
async def test_search_users_requires_membership(
    client: AsyncClient, session: AsyncSession
):
    """A non-member cannot reach the guild's slim roster (path is a selector,
    not a trust boundary)."""
    guild = await create_guild(session)
    outsider = await create_user(session, email="outsider@example.com")
    # No guild membership for the outsider.

    headers = get_auth_headers(outsider)

    response = await client.get(f"/api/v1/g/{guild.id}/users/search", headers=headers)

    assert response.status_code == 403


@pytest.mark.integration
async def test_self_service_password_change_revokes_sessions_and_device_tokens(
    client: AsyncClient, session: AsyncSession
):
    """Changing your own password via PATCH /users/me must invalidate other
    outstanding JWTs and active device tokens — completing the three-path
    symmetry with the admin-reset and forgot-password flows (all share
    ``revoke_user_sessions`` / ``revoke_active_device_tokens``)."""
    from app.models.platform.user_token import UserToken, UserTokenPurpose
    from app.services.platform import user_tokens

    user = await create_user(session, email="self-change@example.com")
    old_jwt = get_auth_token(user)
    device_token = await user_tokens.create_device_token(
        session, user_id=user.id, device_name="Old phone"
    )

    response = await client.patch(
        "/api/v1/users/me",
        json={
            "password": "brand-new-secret-123",
            "current_password": "testpassword123",
        },
        headers={"Authorization": f"Bearer {old_jwt}"},
    )
    assert response.status_code == 200

    # The pre-change JWT is rejected (token_version bumped).
    stale = await client.get(
        "/api/v1/users/me",
        headers={"Authorization": f"Bearer {old_jwt}"},
    )
    assert stale.status_code == 401

    # The device token was revoked (consumed).
    stale_device = await client.get(
        "/api/v1/users/me",
        headers={"Authorization": f"DeviceToken {device_token}"},
    )
    assert stale_device.status_code == 401
    token_row = (
        await session.exec(
            select(UserToken).where(
                UserToken.user_id == user.id,
                UserToken.purpose == UserTokenPurpose.device_auth,
            )
        )
    ).one()
    assert token_row.consumed_at is not None


@pytest.mark.integration
async def test_check_deletion_eligibility(client: AsyncClient, session: AsyncSession):
    """Test checking if user can delete their account."""
    guild = await create_guild(session)
    admin = await create_user(session, email="admin@example.com")
    member = await create_user(session, email="member@example.com")

    await create_guild_membership(
        session, user=admin, guild=guild, role=GuildRole.admin
    )
    await create_guild_membership(
        session, user=member, guild=guild, role=GuildRole.member
    )

    headers = get_auth_headers(member)

    response = await client.get(
        "/api/v1/users/me/deletion-eligibility", headers=headers
    )

    assert response.status_code == 200
    data = response.json()
    assert "can_delete" in data
    assert "blockers" in data


@pytest.mark.integration
async def test_delete_user_as_admin(client: AsyncClient, session: AsyncSession):
    """Test that guild admin can delete users."""
    guild = await create_guild(session)
    admin = await create_user(session, email="admin@example.com")
    member = await create_user(session, email="member@example.com")

    await create_guild_membership(
        session, user=admin, guild=guild, role=GuildRole.admin
    )
    await create_guild_membership(
        session, user=member, guild=guild, role=GuildRole.member
    )

    headers = get_auth_headers(admin)

    response = await client.delete(
        f"/api/v1/g/{guild.id}/users/{member.id}", headers=headers
    )

    assert response.status_code == 204


@pytest.mark.integration
async def test_delete_user_as_member_forbidden(
    client: AsyncClient, session: AsyncSession
):
    """Test that regular members cannot delete users."""
    guild = await create_guild(session)
    member1 = await create_user(session, email="member1@example.com")
    member2 = await create_user(session, email="member2@example.com")

    await create_guild_membership(
        session, user=member1, guild=guild, role=GuildRole.member
    )
    await create_guild_membership(
        session, user=member2, guild=guild, role=GuildRole.member
    )

    headers = get_auth_headers(member1)

    response = await client.delete(
        f"/api/v1/g/{guild.id}/users/{member2.id}", headers=headers
    )

    assert response.status_code == 403


@pytest.mark.integration
async def test_user_cannot_update_email_via_patch(
    client: AsyncClient, session: AsyncSession
):
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
    """Changing your own password requires the current password, so a leaked
    bearer token / API key can't silently take over the account."""
    user = await create_user(session, email="test@example.com")
    headers = get_auth_headers(user)

    # Missing current password is refused.
    missing = await client.patch(
        "/api/v1/users/me",
        headers=headers,
        json={"password": "newpassword123"},
    )
    assert missing.status_code == 400
    assert missing.json()["detail"] == "USER_CURRENT_PASSWORD_REQUIRED"

    # Wrong current password is refused.
    wrong = await client.patch(
        "/api/v1/users/me",
        headers=headers,
        json={"password": "newpassword123", "current_password": "not-it"},
    )
    assert wrong.status_code == 400
    assert wrong.json()["detail"] == "USER_CURRENT_PASSWORD_INCORRECT"

    # Correct current password succeeds.
    ok = await client.patch(
        "/api/v1/users/me",
        headers=headers,
        json={"password": "newpassword123", "current_password": "testpassword123"},
    )
    assert ok.status_code == 200


@pytest.mark.integration
async def test_inactive_user_cannot_access_endpoints(
    client: AsyncClient, session: AsyncSession
):
    """Test that inactive users cannot access protected endpoints."""

    # Create inactive user
    user = User(
        username=usernames.random_name(),
        discriminator=usernames.random_discriminator(),
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
async def test_user_week_starts_on_validation(
    client: AsyncClient, session: AsyncSession
):
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
async def test_list_users_only_shows_guild_members(
    client: AsyncClient, session: AsyncSession
):
    """Test that listing users only shows members of the current guild."""
    guild1 = await create_guild(session, name="Guild 1")
    guild2 = await create_guild(session, name="Guild 2")

    user1 = await create_user(session, email="user1@example.com")
    user2 = await create_user(session, email="user2@example.com")

    await create_guild_membership(session, user=user1, guild=guild1)
    await create_guild_membership(session, user=user2, guild=guild2)

    headers = get_auth_headers(user1)

    response = await client.get(f"/api/v1/g/{guild1.id}/users/", headers=headers)

    assert response.status_code == 200
    data = response.json()
    # Should only see user1, not user2
    assert len(data) == 1
    assert data[0]["id"] == user1.id


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
    member = await create_user(
        session, email="member@example.com", full_name="Mel Member"
    )
    await create_guild_membership(
        session, user=admin, guild=guild, role=GuildRole.admin
    )
    await create_guild_membership(
        session, user=member, guild=guild, role=GuildRole.member
    )

    headers = get_auth_headers(admin)
    response = await client.get(
        f"/api/v1/g/{guild.id}/users/export.csv", headers=headers
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "attachment; filename=" in response.headers["content-disposition"]
    assert response.content.startswith("\ufeff".encode("utf-8"))

    header_row, data_rows = _parse_csv(response.content)
    assert header_row == [
        "user_id",
        "handle",
        "full_name",
        "guild_role",
        "platform_role",
        "oidc_managed",
        "status",
        "email_verified",
        "created_at",
        "initiative_roles",
    ]
    handles = {row[1] for row in data_rows}
    assert handles == {
        f"{admin.username}#{admin.discriminator:04d}",
        f"{member.username}#{member.discriminator:04d}",
    }
    # No address anywhere in the file.
    assert not any("@" in cell for row in data_rows for cell in row)


@pytest.mark.integration
async def test_export_users_csv_forbidden_for_member(
    client: AsyncClient, session: AsyncSession
):
    """A plain guild member cannot hit the export endpoint."""
    guild = await create_guild(session)
    member = await create_user(session, email="m@example.com")
    await create_guild_membership(
        session, user=member, guild=guild, role=GuildRole.member
    )

    headers = get_auth_headers(member)
    response = await client.get(
        f"/api/v1/g/{guild.id}/users/export.csv", headers=headers
    )

    assert response.status_code == 403


@pytest.mark.integration
async def test_export_users_csv_single_user_id(
    client: AsyncClient, session: AsyncSession
):
    """Passing one user_id returns exactly that row with a per-user filename."""
    guild = await create_guild(session)
    admin = await create_user(session, email="admin@example.com")
    target = await create_user(
        session, email="target@example.com", full_name="Target User"
    )
    await create_guild_membership(
        session, user=admin, guild=guild, role=GuildRole.admin
    )
    await create_guild_membership(
        session, user=target, guild=guild, role=GuildRole.member
    )

    headers = get_auth_headers(admin)
    response = await client.get(
        f"/api/v1/g/{guild.id}/users/export.csv?user_id={target.id}", headers=headers
    )

    assert response.status_code == 200
    assert (
        f"user-{target.id}-{target.username}" in response.headers["content-disposition"]
    )
    _, data_rows = _parse_csv(response.content)
    assert len(data_rows) == 1
    assert data_rows[0][0] == str(target.id)
    assert data_rows[0][1] == f"{target.username}#{target.discriminator:04d}"


@pytest.mark.integration
async def test_export_users_csv_multi_user_id(
    client: AsyncClient, session: AsyncSession
):
    """Two user_id values return two rows with a bulk-style filename."""
    guild = await create_guild(session)
    admin = await create_user(session, email="admin@example.com")
    a = await create_user(session, email="a@example.com")
    b = await create_user(session, email="b@example.com")
    await create_guild_membership(
        session, user=admin, guild=guild, role=GuildRole.admin
    )
    await create_guild_membership(session, user=a, guild=guild, role=GuildRole.member)
    await create_guild_membership(session, user=b, guild=guild, role=GuildRole.member)

    headers = get_auth_headers(admin)
    response = await client.get(
        f"/api/v1/g/{guild.id}/users/export.csv?user_id={a.id}&user_id={b.id}",
        headers=headers,
    )

    assert response.status_code == 200
    assert "-users-" in response.headers["content-disposition"]
    _, data_rows = _parse_csv(response.content)
    handles = {row[1] for row in data_rows}
    assert handles == {
        f"{a.username}#{a.discriminator:04d}",
        f"{b.username}#{b.discriminator:04d}",
    }


@pytest.mark.integration
async def test_export_users_csv_partial_miss(
    client: AsyncClient, session: AsyncSession
):
    """Unknown ids are dropped silently; known ids are returned."""
    guild = await create_guild(session)
    admin = await create_user(session, email="admin@example.com")
    target = await create_user(session, email="target@example.com")
    await create_guild_membership(
        session, user=admin, guild=guild, role=GuildRole.admin
    )
    await create_guild_membership(
        session, user=target, guild=guild, role=GuildRole.member
    )

    headers = get_auth_headers(admin)
    response = await client.get(
        f"/api/v1/g/{guild.id}/users/export.csv?user_id={target.id}&user_id=99999",
        headers=headers,
    )

    assert response.status_code == 200
    _, data_rows = _parse_csv(response.content)
    assert len(data_rows) == 1
    assert data_rows[0][0] == str(target.id)


@pytest.mark.integration
async def test_export_users_csv_no_matches_returns_404(
    client: AsyncClient, session: AsyncSession
):
    """All requested ids missing/invisible under RLS -> 404."""
    guild = await create_guild(session)
    admin = await create_user(session, email="admin@example.com")
    await create_guild_membership(
        session, user=admin, guild=guild, role=GuildRole.admin
    )

    headers = get_auth_headers(admin)
    response = await client.get(
        f"/api/v1/g/{guild.id}/users/export.csv?user_id=99998&user_id=99999",
        headers=headers,
    )

    assert response.status_code == 404


@pytest.mark.integration
async def test_export_users_csv_user_outside_guild(
    client: AsyncClient, session: AsyncSession
):
    """A user who exists but isn't in the active guild is not visible."""
    guild1 = await create_guild(session)
    guild2 = await create_guild(session)
    admin = await create_user(session, email="admin@example.com")
    outsider = await create_user(session, email="outsider@example.com")
    await create_guild_membership(
        session, user=admin, guild=guild1, role=GuildRole.admin
    )
    await create_guild_membership(
        session, user=outsider, guild=guild2, role=GuildRole.member
    )

    headers = get_auth_headers(admin)
    response = await client.get(
        f"/api/v1/g/{guild1.id}/users/export.csv?user_id={outsider.id}", headers=headers
    )

    assert response.status_code == 404


@pytest.mark.integration
async def test_password_change_keeps_this_device_signed_in(
    client: AsyncClient, session: AsyncSession
):
    """Changing the password revokes every other session, but THIS device gets
    a fresh server-side session: both cookies are re-issued and the new
    refresh chain rotates."""
    await create_user(session, email="pwkeep@example.com")

    login = await client.post(
        "/api/v1/auth/token",
        data={"username": "pwkeep@example.com", "password": "testpassword123"},
    )
    assert login.status_code == 200

    change = await client.patch(
        "/api/v1/users/me",
        json={"password": "newpassword456", "current_password": "testpassword123"},
    )
    assert change.status_code == 200
    assert change.cookies.get("refresh_token")  # fresh chain for this device

    rotated = await client.post("/api/v1/auth/refresh")
    assert rotated.status_code == 200
    me = await client.get(
        "/api/v1/users/me",
        headers={"Authorization": f"Bearer {rotated.json()['access_token']}"},
    )
    assert me.status_code == 200


@pytest.mark.integration
async def test_password_change_fallback_clears_dead_refresh_cookie(
    client: AsyncClient, session: AsyncSession, monkeypatch
):
    """If the session store fails right after the global revocation, the
    legacy re-issue must also clear the (now revoked) refresh cookie so the
    SPA doesn't resend a dead token on its next silent renewal."""
    await create_user(session, email="pwfall@example.com")

    login = await client.post(
        "/api/v1/auth/token",
        data={"username": "pwfall@example.com", "password": "testpassword123"},
    )
    assert login.status_code == 200
    assert login.cookies.get("refresh_token")

    async def _boom(*args, **kwargs):
        raise RuntimeError("session store down")

    monkeypatch.setattr("app.services.auth.sessions.create_session", _boom)

    change = await client.patch(
        "/api/v1/users/me",
        json={"password": "newpassword456", "current_password": "testpassword123"},
    )
    assert change.status_code == 200
    set_cookies = change.headers.get_list("set-cookie")
    assert any(
        c.startswith("refresh_token=") and ("Max-Age=0" in c or "1970" in c)
        for c in set_cookies
    ), set_cookies
    assert any(c.startswith("session_token=") for c in set_cookies)


@pytest.mark.integration
async def test_users_me_reports_linked_identity(
    client: AsyncClient, session: AsyncSession
):
    """/users/me carries has_federated_identity — the signal the profile and
    deletion dialogs use to hide the password confirmation for SSO accounts."""
    linked = await create_user(session, email="linked-sso@example.com")
    await create_federated_identity(session, linked)
    plain = await create_user(session, email="plain-pwd@example.com")

    response = await client.get("/api/v1/users/me", headers=get_auth_headers(linked))
    assert response.status_code == 200
    assert response.json()["has_federated_identity"] is True

    response = await client.get("/api/v1/users/me", headers=get_auth_headers(plain))
    assert response.status_code == 200
    assert response.json()["has_federated_identity"] is False


@pytest.mark.integration
async def test_oidc_user_can_self_delete_without_password(
    client: AsyncClient, session: AsyncSession
):
    """SSO-provisioned users have no usable password (the random hash
    set at provisioning was never shown). The self-deletion endpoint
    must skip the password gate for them, otherwise they'd be
    permanently blocked from the "Delete account" flow.
    """
    user = await create_user(session, email="oidc-user@example.com")
    await create_federated_identity(session, user, subject="oidc-subject-123")

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
    from app.services.platform import users as users_service
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
        f"/api/v1/users/me/initiative-members/{initiative.id}",
        params={"guild_id": guild.id},
        headers=headers,
    )
    assert response.status_code == 200
    ids = {member["id"] for member in response.json()}
    assert departing.id not in ids
    assert survivor.id in ids
