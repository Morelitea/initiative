"""Publishing the key an app verifies our calls with.

Two things are worth pinning. It is **public** — an app fetching the key it will
check a credential with cannot be asked for a credential first. And an
unconfigured deployment answers **503 rather than an empty key set**: the two
look similar and mean opposite things, and an app that cached `{"keys": []}`
would refuse every later token from a platform that had simply not been wired up
yet.
"""

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import AsyncClient

from app.core.config import settings
from app.core.messages import AppServiceMessages
from app.services.marketplace import context_jwt

pytestmark = pytest.mark.asyncio

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
