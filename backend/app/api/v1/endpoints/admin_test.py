"""Integration tests for platform-admin endpoints at /api/v1/admin."""

import csv
import io

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.user import UserRole

from app.testing.factories import (
    create_user,
    get_auth_headers,
)


def _parse_csv(body: bytes) -> tuple[list[str], list[list[str]]]:
    """Strip the UTF-8 BOM and parse the CSV body into (headers, rows)."""
    text = body.decode("utf-8")
    if text.startswith("\ufeff"):
        text = text[1:]
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    return rows[0], rows[1:]


@pytest.mark.integration
async def test_export_platform_users_csv_as_admin(client: AsyncClient, session: AsyncSession):
    """Platform admins can export all users as CSV."""
    admin = await create_user(session, email="admin@example.com", role=UserRole.admin)
    await create_user(session, email="user1@example.com", full_name="One")
    await create_user(session, email="user2@example.com", full_name="Two")

    headers = get_auth_headers(admin)
    response = await client.get("/api/v1/admin/users/export.csv", headers=headers)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "attachment; filename=" in response.headers["content-disposition"]
    assert "platform-users-" in response.headers["content-disposition"]
    assert response.content.startswith("\ufeff".encode("utf-8"))

    header_row, data_rows = _parse_csv(response.content)
    assert header_row == [
        "user_id",
        "email",
        "full_name",
        "platform_role",
        "status",
        "email_verified",
        "created_at",
        "updated_at",
        "timezone",
        "locale",
        "initiative_roles",
    ]
    emails = {row[1] for row in data_rows}
    assert "admin@example.com" in emails
    assert "user1@example.com" in emails
    assert "user2@example.com" in emails


@pytest.mark.integration
async def test_export_platform_users_csv_forbidden_for_regular_user(
    client: AsyncClient, session: AsyncSession
):
    """A non-admin user cannot hit the platform export endpoint."""
    user = await create_user(session, email="user@example.com")
    headers = get_auth_headers(user)

    response = await client.get("/api/v1/admin/users/export.csv", headers=headers)
    assert response.status_code == 403


@pytest.mark.integration
async def test_export_platform_users_csv_single_user_id(
    client: AsyncClient, session: AsyncSession
):
    """Passing one user_id returns exactly that row with a per-user filename."""
    admin = await create_user(session, email="admin@example.com", role=UserRole.admin)
    target = await create_user(session, email="target@example.com")

    headers = get_auth_headers(admin)
    response = await client.get(
        f"/api/v1/admin/users/export.csv?user_id={target.id}", headers=headers
    )

    assert response.status_code == 200
    assert f"user-{target.id}-" in response.headers["content-disposition"]
    _, data_rows = _parse_csv(response.content)
    assert len(data_rows) == 1
    assert data_rows[0][0] == str(target.id)


@pytest.mark.integration
async def test_export_platform_users_csv_multi_user_id(
    client: AsyncClient, session: AsyncSession
):
    """Two user_id values return two rows with a bulk-style filename."""
    admin = await create_user(session, email="admin@example.com", role=UserRole.admin)
    a = await create_user(session, email="a@example.com")
    b = await create_user(session, email="b@example.com")

    headers = get_auth_headers(admin)
    response = await client.get(
        f"/api/v1/admin/users/export.csv?user_id={a.id}&user_id={b.id}", headers=headers
    )

    assert response.status_code == 200
    assert "platform-users-" in response.headers["content-disposition"]
    _, data_rows = _parse_csv(response.content)
    emails = {row[1] for row in data_rows}
    assert emails == {"a@example.com", "b@example.com"}


@pytest.mark.integration
async def test_export_platform_users_csv_no_matches_returns_404(
    client: AsyncClient, session: AsyncSession
):
    """All requested ids missing -> 404."""
    admin = await create_user(session, email="admin@example.com", role=UserRole.admin)

    headers = get_auth_headers(admin)
    response = await client.get(
        "/api/v1/admin/users/export.csv?user_id=99998&user_id=99999", headers=headers
    )

    assert response.status_code == 404


