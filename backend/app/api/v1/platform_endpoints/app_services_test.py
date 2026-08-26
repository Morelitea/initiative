"""Endpoint tests for the app service registry.

Two things this surface must never get wrong, and both are asserted here: only
the owner tier reaches it, and the shared secret is echoed as a boolean rather
than a value. The network-bound handshake paths are covered at the service
layer (``app/services/marketplace/registrations_test.py``); every case here
either stops before the handshake or operates on a seeded row.
"""

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.core.encryption import SALT_APP_SERVICE_SECRET, encrypt_field
from app.core.messages import AppServiceMessages, AuthMessages
from app.models.platform.app_service_registration import (
    AppServiceRegistration,
    AppServiceStatus,
)
from app.models.platform.user import UserRole
from app.testing.factories import create_user, get_auth_headers

pytestmark = [pytest.mark.integration, pytest.mark.auth]

BASE = "/api/v1/app-services/"
SECRET = "shared-secret-value"
APP_URL = "http://127.0.0.1:9100"


@pytest.fixture(autouse=True)
def _signing_key(monkeypatch):
    monkeypatch.setattr(
        settings, "APP_PLATFORM_SIGNING_PRIVATE_KEY_PEM", "-----BEGIN PRIVATE KEY-----"
    )


async def _owner_headers(session: AsyncSession) -> dict[str, str]:
    owner = await create_user(session, role=UserRole.owner)
    return get_auth_headers(owner)


async def _seed(session: AsyncSession, **overrides) -> AppServiceRegistration:
    row = AppServiceRegistration(
        public_id=overrides.pop("public_id", "acme.widgets"),
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


# --- capability gating -------------------------------------------------------


@pytest.mark.parametrize(
    "role", [UserRole.member, UserRole.support, UserRole.moderator, UserRole.operator]
)
async def test_non_owner_tiers_are_refused(
    client: AsyncClient, session: AsyncSession, role: UserRole
):
    """``apps.manage`` is owner-only: wiring an app service is deployment
    configuration, so no lower tier reaches any verb."""
    user = await create_user(session, role=role)
    headers = get_auth_headers(user)
    row = await _seed(session)

    assert (await client.get(BASE, headers=headers)).status_code == 403
    create = await client.post(
        BASE, headers=headers, json={"base_url": APP_URL, "secret": SECRET}
    )
    assert create.status_code == 403
    assert create.json()["detail"] == AuthMessages.INSUFFICIENT_PRIVILEGES
    assert (await client.get(f"{BASE}{row.id}", headers=headers)).status_code == 403
    assert (
        await client.patch(f"{BASE}{row.id}", headers=headers, json={"enabled": False})
    ).status_code == 403
    assert (
        await client.post(f"{BASE}{row.id}/verify", headers=headers, json={})
    ).status_code == 403
    assert (await client.delete(f"{BASE}{row.id}", headers=headers)).status_code == 403


async def test_anonymous_is_refused(client: AsyncClient):
    assert (await client.get(BASE)).status_code == 401


# --- the secret never leaves --------------------------------------------------


async def test_owner_lists_registrations_without_the_secret(
    client: AsyncClient, session: AsyncSession
):
    headers = await _owner_headers(session)
    await _seed(session, grants=["delegation"], mandatory=True)

    response = await client.get(BASE, headers=headers)

    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body) == 1
    entry = body[0]
    assert entry["public_id"] == "acme.widgets"
    assert entry["has_secret"] is True
    assert entry["grants"] == ["delegation"]
    assert entry["mandatory"] is True
    assert entry["status"] == AppServiceStatus.UNVERIFIED
    # Neither the value nor its ciphertext appears anywhere in the payload.
    assert "secret" not in entry
    assert "secret_encrypted" not in entry
    assert SECRET not in response.text


async def test_read_and_patch_never_echo_the_secret(
    client: AsyncClient, session: AsyncSession
):
    headers = await _owner_headers(session)
    row = await _seed(session)

    read = await client.get(f"{BASE}{row.id}", headers=headers)
    assert read.status_code == 200
    assert SECRET not in read.text
    assert read.json()["has_secret"] is True

    rotated = await client.patch(
        f"{BASE}{row.id}", headers=headers, json={"secret": "a-rotated-secret"}
    )
    assert rotated.status_code == 200, rotated.text
    assert "a-rotated-secret" not in rotated.text
    assert rotated.json()["has_secret"] is True
    # Rotating discards what the previous target's handshake established.
    assert rotated.json()["status"] == AppServiceStatus.UNVERIFIED


