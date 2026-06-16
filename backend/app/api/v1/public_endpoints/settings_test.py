"""Tests for the settings endpoints.

Currently focused on the SMTP test-email error path (pentest SEC-16): a failed
delivery must return a generic machine-readable code, never the raw SMTP
exception (which can carry the mail host, port, or server banner).
"""

from __future__ import annotations

import logging

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.user import UserRole
from app.services import email as email_service
from app.testing import create_user, get_auth_headers


@pytest.mark.integration
async def test_email_test_runtime_error_returns_generic_code(
    client: AsyncClient,
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = await create_user(
        session, email="owner-smtp@example.com", role=UserRole.owner
    )

    sensitive = "SMTPConnectError to smtp.internal.example.com:587 (banner leak)"

    async def _boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError(sensitive)

    monkeypatch.setattr(email_service, "send_test_email", _boom)

    resp = await client.post(
        "/api/v1/settings/email/test",
        json={"recipient": "dest@example.com"},
        headers=get_auth_headers(owner),
    )

    assert resp.status_code == 502
    # The client gets only the generic machine-readable code...
    assert resp.json()["detail"] == "SETTINGS_EMAIL_SEND_FAILED"
    # ...and never the raw SMTP host / banner.
    assert sensitive not in resp.text
    assert "smtp.internal.example.com" not in resp.text


@pytest.mark.integration
async def test_email_test_runtime_error_logs_details_server_side(
    client: AsyncClient,
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    owner = await create_user(
        session, email="owner-smtp-log@example.com", role=UserRole.owner
    )

    sensitive = "535 auth failed for relay user at mail.corp.example.net"

    async def _boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError(sensitive)

    monkeypatch.setattr(email_service, "send_test_email", _boom)

    with caplog.at_level(
        logging.WARNING, logger="app.api.v1.public_endpoints.settings"
    ):
        resp = await client.post(
            "/api/v1/settings/email/test",
            json={"recipient": "dest@example.com"},
            headers=get_auth_headers(owner),
        )

    assert resp.status_code == 502
    # The real cause is preserved for the operator in the server logs only.
    assert sensitive in caplog.text
