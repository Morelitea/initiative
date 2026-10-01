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
    # http where the base URL is http, on its origin and nowhere else.
    assert app_keys.jwks_uri_allowed(
        "http://github:8080/.well-known/jwks.json", "http://github:8080"
    )
    assert not app_keys.jwks_uri_allowed(
        "http://keys:8080/.well-known/jwks.json", "http://github:8080"
    )
    assert not app_keys.jwks_uri_allowed(
        "https://github:8080/.well-known/jwks.json", "http://github:8080"
    )


async def test_an_http_address_on_an_http_base_url_is_fetched():
    base = "http://127.0.0.1:9100"
    fetched, transport = _serving({"keys": [_jwk(_published, "pub-1")]})

    key = await app_keys.key_for(
        _snapshot(base_url=base, jwks_uri=app_keys.key_set_url(base)),
        "pub-1",
        transport=transport,
    )

    assert key is not None
    assert fetched == [f"{base}/.well-known/jwks.json"]


def test_a_thumbprint_is_rfc_7638():
    """The worked example in RFC 7638 §3.1: only the required members count,
    in order, whatever else the key carries."""
    key = {
        "kty": "RSA",
        "n": (
            "0vx7agoebGcQSuuPiLJXZptN9nndrQmbXEps2aiAFbWhM78LhWx4cbbfAAtVT86zwu1RK7aPFFx"
            "uhDR1L6tSoc_BJECPebWKRXjBZCiFV4n3oknjhMstn64tZ_2W-5JsGY4Hc5n9yBXArwl93lqt7_R"
            "N5w6Cf0h4QyQ5v-65YGjQR0_FDW2QvzqY368QQMicAtaSqzs8KJZgnYb9c7d0zgdAZHzu6qMQvR"
            "L5hajrn1n91CbOpbISD08qNLyrdkt-bFTWhAI4vMQFh6WeZu0fM4lFd2NcRwr3XPksINHaQ-G_x"
            "BniIqbw0Ls1jF44-csFCur-kEgU8awapJzKnqDKgw"
        ),
        "e": "AQAB",
        "alg": "RS256",
        "kid": "2011-04-29",
    }

    assert app_keys.jwk_thumbprint(key) == "NzbLsXh8uDCcd-6MNwXF4W_7noWXFZAfHkxZsRGC9Xs"