@pytest.mark.integration
async def test_anonymized_user_cannot_be_deactivated_or_re_anonymized(
    client: AsyncClient, session: AsyncSession
):
    """Once a user is anonymized, the only valid follow-up is hard delete.

    Regression: previously ``deactivate`` on an anonymized row flipped
    its status back to ``deactivated``, which then satisfied the
    reactivate endpoint's anonymized check and let an admin resurrect a
    PII-stripped husk as an active loginable account.
    """
    from app.services import users as users_service

    admin = await create_user(session, email="admin@example.com", role=UserRole.admin)
    target = await create_user(session, email="target@example.com")
    await users_service.soft_delete_user(session, target.id)

    headers = get_auth_headers(admin)

    # Reject deactivate
    response = await client.request(
        "DELETE",
        f"/api/v1/admin/users/{target.id}",
        headers=headers,
        json={"action": "deactivate"},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "ADMIN_ALREADY_ANONYMIZED"

    # Reject another soft_delete
    response = await client.request(
        "DELETE",
        f"/api/v1/admin/users/{target.id}",
        headers=headers,
        json={"action": "soft_delete"},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "ADMIN_ALREADY_ANONYMIZED"

    # Hard delete still allowed
    response = await client.request(
        "DELETE",
        f"/api/v1/admin/users/{target.id}",
        headers=headers,
        json={"action": "hard_delete"},
    )
    assert response.status_code == 200


@pytest.mark.integration
async def test_admin_delete_rejects_surplus_project_transfers(
    client: AsyncClient, session: AsyncSession
):
    """A project_transfers entry that doesn't belong to the target user
    must be rejected, not silently applied. Without this guard an admin
    could deliberately or accidentally transfer ownership of unrelated
    projects via the same payload.
    """
    from app.testing.factories import (
        create_initiative,
        create_initiative_member,
        create_project,
    )
    from app.models.guild import GuildRole

    admin = await create_user(session, email="admin@example.com", role=UserRole.admin)
    target = await create_user(session, email="target@example.com")
    bystander = await create_user(session, email="bystander@example.com")

    # Build a guild + initiative with admin (PM), target, and bystander
    # all members; one project owned by target, one by bystander.
    from app.testing.factories import create_guild as _create_guild
    from app.testing.factories import create_guild_membership as _create_gm

    guild = await _create_guild(session, creator=admin)
    await _create_gm(session, user=admin, guild=guild, role=GuildRole.admin)
    await _create_gm(session, user=target, guild=guild, role=GuildRole.member)
    await _create_gm(session, user=bystander, guild=guild, role=GuildRole.member)
    initiative = await create_initiative(session, guild=guild, creator=admin)
    await create_initiative_member(session, initiative=initiative, user=target)
    await create_initiative_member(session, initiative=initiative, user=bystander)

    target_project = await create_project(session, initiative=initiative, owner=target)
    bystander_project = await create_project(
        session, initiative=initiative, owner=bystander
    )

    headers = get_auth_headers(admin)
    response = await client.request(
        "DELETE",
        f"/api/v1/admin/users/{target.id}",
        headers=headers,
        json={
            "action": "soft_delete",
            "project_transfers": {
                str(target_project.id): admin.id,
                # Surplus: bystander_project doesn't belong to target.
                str(bystander_project.id): admin.id,
            },
        },
    )
    assert response.status_code == 400
    assert "not owned by user" in response.json()["detail"]

    # Bystander's project ownership is unchanged.
    from sqlmodel import select as _select
    from app.models.project import Project

    refreshed = (
        await session.exec(_select(Project).where(Project.id == bystander_project.id))
    ).one()
    assert refreshed.owner_id == bystander.id


@pytest.mark.integration
async def test_platform_role_change_rejected_on_inactive_users(
    client: AsyncClient, session: AsyncSession
):
    """Platform role mutations on deactivated or anonymized users are
    refused with ``ADMIN_CANNOT_CHANGE_ROLE_INACTIVE``. The role on the
    target row is unchanged.
    """
    from sqlmodel import select
    from app.models.user import User
    from app.services import users as users_service

    admin = await create_user(session, email="admin@example.com", role=UserRole.admin)
    headers = get_auth_headers(admin)

    # 1. Deactivated regular user — promote attempt rejected.
    deact_member = await create_user(session, email="deact-member@example.com")
    await users_service.deactivate_user(session, deact_member.id)
    response = await client.patch(
        f"/api/v1/admin/users/{deact_member.id}/platform-role",
        headers=headers,
        json={"role": "admin"},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "ADMIN_CANNOT_CHANGE_ROLE_INACTIVE"
    refreshed = (
        await session.exec(select(User).where(User.id == deact_member.id))
    ).one()
    assert refreshed.role == UserRole.member

    # 2. Deactivated admin user — demote attempt rejected.
    second_admin = await create_user(session, email="second-admin@example.com", role=UserRole.admin)
    await users_service.deactivate_user(session, second_admin.id)
    response = await client.patch(
        f"/api/v1/admin/users/{second_admin.id}/platform-role",
        headers=headers,
        json={"role": "member"},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "ADMIN_CANNOT_CHANGE_ROLE_INACTIVE"
    refreshed = (
        await session.exec(select(User).where(User.id == second_admin.id))
    ).one()
    assert refreshed.role == UserRole.admin

    # 3. Anonymized user — both directions rejected.
    anon = await create_user(session, email="anon-target@example.com")
    await users_service.soft_delete_user(session, anon.id)

    # 3a. Promote attempt (member → admin).
    response = await client.patch(
        f"/api/v1/admin/users/{anon.id}/platform-role",
        headers=headers,
        json={"role": "admin"},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "ADMIN_CANNOT_CHANGE_ROLE_INACTIVE"
    refreshed = (
        await session.exec(select(User).where(User.id == anon.id))
    ).one()
    assert refreshed.role == UserRole.member

    # 3b. Demote attempt (admin → member). soft_delete_user already
    # demoted the row to member, so flip role back to admin directly
    # in the DB (bypassing the endpoint, which would refuse) to set up
    # the demote scenario.
    refreshed.role = UserRole.admin
    session.add(refreshed)
    await session.commit()
    response = await client.patch(
        f"/api/v1/admin/users/{anon.id}/platform-role",
        headers=headers,
        json={"role": "member"},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "ADMIN_CANNOT_CHANGE_ROLE_INACTIVE"
    refreshed = (
        await session.exec(select(User).where(User.id == anon.id))
    ).one()
    assert refreshed.role == UserRole.admin


@pytest.mark.integration
async def test_demote_admin_uses_for_update_path_without_postgres_error(
    client: AsyncClient, session: AsyncSession
):
    """Regression: ``is_last_platform_admin(..., for_update=True)`` ran
    a ``SELECT COUNT(...) FOR UPDATE``, which PostgreSQL rejects with
    "FOR UPDATE is not allowed with aggregate functions". Every valid
    demote of an active admin would crash with an unhandled
    ProgrammingError. The endpoint must complete normally and the
    target's role must end up demoted.
    """
    from sqlmodel import select
    from app.models.user import User

    deleter = await create_user(session, email="deleter@example.com", role=UserRole.admin)
    target = await create_user(session, email="demoteme@example.com", role=UserRole.admin)

    response = await client.patch(
        f"/api/v1/admin/users/{target.id}/platform-role",
        headers=get_auth_headers(deleter),
        json={"role": "member"},
    )
    assert response.status_code == 200, response.text

    refreshed = (await session.exec(select(User).where(User.id == target.id))).one()
    assert refreshed.role == UserRole.member
