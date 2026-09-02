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
from sqlalchemy import update
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core import usernames
from app.core.encryption import encrypt_field, hash_email, SALT_EMAIL
from app.db.query import MAX_ID_FILTER_VALUES
from app.db.session import set_rls_context
from app.models.platform.guild import GuildRole
from app.models.platform.user import Presence, User, UserStatus
from app.core.profile_decorations import SHIPPED_DECORATIONS
from app.core.usernames import url_handle
from app.models.platform.user_decoration import UserDecoration
from app.services.marketplace import catalog as marketplace_catalog
from app.services.marketplace.builtin import load_builtin_manifests
from app.services.platform import profile_decorations as profile_decorations_service
from app.models.tenant.task_assignment_digest import TaskAssignmentDigestItem
from app.services.platform import notification_stream
from app.services.realtime import manager as realtime_manager

from app.testing.factories import (
    create_federated_identity,
    create_guild,
    create_guild_membership,
    create_initiative,
    create_marketplace_listing,
    create_profile_pack,
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
    assert [item["username"] for item in body["items"]] == ["aaa-caller", "bbb-other"]
    # Slim projection: no email, no platform role, no initiative_roles.
    summary = body["items"][0]
    assert set(summary.keys()) == {
        "id",
        "username",
        "discriminator",
        "full_name",
        "avatar_url",
        "status",
    }
    # This guild takes the default and shows names.
    assert summary["full_name"] == "Aaa"


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
async def test_search_users_finds_a_name_typed_nearly_right(
    client: AsyncClient, session: AsyncSession
):
    """Reading a roster is how you learn a colleague's spelling, so requiring
    it first is the wrong way round. A dropped letter and a transposition both
    still find the person."""
    guild = await create_guild(session)
    caller = await create_user(session, username="asmith", full_name="Alice Smith")
    target = await create_user(
        session, username="thorn-ironforge", full_name="Thorn Ironforge"
    )
    for user in (caller, target):
        await create_guild_membership(session, user=user, guild=guild)

    for typed in ("irnforge", "ironfroge"):
        response = await client.get(
            f"/api/v1/g/{guild.id}/users/search",
            headers=get_auth_headers(caller),
            params={"search": typed},
        )
        assert response.status_code == 200, response.text
        found = [item["username"] for item in response.json()["items"]]
        assert "thorn-ironforge" in found, f"{typed} found {found}"


@pytest.mark.integration
async def test_search_users_never_reaches_another_guild(
    client: AsyncClient, session: AsyncSession
):
    """Matching a name more loosely must not widen WHOSE names are matched.
    Only this guild's members are ever searched, exact spelling or not."""
    guild = await create_guild(session)
    caller = await create_user(session, username="asmith", full_name="Alice Smith")
    await create_guild_membership(session, user=caller, guild=guild)

    elsewhere = await create_guild(session)
    stranger = await create_user(
        session, username="thorn-ironforge", full_name="Thorn Ironforge"
    )
    await create_guild_membership(session, user=stranger, guild=elsewhere)

    for typed in ("ironforge", "irnforge", "thorn"):
        response = await client.get(
            f"/api/v1/g/{guild.id}/users/search",
            headers=get_auth_headers(caller),
            params={"search": typed},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["total_count"] == 0, f"{typed} reached {body['items']}"


@pytest.mark.integration
async def test_search_users_matches_real_names_only_where_they_are_shown(
    client: AsyncClient, session: AsyncSession
):
    """A real name is searchable exactly where it is shown. In a guild that
    hides them, neither the spelling of one nor a near miss at it matches."""
    guild = await create_guild(session, show_member_names=False)
    caller = await create_user(session, username="asmith", full_name="Alice Smith")
    hidden = await create_user(session, username="qzx", full_name="Bartholomew Higgins")
    for user in (caller, hidden):
        await create_guild_membership(session, user=user, guild=guild)

    for typed in ("Bartholomew", "Bartholemew", "Higgins"):
        response = await client.get(
            f"/api/v1/g/{guild.id}/users/search",
            headers=get_auth_headers(caller),
            params={"search": typed},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["total_count"] == 0, f"{typed} matched a name this guild hides"


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


@pytest.mark.integration
async def test_profile_carries_the_basics(client: AsyncClient, session: AsyncSession):
    """A profile: the handle, the face, the line they wrote, the look they
    picked, and when they joined."""
    caller = await create_user(session)
    subject = await create_user(
        session,
        username="tinker",
        full_name="Tinker Bell",
        avatar_url="https://example.com/tinker.png",
        custom_status={"emoji": "\N{GAME DIE}", "text": "rolling for initiative"},
        profile_decorations={"banner": "core.aurora", "trophies": ["core.fan"]},
    )

    response = await client.get(
        f"/api/v1/users/{url_handle(subject.username, subject.discriminator)}/profile",
        headers=get_auth_headers(caller),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == subject.id
    assert body["username"] == "tinker"
    assert body["avatar_url"] == "https://example.com/tinker.png"
    assert body["custom_status"] == {
        "emoji": "\N{GAME DIE}",
        "text": "rolling for initiative",
    }
    assert body["profile_decorations"] == {
        "banner": "core.aurora",
        "frame_tint": [],
        "frame": None,
        "trophies": ["core.fan"],
    }
    assert body["presence"] == "offline"
    assert body["joined_at"]


@pytest.mark.integration
async def test_profile_never_carries_a_real_name(
    client: AsyncClient, session: AsyncSession
):
    """The handle is the name here. A profile is the same page for everyone,
    so it carries nothing a guild decides the visibility of."""
    caller = await create_user(session)
    subject = await create_user(session, username="tinker", full_name="Tinker Bell")

    response = await client.get(
        f"/api/v1/users/{url_handle(subject.username, subject.discriminator)}/profile",
        headers=get_auth_headers(caller),
    )

    assert response.status_code == 200
    body = response.json()
    assert "full_name" not in body
    assert body["username"] == "tinker"
    # Nor anything else the account keeps to itself.
    assert set(body.keys()) == {
        "id",
        "username",
        "discriminator",
        "avatar_url",
        "status",
        "custom_status",
        "profile_decorations",
        "presence",
        "joined_at",
    }


@pytest.mark.integration
async def test_profile_needs_no_guild_in_common(
    client: AsyncClient, session: AsyncSession
):
    """Profiles are public: sharing a guild is not what makes one readable."""
    guild = await create_guild(session)
    caller = await create_user(session)
    await create_guild_membership(session, user=caller, guild=guild)
    stranger = await create_user(session, username="stranger")

    response = await client.get(
        f"/api/v1/users/{url_handle(stranger.username, stranger.discriminator)}/profile",
        headers=get_auth_headers(caller),
    )

    assert response.status_code == 200
    assert response.json()["username"] == "stranger"


@pytest.mark.integration
async def test_profile_hides_a_suspended_account(
    client: AsyncClient, session: AsyncSession
):
    """A suspended account vanishes from rosters, and from the page they lead
    to."""
    caller = await create_user(session)
    subject = await create_user(session, status=UserStatus.suspended)

    response = await client.get(
        f"/api/v1/users/{url_handle(subject.username, subject.discriminator)}/profile",
        headers=get_auth_headers(caller),
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "USER_NOT_FOUND"


@pytest.mark.integration
async def test_profile_says_when_someone_is_online(
    client: AsyncClient, session: AsyncSession
):
    """How someone appears is a fact about the person, not about a guild — a
    reader who shares no guild with them still sees it."""
    guild = await create_guild(session)
    caller = await create_user(session)
    subject = await create_user(session)
    await create_guild_membership(session, user=subject, guild=guild)

    socket = object()
    await realtime_manager.connect(guild.id, [], socket, user_id=subject.id)  # type: ignore[arg-type]
    try:
        response = await client.get(
            f"/api/v1/users/{url_handle(subject.username, subject.discriminator)}/profile",
            headers=get_auth_headers(caller),
        )
    finally:
        await realtime_manager.disconnect(socket)  # type: ignore[arg-type]

    assert response.status_code == 200
    assert response.json()["presence"] == "online"

    after = await client.get(
        f"/api/v1/users/{url_handle(subject.username, subject.discriminator)}/profile",
        headers=get_auth_headers(caller),
    )
    assert after.json()["presence"] == "offline"


@pytest.mark.integration
async def test_profile_says_online_with_no_guild_open(
    client: AsyncClient, session: AsyncSession
):
    """The guild events socket only exists while a tab sits inside a guild, so
    reading presence from it alone made everyone reading their own profile —
    or anything else outside a guild — look offline. The notification stream
    has no guild in its address and is what answers the question."""
    caller = await create_user(session)
    subject = await create_user(session)

    socket = object()
    await notification_stream.stream.connect(subject.id, socket)
    try:
        response = await client.get(
            f"/api/v1/users/{url_handle(subject.username, subject.discriminator)}/profile",
            headers=get_auth_headers(caller),
        )
    finally:
        await notification_stream.stream.disconnect(socket)

    assert response.status_code == 200
    assert response.json()["presence"] == "online"

    after = await client.get(
        f"/api/v1/users/{url_handle(subject.username, subject.discriminator)}/profile",
        headers=get_auth_headers(caller),
    )
    assert after.json()["presence"] == "offline"


@pytest.mark.integration
async def test_profile_stays_online_while_any_socket_is_open(
    client: AsyncClient, session: AsyncSession
):
    """Two channels feed one roll, so closing one tab does not sign the other
    one out."""
    caller = await create_user(session)
    subject = await create_user(session)
    guild = await create_guild(session)
    await create_guild_membership(session, user=subject, guild=guild)

    bell, events = object(), object()
    await notification_stream.stream.connect(subject.id, bell)
    await realtime_manager.connect(guild.id, [], events, user_id=subject.id)  # type: ignore[arg-type]
    try:
        await realtime_manager.disconnect(events)  # type: ignore[arg-type]
        response = await client.get(
            f"/api/v1/users/{url_handle(subject.username, subject.discriminator)}/profile",
            headers=get_auth_headers(caller),
        )
    finally:
        await notification_stream.stream.disconnect(bell)

    assert response.json()["presence"] == "online"


@pytest.mark.integration
@pytest.mark.parametrize("chosen", ["idle", "busy"])
async def test_profile_shows_what_someone_picked(
    client: AsyncClient, session: AsyncSession, chosen: str
):
    """Each is shown as itself, not flattened to online."""
    caller = await create_user(session)
    subject = await create_user(session)

    socket = object()
    await notification_stream.stream.connect(
        subject.id, socket, chosen_presence=Presence(chosen)
    )
    try:
        response = await client.get(
            f"/api/v1/users/{url_handle(subject.username, subject.discriminator)}/profile",
            headers=get_auth_headers(caller),
        )
    finally:
        await notification_stream.stream.disconnect(socket)

    assert response.json()["presence"] == chosen


@pytest.mark.integration
async def test_profile_shows_offline_for_someone_who_picked_it(
    client: AsyncClient, session: AsyncSession
):
    """Appearing offline holds with a tab open — that is the whole point of it."""
    caller = await create_user(session)
    subject = await create_user(session)

    socket = object()
    await notification_stream.stream.connect(
        subject.id, socket, chosen_presence=Presence.offline
    )
    try:
        response = await client.get(
            f"/api/v1/users/{url_handle(subject.username, subject.discriminator)}/profile",
            headers=get_auth_headers(caller),
        )
    finally:
        await notification_stream.stream.disconnect(socket)

    assert response.json()["presence"] == "offline"


@pytest.mark.integration
async def test_presence_change_reaches_readers_without_a_reconnect(
    client: AsyncClient, session: AsyncSession
):
    """The socket carried the old choice; setting a new one is followed live."""
    caller = await create_user(session)
    subject = await create_user(session)
    profile_url = (
        f"/api/v1/users/{url_handle(subject.username, subject.discriminator)}/profile"
    )

    socket = object()
    await notification_stream.stream.connect(subject.id, socket)
    try:
        assert (await client.get(profile_url, headers=get_auth_headers(caller))).json()[
            "presence"
        ] == "online"

        saved = await client.patch(
            "/api/v1/users/me",
            headers=get_auth_headers(subject),
            json={"presence": "offline"},
        )
        assert saved.status_code == 200
        assert saved.json()["presence"] == "offline"

        assert (await client.get(profile_url, headers=get_auth_headers(caller))).json()[
            "presence"
        ] == "offline"
    finally:
        await notification_stream.stream.disconnect(socket)


@pytest.mark.integration
async def test_presence_outlives_the_socket_that_set_it(
    client: AsyncClient, session: AsyncSession
):
    """The choice is a column, so a new tab appears the way the last one did."""
    caller = await create_user(session)
    subject = await create_user(session)

    saved = await client.patch(
        "/api/v1/users/me",
        headers=get_auth_headers(subject),
        json={"presence": "busy"},
    )
    assert saved.status_code == 200

    await session.refresh(subject)
    socket = object()
    await notification_stream.stream.connect(
        subject.id, socket, chosen_presence=subject.presence
    )
    try:
        response = await client.get(
            f"/api/v1/users/{url_handle(subject.username, subject.discriminator)}/profile",
            headers=get_auth_headers(caller),
        )
    finally:
        await notification_stream.stream.disconnect(socket)

    assert response.json()["presence"] == "busy"


@pytest.mark.integration
async def test_presence_rejects_a_value_that_is_not_one(
    client: AsyncClient, session: AsyncSession
):
    user = await create_user(session)

    response = await client.patch(
        "/api/v1/users/me",
        headers=get_auth_headers(user),
        json={"presence": "invisible"},
    )

    assert response.status_code == 422


@pytest.mark.integration
async def test_profile_requires_a_signed_in_reader(client: AsyncClient):
    response = await client.get("/api/v1/users/nobody0001/profile")

    assert response.status_code == 401


@pytest.mark.integration
async def test_custom_status_round_trips_as_one_object(
    client: AsyncClient, session: AsyncSession
):
    """One column, one write: the emoji and the line are set together."""
    user = await create_user(session)
    headers = get_auth_headers(user)

    response = await client.patch(
        "/api/v1/users/me",
        headers=headers,
        json={"custom_status": {"emoji": "\N{ROCKET}", "text": "  shipping  "}},
    )

    assert response.status_code == 200
    assert response.json()["custom_status"] == {
        "emoji": "\N{ROCKET}",
        "text": "shipping",
    }

    cleared = await client.patch(
        "/api/v1/users/me", headers=headers, json={"custom_status": None}
    )

    assert cleared.status_code == 200
    assert cleared.json()["custom_status"] == {"emoji": None, "text": None}


@pytest.mark.integration
@pytest.mark.parametrize(
    "payload",
    [
        {"custom_status": {"emoji": "not an emoji"}},
        {"custom_status": {"mood": "chipper"}},
        {"profile_decorations": {"banner": "../../etc/passwd"}},
        {"profile_decorations": {"hat": "core.aurora"}},
        {"profile_decorations": {"trophies": ["a", "b", "c", "d", "e", "f", "g"]}},
    ],
)
async def test_profile_writes_reject_a_shape_that_is_not_the_shape(
    client: AsyncClient, session: AsyncSession, payload: dict
):
    """Text where an emoji goes, a key nothing wears, a path where an id goes,
    and more trophies than a profile has room for."""
    user = await create_user(session)

    response = await client.patch(
        "/api/v1/users/me", headers=get_auth_headers(user), json=payload
    )

    assert response.status_code == 422


@pytest.mark.integration
async def test_library_lists_what_ships_with_the_app(
    client: AsyncClient, session: AsyncSession
):
    """A fresh account has the shipped set and nothing else, and none of it
    names a pack — nobody granted it."""
    user = await create_user(session)

    response = await client.get(
        "/api/v1/users/me/decorations", headers=get_auth_headers(user)
    )

    assert response.status_code == 200
    items = response.json()["items"]
    assert {item["id"] for item in items} == set(SHIPPED_DECORATIONS)
    assert all(item["source"] is None for item in items)
    assert {item["kind"] for item in items} == {"banner", "frame", "trophy"}


@pytest.mark.integration
async def test_library_carries_what_a_pack_granted(
    client: AsyncClient, session: AsyncSession
):
    """An acquired decoration joins the shipped set and says where it came
    from, so a picker can group by pack."""
    user = await create_user(session)
    session.add(
        UserDecoration(
            user_id=user.id,
            decoration_id="pack.midnight",
            kind="banner",
            source="studio.midnight-pack",
        )
    )
    await session.commit()

    response = await client.get(
        "/api/v1/users/me/decorations", headers=get_auth_headers(user)
    )

    assert response.status_code == 200
    items = response.json()["items"]
    granted = next(item for item in items if item["id"] == "pack.midnight")
    assert granted == {
        "id": "pack.midnight",
        "kind": "banner",
        # No listing behind this row in this test, so no name to carry.
        "name": None,
        "source": "studio.midnight-pack",
    }
    assert len(items) == len(SHIPPED_DECORATIONS) + 1


@pytest.mark.integration
async def test_library_is_the_readers_own(client: AsyncClient, session: AsyncSession):
    """Somebody else's acquisitions are not in your library."""
    user = await create_user(session)
    other = await create_user(session)
    session.add(
        UserDecoration(user_id=other.id, decoration_id="pack.midnight", kind="banner")
    )
    await session.commit()

    response = await client.get(
        "/api/v1/users/me/decorations", headers=get_auth_headers(user)
    )

    assert response.status_code == 200
    assert "pack.midnight" not in {item["id"] for item in response.json()["items"]}


@pytest.mark.integration
async def test_wearing_a_decoration_requires_having_it(
    client: AsyncClient, session: AsyncSession
):
    """You wear what you have."""
    user = await create_user(session)

    response = await client.patch(
        "/api/v1/users/me",
        headers=get_auth_headers(user),
        json={"profile_decorations": {"banner": "pack.midnight"}},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "USER_DECORATION_NOT_OWNED"


@pytest.mark.integration
async def test_a_decoration_goes_in_the_slot_it_is_for(
    client: AsyncClient, session: AsyncSession
):
    """Having a frame is not having a banner."""
    user = await create_user(session)

    response = await client.patch(
        "/api/v1/users/me",
        headers=get_auth_headers(user),
        json={"profile_decorations": {"banner": "core.gold"}},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "USER_DECORATION_NOT_OWNED"


@pytest.mark.integration
async def test_wearing_what_a_pack_granted(client: AsyncClient, session: AsyncSession):
    """The acquired half of the library is wearable on the same terms as the
    shipped half."""
    user = await create_user(session)
    session.add(
        UserDecoration(
            user_id=user.id,
            decoration_id="pack.midnight",
            kind="banner",
            source="studio.midnight-pack",
        )
    )
    await session.commit()

    response = await client.patch(
        "/api/v1/users/me",
        headers=get_auth_headers(user),
        json={
            "profile_decorations": {
                "banner": "pack.midnight",
                "frame": "core.gold",
                "trophies": ["core.fan", "core.fan"],
            }
        },
    )

    assert response.status_code == 200
    assert response.json()["profile_decorations"] == {
        "banner": "pack.midnight",
        "frame": "core.gold",
        "frame_tint": [],
        # The same trophy twice is a duplicate, not a second trophy.
        "trophies": ["core.fan"],
    }


@pytest.mark.integration
async def test_a_frame_that_takes_a_colour_keeps_the_one_it_was_given(
    client: AsyncClient, session: AsyncSession
):
    """The colours a wearer picks are stored beside the frame they picked them
    for, and a frame that takes one never keeps two."""
    user = await create_user(session)

    response = await client.patch(
        "/api/v1/users/me",
        headers=get_auth_headers(user),
        json={
            "profile_decorations": {
                "frame": "core.split",
                "frame_tint": ["#1B5E32", "#F2C230"],
            }
        },
    )
    assert response.status_code == 200
    assert response.json()["profile_decorations"]["frame_tint"] == [
        "#1b5e32",
        "#f2c230",
    ]

    response = await client.patch(
        "/api/v1/users/me",
        headers=get_auth_headers(user),
        json={
            "profile_decorations": {
                "frame": "core.gold",
                "frame_tint": ["#AA0011", "#223344"],
            }
        },
    )
    assert response.status_code == 200
    assert response.json()["profile_decorations"]["frame_tint"] == ["#aa0011"]


@pytest.mark.integration
async def test_a_frame_that_takes_no_colour_is_stored_without_one(
    client: AsyncClient, session: AsyncSession
):
    """A colour on a frame that cannot take one is state nothing reads and
    nothing clears, so it is not kept."""
    user = await create_user(session)

    response = await client.patch(
        "/api/v1/users/me",
        headers=get_auth_headers(user),
        json={
            "profile_decorations": {"frame": "core.arcane", "frame_tint": ["#AA0011"]}
        },
    )

    assert response.status_code == 200
    assert response.json()["profile_decorations"]["frame_tint"] == []


@pytest.mark.integration
async def test_a_colour_that_is_not_a_colour_is_refused(
    client: AsyncClient, session: AsyncSession
):
    user = await create_user(session)

    response = await client.patch(
        "/api/v1/users/me",
        headers=get_auth_headers(user),
        json={"profile_decorations": {"frame": "core.gold", "frame_tint": ["puce"]}},
    )

    assert response.status_code == 422


@pytest.mark.integration
async def test_profile_is_addressed_by_handle(
    client: AsyncClient, session: AsyncSession
):
    """``jordan1234`` is the handle as one URL segment — the name and the four
    digits it is always written with, run together, because ``#`` never
    survives a URL."""
    caller = await create_user(session)
    subject = await create_user(session, username="jordan", discriminator=1234)

    response = await client.get(
        "/api/v1/users/jordan1234/profile", headers=get_auth_headers(caller)
    )

    assert response.status_code == 200
    assert response.json()["id"] == subject.id
    assert response.json()["username"] == "jordan"
    assert response.json()["discriminator"] == 1234


@pytest.mark.integration
async def test_profile_handle_comes_apart_at_a_fixed_width(
    client: AsyncClient, session: AsyncSession
):
    """A name may itself end in digits. The number is always four wide, which
    is what keeps ``user2`` + ``0007`` from reading as ``user`` + ``20007``."""
    caller = await create_user(session)
    subject = await create_user(session, username="user2", discriminator=7)

    response = await client.get(
        "/api/v1/users/user20007/profile", headers=get_auth_headers(caller)
    )

    assert response.status_code == 200
    assert response.json()["username"] == "user2"
    assert response.json()["discriminator"] == subject.discriminator


@pytest.mark.integration
@pytest.mark.parametrize("handle", ["jordan", "jordan12a4", "ab0001", "jordan1234x"])
async def test_profile_404s_on_something_that_is_not_a_handle(
    client: AsyncClient, session: AsyncSession, handle: str
):
    """No number, a number with a letter in it, too short a name, and a name
    where the number should be."""
    caller = await create_user(session)

    response = await client.get(
        f"/api/v1/users/{handle}/profile", headers=get_auth_headers(caller)
    )

    assert response.status_code == 404


@pytest.mark.integration
async def test_decoration_packs_list_the_store(
    client: AsyncClient, session: AsyncSession
):
    """The shelf is the marketplace catalog: a pack is a listing, named by its
    publisher and identified by the uid a granted row records."""
    user = await create_user(session)
    listing = await create_profile_pack(session, uid="PACKTABTP00001", slug="tt")

    response = await client.get(
        "/api/v1/users/me/decoration-packs", headers=get_auth_headers(user)
    )

    assert response.status_code == 200
    entry = next(
        item for item in response.json()["items"] if item["uid"] == listing.uid
    )
    assert entry["installed"] is False
    assert entry["public_id"] == listing.public_id
    assert entry["name"] == listing.name
    assert entry["publisher"] == listing.publisher
    # A pack is a set you take together: one of each slot.
    assert {content["kind"] for content in entry["contents"]} == {
        "banner",
        "frame",
        "trophy",
    }
    assert all(content["source"] == listing.uid for content in entry["contents"])


@pytest.mark.integration
async def test_the_shipped_packs_are_on_the_shelf(
    client: AsyncClient, session: AsyncSession
):
    """The packs this build ships reach the store the way any listing does —
    through the catalog, seeded from their manifests."""
    user = await create_user(session)
    for manifest in load_builtin_manifests():
        if manifest.get("kind") == "profile_pack":
            await marketplace_catalog.upsert_listing(
                session, manifest, source="builtin"
            )
    await session.commit()

    response = await client.get(
        "/api/v1/users/me/decoration-packs", headers=get_auth_headers(user)
    )

    assert response.status_code == 200
    shipped = {item["public_id"] for item in response.json()["items"]}
    assert {"core.gaming", "core.soundcheck", "core.observatory"} <= shipped


@pytest.mark.integration
async def test_installing_a_pack_puts_it_in_the_library(
    client: AsyncClient, session: AsyncSession
):
    """What the store grants is what the pickers then offer."""
    user = await create_user(session)
    listing = await create_profile_pack(session, uid="PACKTABTP00001", slug="tt")
    headers = get_auth_headers(user)

    install = await client.post(
        f"/api/v1/users/me/decoration-packs/{listing.uid}", headers=headers
    )

    assert install.status_code == 200
    assert install.json()["installed"] is True

    library = await client.get("/api/v1/users/me/decorations", headers=headers)
    owned = {item["id"]: item for item in library.json()["items"]}
    assert owned["tt.trophy"]["kind"] == "trophy"
    # The grant records the listing uid — the one name for this pack anywhere.
    assert owned["tt.trophy"]["source"] == listing.uid

    listed = await client.get("/api/v1/users/me/decoration-packs", headers=headers)
    installed = {item["uid"] for item in listed.json()["items"] if item["installed"]}
    assert installed == {listing.uid}


@pytest.mark.integration
async def test_installing_a_pack_twice_changes_nothing(
    client: AsyncClient, session: AsyncSession
):
    """A second click on a slow connection is not a second copy."""
    user = await create_user(session)
    listing = await create_profile_pack(session, uid="PACKBAND000001", slug="mu")
    headers = get_auth_headers(user)

    for _ in range(2):
        assert (
            await client.post(
                f"/api/v1/users/me/decoration-packs/{listing.uid}", headers=headers
            )
        ).status_code == 200

    library = await client.get("/api/v1/users/me/decorations", headers=headers)
    ids = [item["id"] for item in library.json()["items"]]
    assert ids.count("mu.frame") == 1


@pytest.mark.integration
async def test_a_pack_you_have_is_wearable(client: AsyncClient, session: AsyncSession):
    """The whole point of taking one."""
    user = await create_user(session)
    listing = await create_profile_pack(session, uid="PACKTABTP00001", slug="tt")
    headers = get_auth_headers(user)
    await client.post(
        f"/api/v1/users/me/decoration-packs/{listing.uid}", headers=headers
    )

    response = await client.patch(
        "/api/v1/users/me",
        headers=headers,
        json={
            "profile_decorations": {
                "banner": "tt.banner",
                "frame": "tt.frame",
                "trophies": ["tt.trophy"],
            }
        },
    )

    assert response.status_code == 200
    assert response.json()["profile_decorations"]["trophies"] == ["tt.trophy"]


@pytest.mark.integration
async def test_a_pack_you_do_not_have_is_not_wearable(
    client: AsyncClient, session: AsyncSession
):
    """The store is the only way in."""
    user = await create_user(session)
    await create_profile_pack(session, uid="PACKTABTP00001", slug="tt")

    response = await client.patch(
        "/api/v1/users/me",
        headers=get_auth_headers(user),
        json={"profile_decorations": {"trophies": ["tt.trophy"]}},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "USER_DECORATION_NOT_OWNED"


@pytest.mark.integration
async def test_removing_a_pack_takes_off_what_was_worn(
    client: AsyncClient, session: AsyncSession
):
    """A profile must not go on wearing what the account gave back — the next
    unrelated edit would be refused if it did."""
    user = await create_user(session)
    tabletop = await create_profile_pack(session, uid="PACKTABTP00001", slug="tt")
    music = await create_profile_pack(
        session, uid="PACKBAND000001", public_id="test.music", slug="mu"
    )
    headers = get_auth_headers(user)
    for listing in (tabletop, music):
        await client.post(
            f"/api/v1/users/me/decoration-packs/{listing.uid}", headers=headers
        )
    await client.patch(
        "/api/v1/users/me",
        headers=headers,
        json={
            "profile_decorations": {
                "banner": "tt.banner",
                "frame": "mu.frame",
                "trophies": ["tt.trophy", "mu.trophy"],
            }
        },
    )

    removed = await client.delete(
        f"/api/v1/users/me/decoration-packs/{tabletop.uid}", headers=headers
    )

    assert removed.status_code == 200
    assert removed.json()["installed"] is False

    me = await client.get("/api/v1/users/me", headers=headers)
    worn = me.json()["profile_decorations"]
    # The tabletop pieces came off; the other pack's stayed on.
    assert worn["banner"] is None
    assert worn["frame"] == "mu.frame"
    assert worn["trophies"] == ["mu.trophy"]

    library = await client.get("/api/v1/users/me/decorations", headers=headers)
    assert "tt.trophy" not in {item["id"] for item in library.json()["items"]}


@pytest.mark.integration
async def test_removing_a_pack_leaves_someone_elses_library_alone(
    client: AsyncClient, session: AsyncSession
):
    user = await create_user(session)
    other = await create_user(session)
    listing = await create_profile_pack(session, uid="PACKTABTP00001", slug="tt")
    for who in (user, other):
        await client.post(
            f"/api/v1/users/me/decoration-packs/{listing.uid}",
            headers=get_auth_headers(who),
        )

    await client.delete(
        f"/api/v1/users/me/decoration-packs/{listing.uid}",
        headers=get_auth_headers(user),
    )

    library = await client.get(
        "/api/v1/users/me/decorations", headers=get_auth_headers(other)
    )
    assert "tt.trophy" in {item["id"] for item in library.json()["items"]}


@pytest.mark.integration
async def test_an_unknown_pack_is_not_a_pack(
    client: AsyncClient, session: AsyncSession
):
    user = await create_user(session)

    response = await client.post(
        "/api/v1/users/me/decoration-packs/NSCHPACK000001",
        headers=get_auth_headers(user),
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "USER_DECORATION_PACK_NOT_FOUND"


@pytest.mark.integration
async def test_a_listing_of_another_kind_is_not_a_pack(
    client: AsyncClient, session: AsyncSession
):
    """A uid names a listing; only a profile pack installs to a person."""
    user = await create_user(session)
    dashboard = await create_marketplace_listing(session, uid="DASHBRD0000001")

    response = await client.post(
        f"/api/v1/users/me/decoration-packs/{dashboard.uid}",
        headers=get_auth_headers(user),
    )

    assert response.status_code == 404


@pytest.mark.integration
async def test_installing_a_pack_survives_two_requests_at_once(session: AsyncSession):
    """Two installs that cannot see each other's rows.

    The real race is two requests in flight together, neither's insert visible
    to the other's read. Calling the service twice before anything is flushed
    reproduces exactly that, deterministically: a read-then-insert would have
    both conclude the same row was missing and collide on the primary key.
    """
    user = await create_user(session)
    listing = await create_profile_pack(session, uid="PACKTABTP00001", slug="tt")
    pack = await profile_decorations_service.pack_by_uid(session, listing.uid)

    assert (
        await profile_decorations_service.install_pack(
            session, user_id=user.id, pack=pack
        )
        == []
    )
    # The second install finds every row already there and attributed to this
    # same pack, which is not a conflict.
    assert (
        await profile_decorations_service.install_pack(
            session, user_id=user.id, pack=pack
        )
        == []
    )
    await session.commit()

    held = (
        await session.exec(
            select(UserDecoration).where(UserDecoration.user_id == user.id)
        )
    ).all()
    assert sorted(row.decoration_id for row in held) == sorted(pack.decorations)


@pytest.mark.integration
async def test_giving_a_pack_back_is_all_or_nothing(session: AsyncSession):
    """The library and the profile move together.

    Emptying the library without undressing the profile leaves the account
    wearing what it does not have, and the next unrelated profile edit is then
    refused. Rolling back before the commit must leave *both* untouched — if
    they were two transactions, one of them would already have landed.
    """
    user = await create_user(session)
    # Held before the rollback below, which expires every instance: reading
    # ``user.id`` afterwards would be a lazy refresh in the wrong place.
    user_id = user.id
    listing = await create_profile_pack(session, uid="PACKTABTP00001", slug="tt")
    pack = await profile_decorations_service.pack_by_uid(session, listing.uid)
    await profile_decorations_service.install_pack(session, user_id=user_id, pack=pack)
    user.profile_decorations = {
        "banner": "tt.banner",
        "frame": None,
        "trophies": ["tt.trophy"],
    }
    session.add(user)
    await session.commit()

    await profile_decorations_service.remove_pack(session, user_id=user_id, pack=pack)
    await session.rollback()

    still_held = (
        await session.exec(
            select(UserDecoration).where(UserDecoration.user_id == user_id)
        )
    ).all()
    fresh = (await session.exec(select(User).where(User.id == user_id))).one()
    assert len(still_held) == len(pack.decorations)
    assert fresh.profile_decorations["banner"] == "tt.banner"


@pytest.mark.integration
async def test_giving_a_pack_back_reads_what_is_worn_now(session: AsyncSession):
    """Undressing works from the value in the database, not one read earlier.

    Building a whole replacement from a stale read is how a profile edit that
    lands in between gets overwritten — or how a piece the reader just took off
    comes back. The read happens inside the transaction, under a row lock.
    """
    user = await create_user(session)
    user_id = user.id
    listing = await create_profile_pack(session, uid="PACKTABTP00001", slug="tt")
    music = await create_profile_pack(
        session, uid="PACKBAND000001", public_id="test.music", slug="mu"
    )
    pack = await profile_decorations_service.pack_by_uid(session, listing.uid)
    music_pack = await profile_decorations_service.pack_by_uid(session, music.uid)
    await profile_decorations_service.install_pack(session, user_id=user_id, pack=pack)
    await profile_decorations_service.install_pack(
        session, user_id=user_id, pack=music_pack
    )
    user.profile_decorations = {"banner": "tt.banner", "frame": None, "trophies": []}
    session.add(user)
    await session.commit()

    # Somebody changes their look after that value was last read anywhere.
    await session.exec(
        update(User)
        .where(User.id == user_id)
        .values(
            profile_decorations={
                "banner": "mu.banner",
                "frame": "tt.frame",
                "trophies": ["mu.trophy"],
            }
        )
    )
    await session.commit()

    await profile_decorations_service.remove_pack(session, user_id=user_id, pack=pack)
    await session.commit()

    fresh = (await session.exec(select(User).where(User.id == user_id))).one()
    # The newer choice survived; only the given-back pack's piece came off.
    assert fresh.profile_decorations["banner"] == "mu.banner"
    assert fresh.profile_decorations["frame"] is None
    assert fresh.profile_decorations["trophies"] == ["mu.trophy"]


@pytest.mark.integration
async def test_giving_back_an_older_pack_undresses_what_it_gave(session: AsyncSession):
    """A pack that has published since is not the record of what you were given.

    Install grants what the version of the day lists. If the pack later drops
    a decoration, the account still holds and may still be wearing it — so
    giving the pack back has to take off what *its rows* gave, not what its
    current definition happens to list.
    """
    user = await create_user(session)
    user_id = user.id
    listing = await create_profile_pack(session, uid="PACKTABTP00001", slug="tt")
    pack = await profile_decorations_service.pack_by_uid(session, listing.uid)
    await profile_decorations_service.install_pack(session, user_id=user_id, pack=pack)
    user.profile_decorations = {"banner": "tt.banner", "frame": None, "trophies": []}
    session.add(user)
    await session.commit()

    # The pack publishes again without the banner it had granted.
    thinner = profile_decorations_service.Pack(
        listing=pack.listing, decorations={"tt.frame": "frame", "tt.trophy": "trophy"}
    )
    await profile_decorations_service.remove_pack(
        session, user_id=user_id, pack=thinner
    )
    await session.commit()

    fresh = (await session.exec(select(User).where(User.id == user_id))).one()
    held = (
        await session.exec(
            select(UserDecoration).where(UserDecoration.user_id == user_id)
        )
    ).all()
    assert held == []
    # The banner came off even though the pack no longer lists it.
    assert fresh.profile_decorations["banner"] is None


@pytest.mark.integration
async def test_a_pack_claiming_another_packs_decoration_is_refused(
    client: AsyncClient, session: AsyncSession
):
    """A decoration id names one thing, so a row can only be attributed to one
    pack. The second install says so rather than half-succeeding."""
    user = await create_user(session)
    headers = get_auth_headers(user)
    first = await create_profile_pack(session, uid="PACKTABTP00001", slug="tt")
    # A second pack claiming an id the first already grants.
    squatter = await create_marketplace_listing(
        session,
        uid="PACKSQAT000001",
        public_id="test.squatter",
        kind="profile_pack",
        definition={
            "schema_version": 1,
            "kind": "profile_pack",
            "decorations": [
                {"id": "tt.trophy", "slot": "trophy", "name": "Also a trophy"}
            ],
        },
    )
    await client.post(f"/api/v1/users/me/decoration-packs/{first.uid}", headers=headers)

    response = await client.post(
        f"/api/v1/users/me/decoration-packs/{squatter.uid}", headers=headers
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "USER_DECORATION_ALREADY_GRANTED"

    # And the first pack's grant is untouched, still attributed to it.
    library = await client.get("/api/v1/users/me/decorations", headers=headers)
    owned = {item["id"]: item for item in library.json()["items"]}
    assert owned["tt.trophy"]["source"] == first.uid

    listed = await client.get("/api/v1/users/me/decoration-packs", headers=headers)
    installed = {item["uid"] for item in listed.json()["items"] if item["installed"]}
    assert installed == {first.uid}
