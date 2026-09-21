"""What wiring an app service up writes down.

A registration confers powers on somebody else's code, so every change to one
is a record of which powers and which address moved, and whether the shared
secret moved with them. The secret's value never does.
"""

from __future__ import annotations

import json

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.audit_events import AuditEventType
from app.core.config import settings
from app.core.encryption import SALT_APP_SERVICE_SECRET, encrypt_field
from app.models.platform.app_service_registration import (
    AppServiceRegistration,
    AppServiceStatus,
)
from app.models.platform.user import UserRole
from app.services.marketplace.handshake import HandshakeResult
from app.testing import emitted
from app.testing.factories import create_user, get_auth_headers

pytestmark = [pytest.mark.integration, pytest.mark.auth]

BASE = "/api/v1/app-services/"
SECRET = "shared-secret-value"
APP_URL = "http://127.0.0.1:9100"
PUBLIC_ID = "acme.widgets"


@pytest.fixture(autouse=True)
def _signing_key(monkeypatch):
    monkeypatch.setattr(
        settings, "APP_PLATFORM_SIGNING_PRIVATE_KEY_PEM", "-----BEGIN PRIVATE KEY-----"
    )


@pytest.fixture
def answering_app(monkeypatch):
    """An app that answers the handshake, so the registry can be driven over
    HTTP without a container to talk to."""

    async def _handshake(*, base_url: str, secret: str, transport=None):
        return HandshakeResult(
            public_id=PUBLIC_ID,
            listing_uid=None,
            manifest_hash="0" * 64,
            protocol_version=1,
            manifest={},
        )

    monkeypatch.setattr(
        "app.services.marketplace.registrations.perform_handshake", _handshake
    )


async def _owner(session: AsyncSession) -> tuple[int | None, dict[str, str]]:
    owner = await create_user(session, role=UserRole.owner)
    return owner.id, get_auth_headers(owner)


async def _seed(session: AsyncSession, **overrides) -> AppServiceRegistration:
    row = AppServiceRegistration(
        public_id=overrides.pop("public_id", PUBLIC_ID),
        base_url=overrides.pop("base_url", APP_URL),
        allowed_origins=overrides.pop("allowed_origins", [APP_URL]),
        secret_encrypted=encrypt_field(SECRET, SALT_APP_SERVICE_SECRET),
        status=overrides.pop("status", AppServiceStatus.UNVERIFIED),
        **overrides,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


async def test_registering_an_app_service_names_what_it_confers(
    client: AsyncClient, session: AsyncSession, answering_app, capfd
):
    owner_id, headers = await _owner(session)
    capfd.readouterr()

    created = await client.post(
        BASE,
        headers=headers,
        json={
            "base_url": APP_URL,
            "secret": SECRET,
            "grants": ["delegation"],
            "mandatory": True,
        },
    )
    assert created.status_code == 201, created.text
    registration_id = created.json()["id"]

    rows = emitted(capfd, AuditEventType.APP_SERVICE_CREATED)
    assert [(r["actor_user_id"], r["target"]) for r in rows] == [
        (owner_id, {"type": "app_service_registration", "id": registration_id})
    ]
    detail = rows[0]["detail"]
    assert detail["secret_changed"] is True
    assert {"public_id", "base_url", "grants", "mandatory", "enabled"} <= set(
        detail["changed"]
    )
    assert detail["values"]["mandatory"] == {"from": None, "to": True}
    # The address and the powers list are strings: named, never copied.
    assert "base_url" not in detail["values"]
    assert "grants" not in detail["values"]
    assert SECRET not in json.dumps(rows[0])


async def test_editing_a_registration_records_what_moved_and_the_secret_with_it(
    client: AsyncClient, session: AsyncSession, capfd
):
    owner_id, headers = await _owner(session)
    row = await _seed(session)
    registration_id = row.id
    capfd.readouterr()

    edited = await client.patch(
        f"{BASE}{registration_id}",
        headers=headers,
        json={"enabled": False, "secret": "rotated-secret"},
    )
    assert edited.status_code == 200, edited.text

    rows = emitted(capfd, AuditEventType.APP_SERVICE_UPDATED)
    assert [(r["actor_user_id"], r["target"]["id"]) for r in rows] == [
        (owner_id, registration_id)
    ]
    detail = rows[0]["detail"]
    assert detail["secret_changed"] is True
    assert detail["values"]["enabled"] == {"from": True, "to": False}


async def test_an_edit_that_changes_nothing_records_nothing(
    client: AsyncClient, session: AsyncSession, capfd
):
    _, headers = await _owner(session)
    row = await _seed(session)
    capfd.readouterr()

    same = await client.patch(
        f"{BASE}{row.id}", headers=headers, json={"enabled": True, "mandatory": False}
    )
    assert same.status_code == 200, same.text

    assert emitted(capfd, AuditEventType.APP_SERVICE_UPDATED) == []


async def test_a_refused_request_records_nothing(
    client: AsyncClient, session: AsyncSession, capfd
):
    member = await create_user(session, role=UserRole.member)
    row = await _seed(session)
    capfd.readouterr()

    refused = await client.patch(
        f"{BASE}{row.id}", headers=get_auth_headers(member), json={"enabled": False}
    )
    assert refused.status_code == 403

    assert emitted(capfd, AuditEventType.APP_SERVICE_UPDATED) == []


async def test_removing_a_registration_is_recorded(
    client: AsyncClient, session: AsyncSession, capfd
):
    owner_id, headers = await _owner(session)
    row = await _seed(session)
    registration_id = row.id
    capfd.readouterr()

    gone = await client.delete(f"{BASE}{registration_id}", headers=headers)
    assert gone.status_code == 204, gone.text

    rows = emitted(capfd, AuditEventType.APP_SERVICE_DELETED)
    assert [(r["actor_user_id"], r["target"]) for r in rows] == [
        (owner_id, {"type": "app_service_registration", "id": registration_id})
    ]


async def test_a_verification_records_the_status_it_ended_on(
    client: AsyncClient, session: AsyncSession, answering_app, capfd
):
    owner_id, headers = await _owner(session)
    row = await _seed(session)
    registration_id = row.id
    capfd.readouterr()

    verified = await client.post(
        f"{BASE}{registration_id}/verify", headers=headers, json={}
    )
    assert verified.status_code == 200, verified.text

    rows = emitted(capfd, AuditEventType.APP_SERVICE_VERIFIED)
    assert [(r["actor_user_id"], r["target"]["id"]) for r in rows] == [
        (owner_id, registration_id)
    ]
    assert rows[0]["detail"] == {
        "status": AppServiceStatus.OK,
        "protocol_version": 1,
    }
