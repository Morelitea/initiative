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
