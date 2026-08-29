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
from app.services.marketplace.registration_lookup import invalidate_registrations
from app.testing import create_app_service_registration


JWKS_URL = "/api/v1/app-platform/jwks.json"
DELEGATES_JWKS_URL = "/api/v1/app-platform/delegates/%s/jwks.json"

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


#: A second, genuinely different key — so a shared ``kid`` across two
#: registrations is a real collision rather than the same key twice.
_other_keypair = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _other_delegate_jwk(kid: str) -> dict:
    return _jwk_from(_other_keypair, kid)


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

    response = await client.get(DELEGATES_JWKS_URL % "tests.auto")
    assert response.status_code == 200, response.text
    assert response.json() == {"keys": [entry]}


async def test_two_delegates_sharing_a_kid_keep_separate_key_sets(
    client: AsyncClient, session
):
    """A kid is unique only within the registration that published it.

    Initiative's own verification handles a collision by trying every
    candidate key, which is not something a JWKS consumer does — it selects one
    key per kid. So each delegate is addressed on its own, and a shared label
    resolves to that delegate's key rather than to whichever was merged first.
    """
    mine = _delegate_jwk("signing-key")
    theirs = _other_delegate_jwk("signing-key")
    await create_app_service_registration(
        session,
        public_id="tests.auto",
        grants=["delegation"],
        delegation_jwks={"keys": [mine]},
    )
    await create_app_service_registration(
        session,
        public_id="tests.other-auto",
        grants=["delegation"],
        delegation_jwks={"keys": [theirs]},
    )

    assert (await client.get(DELEGATES_JWKS_URL % "tests.auto")).json() == {
        "keys": [mine]
    }
    assert (await client.get(DELEGATES_JWKS_URL % "tests.other-auto")).json() == {
        "keys": [theirs]
    }
    # The distinct keys are what makes this a real collision rather than the
    # same key published twice.
    assert mine["n"] != theirs["n"]


@pytest.mark.parametrize(
    "public_id, grants, enabled",
    [
        ("tests.auto-off", ["delegation"], False),
        ("tests.no-grant", [], True),
    ],
)
async def test_a_delegate_that_cannot_act_publishes_nothing(
    client: AsyncClient, session, public_id, grants, enabled
):
    """The same rule that resolves a token decides what is published: switched
    off or never granted, there is nothing here to verify against."""
    await create_app_service_registration(
        session,
        public_id=public_id,
        grants=grants,
        enabled=enabled,
        delegation_jwks={"keys": [_delegate_jwk("unpublished")]},
    )

    response = await client.get(DELEGATES_JWKS_URL % public_id)
    assert response.status_code == 404
    assert response.json()["detail"] == AppServiceMessages.NOT_FOUND


async def test_an_unknown_delegate_is_not_found(client: AsyncClient):
    invalidate_registrations()
    response = await client.get(DELEGATES_JWKS_URL % "tests.nobody")
    assert response.status_code == 404
    assert response.json()["detail"] == AppServiceMessages.NOT_FOUND
