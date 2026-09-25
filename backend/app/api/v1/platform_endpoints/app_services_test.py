"""Endpoint tests for the app service registry and its publishers.

Only the owner tier reaches this surface; a registration is what the operator
states about an app, and is shown whole, since none of it is secret.
"""

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.core.messages import AppServiceMessages, AuthMessages
from app.models.platform.app_service_registration import AppServiceRegistration
from app.models.platform.user import UserRole
from app.testing.factories import (
    create_app_service_registration,
    create_marketplace_listing,
    create_user,
    get_auth_headers,
)


BASE = "/api/v1/app-services/"
PUBLISHERS = "/api/v1/app-publishers/"
APP_URL = "http://127.0.0.1:9100"
LISTING_UID = "K7M2QX8N4TVB9C"
NEW = {"public_id": "acme.widgets", "listing_uid": LISTING_UID, "base_url": APP_URL}


@pytest.fixture(autouse=True)
def _signing_key(monkeypatch):
    monkeypatch.setattr(
        settings, "APP_PLATFORM_SIGNING_PRIVATE_KEY_PEM", "-----BEGIN PRIVATE KEY-----"
    )


async def _owner_headers(session: AsyncSession) -> dict[str, str]:
    owner = await create_user(session, role=UserRole.owner)
    return get_auth_headers(owner)


async def _seed(session: AsyncSession, **overrides) -> AppServiceRegistration:
    return await create_app_service_registration(
        session,
        public_id=overrides.pop("public_id", "acme.widgets"),
        base_url=overrides.pop("base_url", APP_URL),
        allowed_origins=overrides.pop("allowed_origins", [APP_URL]),
        listing_uid=overrides.pop("listing_uid", LISTING_UID),
        **overrides,
    )


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
    create = await client.post(BASE, headers=headers, json=NEW)
    assert create.status_code == 403
    assert create.json()["detail"] == AuthMessages.INSUFFICIENT_PRIVILEGES
    assert (await client.get(f"{BASE}{row.id}", headers=headers)).status_code == 403
    assert (
        await client.patch(f"{BASE}{row.id}", headers=headers, json={"enabled": False})
    ).status_code == 403
    assert (await client.delete(f"{BASE}{row.id}", headers=headers)).status_code == 403

    assert (await client.get(PUBLISHERS, headers=headers)).status_code == 403
    assert (
        await client.post(
            PUBLISHERS, headers=headers, json={"prefix": "x", "display_name": "X"}
        )
    ).status_code == 403
    assert (
        await client.patch(
            f"{PUBLISHERS}{row.publisher_id}", headers=headers, json={"enabled": False}
        )
    ).status_code == 403


async def test_anonymous_is_refused(client: AsyncClient):
    assert (await client.get(BASE)).status_code == 401


# --- what a registration is ---------------------------------------------------


async def test_owner_creates_a_registration_as_stated(
    client: AsyncClient, session: AsyncSession
):
    headers = await _owner_headers(session)

    response = await client.post(BASE, headers=headers, json=NEW)

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["public_id"] == "acme.widgets"
    assert body["listing_uid"] == LISTING_UID
    assert body["publisher_prefix"] == "acme"
    assert body["publisher_enabled"] is True
    # No key set yet, so it is not live.
    assert body["live"] is False
    for gone in ("status", "has_secret", "manifest_hash", "last_verified_at"):
        assert gone not in body


async def test_owner_lists_registrations_with_their_publisher(
    client: AsyncClient, session: AsyncSession
):
    headers = await _owner_headers(session)
    await _seed(session, mandatory=True)

    response = await client.get(BASE, headers=headers)

    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body) == 1
    entry = body[0]
    assert entry["public_id"] == "acme.widgets"
    assert "grants" not in entry
    assert entry["mandatory"] is True
    assert entry["publisher_prefix"] == "acme"
    assert entry["live"] is True
    assert entry["jwks"]["keys"]


async def test_create_needs_a_listing(client: AsyncClient, session: AsyncSession):
    headers = await _owner_headers(session)

    response = await client.post(
        BASE, headers=headers, json={**NEW, "listing_uid": "nope"}
    )

    assert response.status_code == 400, response.text
    assert response.json()["detail"] == AppServiceMessages.INVALID_LISTING_UID


async def test_the_key_set_address_round_trips(
    client: AsyncClient, session: AsyncSession
):
    headers = await _owner_headers(session)
    row = await _seed(session, base_url="https://app.example.com", jwks={})

    set_it = await client.patch(
        f"{BASE}{row.id}",
        headers=headers,
        json={"jwks_uri": "https://app.example.com/jwks.json", "jwks": {}},
    )
    assert set_it.status_code == 200, set_it.text
    assert set_it.json()["jwks_uri"] == "https://app.example.com/jwks.json"
    assert set_it.json()["jwks"] is None
    assert set_it.json()["live"] is True

    elsewhere = await client.patch(
        f"{BASE}{row.id}",
        headers=headers,
        json={"jwks_uri": "https://keys.example.net/jwks.json"},
    )
    assert elsewhere.status_code == 400
    assert elsewhere.json()["detail"] == AppServiceMessages.INVALID_JWKS_URI


