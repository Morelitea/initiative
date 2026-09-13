"""Publishing the keys an app verifies calls with.

Two documents, one per kind of caller: the platform's own signing key, and the
delegates' provisioned keys. Both are **public** — an app fetching the key it
will check a credential with cannot be asked for a credential first — and the
two differ on what an empty answer means. An unconfigured platform key answers
**503 rather than an empty key set**: the two look similar and mean opposite
things, and an app that cached `{"keys": []}` would refuse every later token
from a platform that had simply not been wired up yet.

Delegates are addressed **one document per delegate**, and that is the property
most worth holding here. A `kid` is an opaque label its owner picks, unique
only within the registration that published it — Initiative's own verification
copes with a collision by trying every candidate key, which is not what a JWKS
consumer does. A merged document would hand out two entries under one `kid` and
get valid calls rejected.
"""

import base64

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import AsyncClient

from app.core.config import settings
from app.core.messages import AppServiceMessages
from app.services.marketplace import context_jwt


JWKS_URL = "/api/v1/app-platform/jwks.json"

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


def _jwk_from(key: rsa.RSAPrivateKey, kid: str) -> dict:
    numbers = key.public_key().public_numbers()
    return {
        "kty": "RSA",
        "use": "sig",
        "alg": "RS256",
        "kid": kid,
        "n": _b64u_int(numbers.n),
        "e": _b64u_int(numbers.e),
    }


def _delegate_jwk(kid: str) -> dict:
    return _jwk_from(_keypair, kid)