async def test_registration_without_a_secret_reports_it(
    client: AsyncClient, session: AsyncSession
):
    headers = await _owner_headers(session)
    row = await _seed(session)
    row.secret_encrypted = None
    session.add(row)
    await session.commit()

    read = await client.get(f"{BASE}{row.id}", headers=headers)
    assert read.json()["has_secret"] is False

    verify = await client.post(f"{BASE}{row.id}/verify", headers=headers, json={})
    assert verify.status_code == 409
    assert verify.json()["detail"] == AppServiceMessages.SECRET_REQUIRED


# --- operator-conferred fields ------------------------------------------------


async def test_patch_sets_the_operator_only_fields(
    client: AsyncClient, session: AsyncSession
):
    headers = await _owner_headers(session)
    row = await _seed(session)

    response = await client.patch(
        f"{BASE}{row.id}",
        headers=headers,
        json={"grants": ["delegation"], "mandatory": True, "enabled": False},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["grants"] == ["delegation"]
    assert body["mandatory"] is True
    assert body["enabled"] is False


async def test_the_browser_address_round_trips_and_clears(
    client: AsyncClient, session: AsyncSession
):
    headers = await _owner_headers(session)
    row = await _seed(session)

    set_it = await client.patch(
        f"{BASE}{row.id}",
        headers=headers,
        json={"embed_origin": "https://app.example.com"},
    )
    assert set_it.status_code == 200, set_it.text
    assert set_it.json()["embed_origin"] == "https://app.example.com"

    cleared = await client.patch(
        f"{BASE}{row.id}", headers=headers, json={"embed_origin": ""}
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["embed_origin"] is None


@pytest.mark.parametrize(
    ("case", "body", "detail"),
    [
        # A power no code resolves would read in the admin UI as something this
        # deployment had conferred.
        (
            "a grant outside the vocabulary",
            {"base_url": APP_URL, "secret": SECRET, "grants": ["superuser"]},
            AppServiceMessages.UNKNOWN_GRANT,
        ),
        (
            "a malformed base url",
            {"base_url": "ftp://app.example.com", "secret": "s"},
            AppServiceMessages.INVALID_BASE_URL,
        ),
        # Its own code, so an operator is told which of the two addresses the
        # registry would not take.
        (
            "a malformed embed origin",
            {
                "base_url": APP_URL,
                "secret": SECRET,
                "embed_origin": "ftp://app.example.com",
            },
            AppServiceMessages.INVALID_EMBED_ORIGIN,
        ),
        (
            "an origin carrying a path",
            {
                "base_url": APP_URL,
                "secret": SECRET,
                "allowed_origins": ["https://app.example.com/embed"],
            },
            AppServiceMessages.INVALID_ORIGIN,
        ),
    ],
    ids=lambda v: v if isinstance(v, str) and " " in v else "",
)
async def test_create_refuses_a_registration_it_cannot_store(
    client: AsyncClient, session: AsyncSession, case: str, body: dict, detail: str
):
    """Each rejection names the field the operator has to fix."""
    headers = await _owner_headers(session)

    response = await client.post(BASE, headers=headers, json=body)

    assert response.status_code == 400, response.text
    assert response.json()["detail"] == detail


# --- fail-closed without the platform keypair ---------------------------------


async def test_create_fails_closed_without_a_signing_key(
    client: AsyncClient, session: AsyncSession, monkeypatch
):
    """The app-platform keypair is required and has no fallback, so the request
    is refused with a code an operator can act on."""
    monkeypatch.setattr(settings, "APP_PLATFORM_SIGNING_PRIVATE_KEY_PEM", None)
    headers = await _owner_headers(session)

    response = await client.post(
        BASE, headers=headers, json={"base_url": APP_URL, "secret": SECRET}
    )

    assert response.status_code == 503
    assert response.json()["detail"] == AppServiceMessages.SIGNING_NOT_CONFIGURED


# --- delete -------------------------------------------------------------------


async def test_owner_deletes_a_registration(client: AsyncClient, session: AsyncSession):
    headers = await _owner_headers(session)
    row = await _seed(session)

    assert (await client.delete(f"{BASE}{row.id}", headers=headers)).status_code == 204
    assert (await client.get(f"{BASE}{row.id}", headers=headers)).status_code == 404


async def test_missing_registration_is_a_404(
    client: AsyncClient, session: AsyncSession
):
    headers = await _owner_headers(session)

    response = await client.get(f"{BASE}999999", headers=headers)

    assert response.status_code == 404
    assert response.json()["detail"] == AppServiceMessages.NOT_FOUND