# --- operator-conferred fields ------------------------------------------------


async def test_patch_sets_the_operator_only_fields(
    client: AsyncClient, session: AsyncSession
):
    headers = await _owner_headers(session)
    row = await _seed(session)

    response = await client.patch(
        f"{BASE}{row.id}",
        headers=headers,
        json={"mandatory": True, "enabled": False},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["mandatory"] is True
    assert body["enabled"] is False


async def test_the_scope_ceiling_round_trips(
    client: AsyncClient, session: AsyncSession
):
    headers = await _owner_headers(session)
    row = await _seed(session)
    assert (await client.get(f"{BASE}{row.id}", headers=headers)).json()[
        "scope_ceiling"
    ] == []

    response = await client.patch(
        f"{BASE}{row.id}",
        headers=headers,
        json={"scope_ceiling": ["projects:write", "comments:read"]},
    )

    assert response.status_code == 200, response.text
    assert response.json()["scope_ceiling"] == ["comments:read", "projects:write"]


async def test_patch_refuses_a_scope_outside_the_vocabulary(
    client: AsyncClient, session: AsyncSession
):
    headers = await _owner_headers(session)
    row = await _seed(session, scope_ceiling=["projects:read"])

    response = await client.patch(
        f"{BASE}{row.id}", headers=headers, json={"scope_ceiling": ["root:write"]}
    )

    assert response.status_code == 400, response.text
    assert response.json()["detail"] == AppServiceMessages.UNKNOWN_SCOPE
    await session.refresh(row)
    assert row.scope_ceiling == ["projects:read"]


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
        (
            "a scope outside the vocabulary",
            {**NEW, "scope_ceiling": ["root:write"]},
            AppServiceMessages.UNKNOWN_SCOPE,
        ),
        (
            "a malformed base url",
            {**NEW, "base_url": "ftp://app.example.com"},
            AppServiceMessages.INVALID_BASE_URL,
        ),
        # Its own code, so an operator is told which of the two addresses the
        # registry would not take.
        (
            "a malformed embed origin",
            {**NEW, "embed_origin": "ftp://app.example.com"},
            AppServiceMessages.INVALID_EMBED_ORIGIN,
        ),
        (
            "an origin carrying a path",
            {**NEW, "allowed_origins": ["https://app.example.com/embed"]},
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

    response = await client.post(BASE, headers=headers, json=NEW)

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


# --- publishers ---------------------------------------------------------------


async def test_owner_adds_and_lists_a_publisher(
    client: AsyncClient, session: AsyncSession
):
    headers = await _owner_headers(session)

    created = await client.post(
        PUBLISHERS,
        headers=headers,
        json={"prefix": "Private-Apps", "display_name": "Our own apps"},
    )

    assert created.status_code == 201, created.text
    body = created.json()
    assert body["prefix"] == "private-apps"
    assert body["display_name"] == "Our own apps"
    assert body["verified"] is False
    assert body["enabled"] is True

    listed = await client.get(PUBLISHERS, headers=headers)
    assert "private-apps" in {entry["prefix"] for entry in listed.json()}

    again = await client.post(
        PUBLISHERS,
        headers=headers,
        json={"prefix": "private-apps", "display_name": "Twice"},
    )
    assert again.status_code == 409
    assert again.json()["detail"] == AppServiceMessages.DUPLICATE_PUBLISHER


@pytest.mark.parametrize("prefix", ["", "has.dot", "has space", "x" * 121])
async def test_a_prefix_is_one_segment_of_an_app_id(
    client: AsyncClient, session: AsyncSession, prefix: str
):
    headers = await _owner_headers(session)

    response = await client.post(
        PUBLISHERS, headers=headers, json={"prefix": prefix, "display_name": "X"}
    )

    assert response.status_code in (400, 422), response.text


async def test_switching_a_publisher_off_takes_its_apps_out_of_service(
    client: AsyncClient, session: AsyncSession
):
    headers = await _owner_headers(session)
    row = await _seed(session)
    assert (await client.get(f"{BASE}{row.id}", headers=headers)).json()["live"]

    off = await client.patch(
        f"{PUBLISHERS}{row.publisher_id}",
        headers=headers,
        json={"enabled": False, "display_name": "Acme, paused"},
    )

    assert off.status_code == 200, off.text
    assert off.json()["enabled"] is False
    assert off.json()["display_name"] == "Acme, paused"
    read = (await client.get(f"{BASE}{row.id}", headers=headers)).json()
    assert read["enabled"] is True
    assert read["publisher_enabled"] is False
    assert read["live"] is False


async def test_a_missing_publisher_is_a_404(client: AsyncClient, session: AsyncSession):
    headers = await _owner_headers(session)

    response = await client.patch(
        f"{PUBLISHERS}999999", headers=headers, json={"enabled": False}
    )

    assert response.status_code == 404
    assert response.json()["detail"] == AppServiceMessages.PUBLISHER_NOT_FOUND


# --- vendor values -------------------------------------------------------------


VENDOR_DEFINITION = {
    "app_kind": "service",
    "service": {"public_id": "acme.widgets", "protocol": 1},
    "features": [],
    "vendor": {
        "label": {"en": "Widget client"},
        "fields": [
            {
                "key": "client_id",
                "type": "string",
                "required": True,
                "label": {"en": "Client id"},
            },
            {
                "key": "client_secret",
                "type": "secret",
                "required": True,
                "label": {"en": "Client secret"},
            },
        ],
    },
}


async def _vendor_listing(session: AsyncSession) -> None:
    await create_marketplace_listing(
        session,
        uid=LISTING_UID,
        public_id="acme.widgets",
        kind="app",
        definition=VENDOR_DEFINITION,
    )


async def test_the_form_shows_the_fields_the_listing_asks_for(
    client: AsyncClient, session: AsyncSession
):
    await _vendor_listing(session)
    headers = await _owner_headers(session)
    row = await _seed(session)

    body = (await client.get(f"{BASE}{row.id}", headers=headers)).json()

    assert [field["key"] for field in body["vendor_fields"]] == [
        "client_id",
        "client_secret",
    ]
    assert body["vendor_fields"][1]["type"] == "secret"
    assert body["vendor_set"] == []
    assert body["connection_callback_url"] == (
        f"{settings.APP_URL.rstrip('/')}/api/v1/app-connections/callback"
    )
    assert body["connection_setup_url"] == (
        f"{settings.APP_URL.rstrip('/')}/api/v1/app-connections/setup"
    )


async def test_a_secret_is_written_and_shown_only_as_set(
    client: AsyncClient, session: AsyncSession
):
    await _vendor_listing(session)
    headers = await _owner_headers(session)
    row = await _seed(session)

    response = await client.patch(
        f"{BASE}{row.id}",
        headers=headers,
        json={"vendor_values": {"client_id": "widget-app", "client_secret": "s3cr3t"}},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["vendor_values"] == {"client_id": "widget-app"}
    assert body["vendor_set"] == ["client_id", "client_secret"]
    assert body["vendor_ready"] is True
    assert body["live"] is True
    assert "s3cr3t" not in response.text

    # Left out, a secret is kept; sent empty, it is cleared.
    kept = await client.patch(
        f"{BASE}{row.id}",
        headers=headers,
        json={"vendor_values": {"client_id": "widget-app-2"}},
    )
    assert kept.json()["vendor_set"] == ["client_id", "client_secret"]
    cleared = await client.patch(
        f"{BASE}{row.id}",
        headers=headers,
        json={"vendor_values": {"client_secret": ""}},
    )
    assert cleared.json()["vendor_set"] == ["client_id"]


async def test_a_registration_is_not_live_until_its_required_values_are_set(
    client: AsyncClient, session: AsyncSession
):
    await _vendor_listing(session)
    headers = await _owner_headers(session)
    row = await _seed(session)

    body = (
        await client.patch(
            f"{BASE}{row.id}",
            headers=headers,
            json={"vendor_values": {"client_id": "widget-app"}},
        )
    ).json()

    assert body["vendor_ready"] is False
    assert body["live"] is False


async def test_a_value_the_listing_does_not_ask_for_is_refused(
    client: AsyncClient, session: AsyncSession
):
    await _vendor_listing(session)
    headers = await _owner_headers(session)
    row = await _seed(session)

    response = await client.patch(
        f"{BASE}{row.id}",
        headers=headers,
        json={"vendor_values": {"webhook_secret": "x"}},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == AppServiceMessages.UNKNOWN_VENDOR_FIELD


async def test_a_registry_registration_takes_its_vendor_values(
    client: AsyncClient, session: AsyncSession
):
    """The registry states what an app is; the vendor client it uses here is
    this deployment's, like its address."""
    await _vendor_listing(session)
    headers = await _owner_headers(session)
    row = await _seed(session, source="registry")

    response = await client.patch(
        f"{BASE}{row.id}",
        headers=headers,
        json={"vendor_values": {"client_id": "a", "client_secret": "b"}},
    )

    assert response.status_code == 200, response.text
    assert response.json()["vendor_ready"] is True
