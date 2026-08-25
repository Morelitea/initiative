"""Publishing the keys an app verifies calls with.

Two documents, one per kind of caller: the platform's own signing key, and the
delegates' provisioned keys. Both are **public** — an app fetching the key it
will check a credential with cannot be asked for a credential first — and the
two differ on what an empty answer means. An unconfigured platform key answers
**503 rather than an empty key set**: the two look similar and mean opposite
things, and an app that cached `{"keys": []}` would refuse every later token
from a platform that had simply not been wired up yet. The delegate set is the
other way round: no delegate wired up means exactly no delegate keys, so an
empty array is the honest answer and 200 is the status.
"""

import base64

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import AsyncClient

from app.core.config import settings
from app.core.messages import AppServiceMessages
from app.services.marketplace import context_jwt
from app.services.marketplace.registration_lookup import invalidate_registrations
from app.testing import create_app_service_registration

pytestmark = pytest.mark.asyncio

JWKS_URL = "/api/v1/app-platform/jwks.json"
DELEGATES_JWKS_URL = "/api/v1/app-platform/delegates/jwks.json"

_keypair = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_PRIVATE_PEM = _keypair.private_bytes(
    serialization.Encoding.PEM,
    serialization.PrivateFormat.PKCS8,
    serialization.NoEncryption(),
).decode()


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setattr(settings, "APP_PLATFORM_SIGNING_PRIVATE_KEY_PEM", _PRIVATE_PEM)
    monkeypatch.setattr(settings, "APP_PLATFORM_SIGNING_KEY_ID", "app-platform-1")
    monkeypatch.setattr(context_jwt, "_jwks_cache", None, raising=False)


@pytest.fixture
def unconfigured(monkeypatch):
    monkeypatch.setattr(settings, "APP_PLATFORM_SIGNING_PRIVATE_KEY_PEM", None)
    monkeypatch.setattr(context_jwt, "_jwks_cache", None, raising=False)


async def test_the_key_set_is_served_without_any_credential(
    client: AsyncClient, configured
):
    response = await client.get(JWKS_URL)
    assert response.status_code == 200, response.text

    keys = response.json()["keys"]
    assert len(keys) == 1
    assert keys[0]["kty"] == "RSA"
    assert keys[0]["alg"] == "RS256"
    assert keys[0]["kid"] == "app-platform-1"
    assert keys[0]["n"] and keys[0]["e"]


async def test_it_never_serves_private_material(client: AsyncClient, configured):
    entry = (await client.get(JWKS_URL)).json()["keys"][0]
    assert set(entry) <= {"kty", "use", "alg", "kid", "n", "e"}


async def test_an_unconfigured_deployment_says_so_rather_than_publishing_nothing(
    client: AsyncClient, unconfigured
):
    response = await client.get(JWKS_URL)
    assert response.status_code == 503
    assert response.json()["detail"] == AppServiceMessages.SIGNING_NOT_CONFIGURED


# --- the delegates' keys ----------------------------------------------------


def _b64u_int(value: int) -> str:
    raw = value.to_bytes((value.bit_length() + 7) // 8, "big")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _delegate_jwk(kid: str) -> dict:
    numbers = _keypair.public_key().public_numbers()
    return {
        "kty": "RSA",
        "use": "sig",
        "alg": "RS256",
        "kid": kid,
        "n": _b64u_int(numbers.n),
        "e": _b64u_int(numbers.e),
    }


async def test_delegate_keys_are_served_without_any_credential(
    client: AsyncClient, session
):
    entry = _delegate_jwk("auto-1")
    await create_app_service_registration(
        session,
        public_id="tests.auto",
        grants=["delegation"],
        delegation_jwks={"keys": [entry]},
    )

    response = await client.get(DELEGATES_JWKS_URL)
    assert response.status_code == 200, response.text
    assert response.json() == {"keys": [entry]}


async def test_only_enabled_registrations_holding_the_grant_publish(
    client: AsyncClient, session
):
    await create_app_service_registration(
        session,
        public_id="tests.auto",
        grants=["delegation"],
        delegation_jwks={"keys": [_delegate_jwk("published")]},
    )
    await create_app_service_registration(
        session,
        public_id="tests.auto-off",
        grants=["delegation"],
        enabled=False,
        delegation_jwks={"keys": [_delegate_jwk("switched-off")]},
    )
    await create_app_service_registration(
        session,
        public_id="tests.no-grant",
        grants=[],
        delegation_jwks={"keys": [_delegate_jwk("ungranted")]},
    )

    keys = (await client.get(DELEGATES_JWKS_URL)).json()["keys"]
    assert [entry["kid"] for entry in keys] == ["published"]


async def test_no_delegates_is_an_empty_set_not_an_error(client: AsyncClient):
    invalidate_registrations()
    response = await client.get(DELEGATES_JWKS_URL)
    assert response.status_code == 200
    assert response.json() == {"keys": []}
