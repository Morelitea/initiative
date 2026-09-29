"""The keys an app signs with: pasted into its registration, or published by
the app at its key set address and fetched from there.

The fetch runs through an injected ``httpx.MockTransport`` against a loopback
literal, so nothing here touches the network.
"""

import json
from types import MappingProxyType

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from jwt.algorithms import ECAlgorithm

from app.services.marketplace import app_keys
from app.services.marketplace.registration_lookup import RegistrationSnapshot


BASE = "https://127.0.0.1:9443"
JWKS_URI = f"{BASE}/.well-known/jwks.json"

_published = ec.generate_private_key(ec.SECP256R1())
_pasted = ec.generate_private_key(ec.SECP256R1())


def _jwk(key, kid: str) -> dict:
    entry = json.loads(ECAlgorithm.to_jwk(key.public_key()))
    entry["kid"] = kid
    return entry


def _snapshot(*, jwks_uri: str | None = JWKS_URI, base_url: str = BASE, keys=None):
    return RegistrationSnapshot(
        public_id="acme.tracker",
        listing_uid="K7M2QX8N4TVB9C",
        base_url=base_url,
        embed_origin=None,
        allowed_origins=(base_url,),
        keys=MappingProxyType(keys or {}),
        mandatory=False,
        enabled=True,
        live=True,
        jwks_uri=jwks_uri,
    )


def _serving(document, *, status: int = 200):
    fetched: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        fetched.append(str(request.url))
        return httpx.Response(status, json=document)

    return fetched, httpx.MockTransport(handler)


@pytest.fixture(autouse=True)
def _fresh_cache():
    app_keys.clear_fetched_keys()
    yield
    app_keys.clear_fetched_keys()


async def test_a_published_key_is_found_by_its_kid():
    fetched, transport = _serving({"keys": [_jwk(_published, "pub-1")]})

    key = await app_keys.key_for(_snapshot(), "pub-1", transport=transport)

    assert key is not None
    assert key.public_numbers() == _published.public_key().public_numbers()
    assert fetched == [JWKS_URI]


async def test_a_fetched_set_is_reused_for_a_minute(monkeypatch):
    fetched, transport = _serving({"keys": [_jwk(_published, "pub-1")]})
    now = [1000.0]
    monkeypatch.setattr(app_keys.time, "monotonic", lambda: now[0])

    await app_keys.key_for(_snapshot(), "pub-1", transport=transport)
    await app_keys.key_for(_snapshot(), "unknown", transport=transport)
    assert len(fetched) == 1

    now[0] += 61
    await app_keys.key_for(_snapshot(), "pub-1", transport=transport)
    assert len(fetched) == 2


async def test_a_pasted_key_answers_without_a_fetch():
    fetched, transport = _serving({"keys": []})
    snapshot = _snapshot(keys={"paste-1": _pasted.public_key()})

    key = await app_keys.key_for(snapshot, "paste-1", transport=transport)

    assert key is not None
    assert fetched == []


@pytest.mark.parametrize(
    "jwks_uri",
    [
        "http://127.0.0.1:9443/jwks.json",
        "https://127.0.0.2:9443/jwks.json",
        "https://127.0.0.1:9444/jwks.json",
    ],
)
async def test_an_address_off_the_apps_origin_is_not_fetched(jwks_uri):
    fetched, transport = _serving({"keys": [_jwk(_published, "pub-1")]})

    key = await app_keys.key_for(
        _snapshot(jwks_uri=jwks_uri), "pub-1", transport=transport
    )

    assert key is None
    assert fetched == []


async def test_a_failed_fetch_finds_no_key():
    fetched, transport = _serving({"detail": "nope"}, status=500)

    assert await app_keys.key_for(_snapshot(), "pub-1", transport=transport) is None
    assert fetched == [JWKS_URI]


async def test_private_and_symmetric_entries_are_left_out():
    private = _jwk(_published, "priv-1")
    private["d"] = "AAAA"
    symmetric = {"kty": "oct", "kid": "sym-1", "k": "c2VjcmV0"}
    _fetched, transport = _serving({"keys": [private, symmetric]})

    for kid in ("priv-1", "sym-1"):
        assert await app_keys.key_for(_snapshot(), kid, transport=transport) is None


def test_the_address_rule():
    assert app_keys.jwks_uri_allowed(JWKS_URI, BASE)
    assert app_keys.jwks_uri_allowed(f"{BASE}/keys", f"{BASE}/prefix")
    assert not app_keys.jwks_uri_allowed(JWKS_URI, "http://127.0.0.1:9443")
    assert not app_keys.jwks_uri_allowed("not a url", BASE)
