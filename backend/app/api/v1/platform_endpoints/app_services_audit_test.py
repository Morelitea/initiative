"""What wiring an app service up writes down.

A registration confers powers on somebody else's code, so every change to one
is a record of which powers and which address moved. So is every change to a
publisher, whose switch reaches every app under it.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.audit_events import AuditEventType
from app.core.config import settings
from app.models.platform.app_service_registration import AppServiceRegistration
from app.models.platform.user import UserRole
from app.testing import emitted
from app.testing.factories import (
    create_app_service_registration,
    create_user,
    get_auth_headers,
)

pytestmark = [pytest.mark.integration, pytest.mark.auth]

BASE = "/api/v1/app-services/"
PUBLISHERS = "/api/v1/app-publishers/"
APP_URL = "http://127.0.0.1:9100"
PUBLIC_ID = "acme.widgets"
LISTING_UID = "K7M2QX8N4TVB9C"


@pytest.fixture(autouse=True)
def _signing_key(monkeypatch):
    monkeypatch.setattr(
        settings, "APP_PLATFORM_SIGNING_PRIVATE_KEY_PEM", "-----BEGIN PRIVATE KEY-----"
    )


async def _owner(session: AsyncSession) -> tuple[int | None, dict[str, str]]:
    owner = await create_user(session, role=UserRole.owner)
    return owner.id, get_auth_headers(owner)


async def _seed(session: AsyncSession, **overrides) -> AppServiceRegistration:
    return await create_app_service_registration(
        session,
        public_id=overrides.pop("public_id", PUBLIC_ID),
        base_url=overrides.pop("base_url", APP_URL),
        allowed_origins=overrides.pop("allowed_origins", [APP_URL]),
        listing_uid=overrides.pop("listing_uid", LISTING_UID),
        **overrides,
    )


async def test_registering_an_app_service_names_what_it_confers(
    client: AsyncClient, session: AsyncSession, capfd
):
    owner_id, headers = await _owner(session)
    capfd.readouterr()

    created = await client.post(
        BASE,
        headers=headers,
        json={
            "public_id": PUBLIC_ID,
            "listing_uid": LISTING_UID,
            "base_url": APP_URL,
            "mandatory": True,
        },
    )
    assert created.status_code == 201, created.text
    registration_id = created.json()["id"]

    envelopes = emitted(capfd)
    rows = [
        e for e in envelopes if e["event_type"] == AuditEventType.APP_SERVICE_CREATED
    ]
    assert [(r["actor_user_id"], r["target"]) for r in rows] == [
        (owner_id, {"type": "app_service_registration", "id": registration_id})
    ]
    detail = rows[0]["detail"]
    assert {
        "public_id",
        "listing_uid",
        "publisher_id",
        "base_url",
        "mandatory",
        "enabled",
    } <= set(detail["changed"])
    assert detail["values"]["mandatory"] == {"from": None, "to": True}
    # The address is a string: named, never copied.
    assert "base_url" not in detail["values"]
    # The acme prefix was new here, so its publisher was added with it.
    publishers = [
        e for e in envelopes if e["event_type"] == AuditEventType.APP_PUBLISHER_CREATED
    ]
    assert [r["detail"]["via"] for r in publishers] == ["registration"]


async def test_editing_a_registration_records_what_moved(
    client: AsyncClient, session: AsyncSession, capfd
):
    owner_id, headers = await _owner(session)
    row = await _seed(session)
    registration_id = row.id
    capfd.readouterr()

    edited = await client.patch(
        f"{BASE}{registration_id}",
        headers=headers,
        json={"enabled": False, "listing_uid": "ABCDEFGHJKMNPQ"},
    )
    assert edited.status_code == 200, edited.text

    rows = emitted(capfd, AuditEventType.APP_SERVICE_UPDATED)
    assert [(r["actor_user_id"], r["target"]["id"]) for r in rows] == [
        (owner_id, registration_id)
    ]
    detail = rows[0]["detail"]
    assert {"enabled", "listing_uid"} <= set(detail["changed"])
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


async def test_a_publisher_is_recorded_when_added_and_switched(
    client: AsyncClient, session: AsyncSession, capfd
):
    owner_id, headers = await _owner(session)
    capfd.readouterr()

    created = await client.post(
        PUBLISHERS, headers=headers, json={"prefix": "local", "display_name": "Local"}
    )
    assert created.status_code == 201, created.text
    publisher_id = created.json()["id"]
    switched = await client.patch(
        f"{PUBLISHERS}{publisher_id}", headers=headers, json={"enabled": False}
    )
    assert switched.status_code == 200, switched.text

    envelopes = emitted(capfd)
    added = [
        e for e in envelopes if e["event_type"] == AuditEventType.APP_PUBLISHER_CREATED
    ]
    assert [(r["actor_user_id"], r["target"]) for r in added] == [
        (owner_id, {"type": "app_publisher", "id": publisher_id})
    ]
    updated = [
        e for e in envelopes if e["event_type"] == AuditEventType.APP_PUBLISHER_UPDATED
    ]
    assert [r["detail"]["values"]["enabled"] for r in updated] == [
        {"from": True, "to": False}
    ]
