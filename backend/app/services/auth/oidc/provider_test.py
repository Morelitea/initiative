"""Tests for the composed OIDC relying-party flow (begin/complete).

A fake IdP (discovery + JWKS + token endpoint) runs behind an
``httpx.MockTransport``, so the full begin → callback → verified-claims path is
exercised with no network. Failure tests attack each trust decision in
``complete``: the state, the token response, the signing key, and the id_token
claims.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlsplit

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

from app.services.auth.oidc.flow_state import decode_flow_state
from app.services.auth.oidc.provider import (
    OidcClientConfig,
    OidcFlowError,
    OidcProvider,
)

pytestmark = pytest.mark.unit

ISSUER = "https://idp.example.com"
CLIENT_ID = "client-123"
REDIRECT_URI = "https://app.example.com/api/v1/auth/oidc/callback"

IDP_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _pem(priv) -> str:
    return priv.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()


def _jwks_doc(priv=IDP_KEY, kid: str = "k1") -> dict:
    data = json.loads(RSAAlgorithm.to_jwk(priv.public_key()))
    data.update({"kid": kid, "alg": "RS256", "use": "sig"})
    return {"keys": [data]}


def _mint_id_token(
    *, nonce: str, priv=IDP_KEY, kid: str = "k1", **claim_overrides
) -> str:
    now = datetime.now(timezone.utc)
    claims = {
        "iss": ISSUER,
        "sub": "idp-subject-1",
        "aud": CLIENT_ID,
        "exp": now + timedelta(minutes=5),
        "iat": now,
        "nonce": nonce,
        "email": "alice@example.com",
    }
    claims.update(claim_overrides)
    return jwt.encode(claims, _pem(priv), algorithm="RS256", headers={"kid": kid})


class FakeIdp:
    """Routes discovery/JWKS/token requests; records the token-request form.

    ``algs`` fills ``id_token_signing_alg_values_supported``; ``None`` means the
    discovery document omits the field entirely (an immutable tuple default —
    do not "fix" it to ``None``, which has that distinct meaning).
    """

    def __init__(self, *, algs: tuple[str, ...] | None = ("RS256", "ES256")):
        doc: dict[str, object] = {
            "issuer": ISSUER,
            "authorization_endpoint": f"{ISSUER}/authorize",
            "token_endpoint": f"{ISSUER}/token",
            "jwks_uri": f"{ISSUER}/jwks",
        }
        if algs is not None:
            doc["id_token_signing_alg_values_supported"] = list(algs)
        self.discovery_doc = doc
        self.jwks_doc = _jwks_doc()
        # A fixed httpx.Response, or a callable building one from the parsed form.
        self.token_response: (
            httpx.Response | Callable[[dict[str, str]], httpx.Response] | None
        ) = None
        self.token_request_form: dict[str, str] = {}
        self.calls: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.calls.append(path)
        if path.endswith("/.well-known/openid-configuration"):
            return httpx.Response(200, json=self.discovery_doc)
        if path == "/jwks":
            return httpx.Response(200, json=self.jwks_doc)
        if path == "/token":
            form = parse_qs(request.content.decode())
            self.token_request_form = {k: v[0] for k, v in form.items()}
            resp = self.token_response
            if resp is None:
                return httpx.Response(500, text="test did not set token_response")
            if isinstance(resp, httpx.Response):
                return resp
            return resp(self.token_request_form)
        return httpx.Response(404)

    def client_factory(self):
        transport = httpx.MockTransport(self.handler)
        return lambda: httpx.AsyncClient(transport=transport)


def _provider(idp: FakeIdp, *, client_secret: str | None = "s3cret") -> OidcProvider:
    config = OidcClientConfig(
        issuer=ISSUER,
        client_id=CLIENT_ID,
        redirect_uri=REDIRECT_URI,
        client_secret=client_secret,
    )
    return OidcProvider(config, client_factory=idp.client_factory())


async def _begin_and_complete(idp: FakeIdp, provider: OidcProvider):
    """Run the full flow, minting the id_token with the nonce the flow chose
    (read from the authorization URL, as the real IdP would)."""
    begun = await provider.begin()
    nonce = parse_qs(urlsplit(begun.authorization_url).query)["nonce"][0]
    if idp.token_response is None:
        idp.token_response = httpx.Response(
            200,
            json={
                "access_token": "at-123",
                "refresh_token": "rt-456",
                "id_token": _mint_id_token(nonce=nonce),
                "token_type": "Bearer",
            },
        )
    return await provider.complete(code="auth-code-1", state=begun.state)


# --- begin -------------------------------------------------------------------


async def test_begin_builds_authorization_url():
    idp = FakeIdp()
    provider = _provider(idp)

    begun = await provider.begin(mobile=True, device_name="Pixel")
    parts = urlsplit(begun.authorization_url)
    assert f"{parts.scheme}://{parts.netloc}{parts.path}" == f"{ISSUER}/authorize"
    params = {k: v[0] for k, v in parse_qs(parts.query).items()}
    assert params["response_type"] == "code"
    assert params["client_id"] == CLIENT_ID
    assert params["redirect_uri"] == REDIRECT_URI
    assert params["scope"] == "openid email profile"
    assert params["code_challenge_method"] == "S256"
    assert params["state"] == begun.state

    # The URL's nonce and challenge must be the ones sealed inside the state.
    flow = decode_flow_state(begun.state)
    assert params["nonce"] == flow.nonce
    assert params["code_challenge"] == flow.code_challenge
    assert flow.mobile is True
    assert flow.device_name == "Pixel"


async def test_begin_appends_to_existing_query():
    idp = FakeIdp()
    idp.discovery_doc["authorization_endpoint"] = f"{ISSUER}/authorize?tenant=acme"
    provider = _provider(idp)

    begun = await provider.begin()
    params = parse_qs(urlsplit(begun.authorization_url).query)
    assert params["tenant"] == ["acme"]
    assert "client_id" in params


# --- complete: happy path ------------------------------------------------------


async def test_complete_returns_verified_identity():
    idp = FakeIdp()
    provider = _provider(idp)

    done = await _begin_and_complete(idp, provider)
    assert done.subject == "idp-subject-1"
    assert done.claims["email"] == "alice@example.com"
    assert done.access_token == "at-123"
    assert done.refresh_token == "rt-456"
    assert done.mobile is False


async def test_complete_sends_code_exchange_form():
    idp = FakeIdp()
    provider = _provider(idp)

    begun = await provider.begin()
    flow = decode_flow_state(begun.state)
    idp.token_response = httpx.Response(
        200, json={"id_token": _mint_id_token(nonce=flow.nonce)}
    )
    await provider.complete(code="auth-code-1", state=begun.state)

    form = idp.token_request_form
    assert form["grant_type"] == "authorization_code"
    assert form["code"] == "auth-code-1"
    assert form["redirect_uri"] == REDIRECT_URI
    assert form["client_id"] == CLIENT_ID
    assert form["client_secret"] == "s3cret"
    # PKCE: the verifier sent must be the one sealed in the state.
    assert form["code_verifier"] == flow.code_verifier


async def test_public_client_sends_no_secret():
    idp = FakeIdp()
    provider = _provider(idp, client_secret=None)

    begun = await provider.begin()
    flow = decode_flow_state(begun.state)
    idp.token_response = httpx.Response(
        200, json={"id_token": _mint_id_token(nonce=flow.nonce)}
    )
    done = await provider.complete(code="c", state=begun.state)
    assert done.subject == "idp-subject-1"
    assert "client_secret" not in idp.token_request_form


# --- complete: rejection paths ---------------------------------------------------


async def test_missing_code_rejected_without_network():
    idp = FakeIdp()
    provider = _provider(idp)
    with pytest.raises(OidcFlowError) as err:
        await provider.complete(code="", state="whatever")
    assert err.value.code == "missing_authorization_code"
    assert idp.calls == []


async def test_invalid_state_rejected_without_network():
    idp = FakeIdp()
    provider = _provider(idp)
    with pytest.raises(OidcFlowError) as err:
        await provider.complete(code="c", state="garbage")
    assert err.value.code == "invalid_state"
    assert idp.calls == []


async def test_token_endpoint_error_rejected():
    idp = FakeIdp()
    provider = _provider(idp)
    begun = await provider.begin()
    idp.token_response = httpx.Response(400, json={"error": "invalid_grant"})
    with pytest.raises(OidcFlowError) as err:
        await provider.complete(code="c", state=begun.state)
    assert err.value.code == "token_request_failed"
    # The OAuth error body survives into the (server-side) detail for debugging.
    assert "invalid_grant" in str(err.value)


def test_empty_client_id_rejected_at_construction():
    """Config problems surface where the provider is built, not mid-login."""
    with pytest.raises(ValueError):
        OidcClientConfig(issuer=ISSUER, client_id="", redirect_uri=REDIRECT_URI)
    with pytest.raises(ValueError):
        OidcClientConfig(issuer="", client_id=CLIENT_ID, redirect_uri=REDIRECT_URI)
    with pytest.raises(ValueError):
        OidcClientConfig(issuer=ISSUER, client_id=CLIENT_ID, redirect_uri="")


async def test_token_response_missing_id_token_rejected():
    idp = FakeIdp()
    provider = _provider(idp)
    begun = await provider.begin()
    idp.token_response = httpx.Response(200, json={"access_token": "at-only"})
    with pytest.raises(OidcFlowError) as err:
        await provider.complete(code="c", state=begun.state)
    assert err.value.code == "token_missing_id_token"


async def test_token_response_non_object_rejected():
    idp = FakeIdp()
    provider = _provider(idp)
    begun = await provider.begin()
    idp.token_response = httpx.Response(200, json=["not", "an", "object"])
    with pytest.raises(OidcFlowError) as err:
        await provider.complete(code="c", state=begun.state)
    assert err.value.code == "token_request_failed"


async def test_id_token_with_unknown_kid_rejected():
    idp = FakeIdp()
    provider = _provider(idp)
    begun = await provider.begin()
    nonce = decode_flow_state(begun.state).nonce
    idp.token_response = httpx.Response(
        200, json={"id_token": _mint_id_token(nonce=nonce, kid="not-in-jwks")}
    )
    with pytest.raises(OidcFlowError) as err:
        await provider.complete(code="c", state=begun.state)
    assert err.value.code == "id_token_unverifiable"


async def test_id_token_signed_by_wrong_key_rejected():
    """Same kid, different private key: resolves a key but the signature fails."""
    idp = FakeIdp()
    provider = _provider(idp)
    begun = await provider.begin()
    nonce = decode_flow_state(begun.state).nonce
    idp.token_response = httpx.Response(
        200, json={"id_token": _mint_id_token(nonce=nonce, priv=OTHER_KEY)}
    )
    with pytest.raises(OidcFlowError) as err:
        await provider.complete(code="c", state=begun.state)
    assert err.value.code == "id_token_rejected"


async def test_id_token_with_wrong_nonce_rejected():
    idp = FakeIdp()
    provider = _provider(idp)
    begun = await provider.begin()
    idp.token_response = httpx.Response(
        200, json={"id_token": _mint_id_token(nonce="a-replayed-nonce")}
    )
    with pytest.raises(OidcFlowError) as err:
        await provider.complete(code="c", state=begun.state)
    assert err.value.code == "id_token_rejected"


async def test_id_token_for_other_audience_rejected():
    idp = FakeIdp()
    provider = _provider(idp)
    begun = await provider.begin()
    nonce = decode_flow_state(begun.state).nonce
    idp.token_response = httpx.Response(
        200, json={"id_token": _mint_id_token(nonce=nonce, aud="another-client")}
    )
    with pytest.raises(OidcFlowError) as err:
        await provider.complete(code="c", state=begun.state)
    assert err.value.code == "id_token_rejected"


# --- algorithm negotiation --------------------------------------------------------


async def test_provider_advertising_only_symmetric_algs_rejected():
    """A discovery doc advertising only HMAC algs must be an OidcFlowError —
    never a fallback to accepting HMAC, and never a raw ValueError."""
    idp = FakeIdp(algs=("HS256",))
    provider = _provider(idp)
    begun = await provider.begin()
    nonce = decode_flow_state(begun.state).nonce
    idp.token_response = httpx.Response(
        200, json={"id_token": _mint_id_token(nonce=nonce)}
    )
    with pytest.raises(OidcFlowError) as err:
        await provider.complete(code="c", state=begun.state)
    assert err.value.code == "id_token_rejected"


async def test_token_alg_outside_advertised_set_rejected():
    """Discovery advertises ES256 only; an RS256 id_token must be refused."""
    idp = FakeIdp(algs=("ES256",))
    provider = _provider(idp)
    begun = await provider.begin()
    nonce = decode_flow_state(begun.state).nonce
    idp.token_response = httpx.Response(
        200, json={"id_token": _mint_id_token(nonce=nonce)}
    )
    with pytest.raises(OidcFlowError) as err:
        await provider.complete(code="c", state=begun.state)
    assert err.value.code == "id_token_rejected"


async def test_no_advertised_algs_uses_default_pair():
    idp = FakeIdp(algs=None)  # discovery omits the field entirely
    provider = _provider(idp)
    done = await _begin_and_complete(idp, provider)
    assert done.subject == "idp-subject-1"
