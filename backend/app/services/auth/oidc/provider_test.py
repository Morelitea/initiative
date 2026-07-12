"""Tests for the composed OIDC relying-party flow (begin/complete).

A fake IdP (discovery + JWKS + token endpoint) runs behind an
``httpx.MockTransport``, so the full begin → callback → verified-claims path is
exercised with no network. Failure tests attack each trust decision in
``complete``: the state, the token response, the signing key, and the id_token
claims.
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from app.services.auth.oidc.flow_state import decode_flow_state
from app.services.auth.oidc.provider import (
    OidcClientConfig,
    OidcFlowError,
    OidcProvider,
)
from app.testing.oidc import (
    CLIENT_ID,
    ISSUER,
    OTHER_KEY,
    FakeIdp,
    mint_id_token as _mint_id_token,
)

pytestmark = pytest.mark.unit

REDIRECT_URI = "https://app.example.com/api/v1/auth/oidc/callback"


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


# --- userinfo enrichment ------------------------------------------------------


async def test_fetch_userinfo_returns_claims_with_bearer():
    idp = FakeIdp(userinfo_claims={"sub": "idp-subject-1", "email": "a@example.com"})
    provider = _provider(idp)
    claims = await provider.fetch_userinfo("at-123")
    assert claims == {"sub": "idp-subject-1", "email": "a@example.com"}
    assert idp.userinfo_bearer_tokens == ["Bearer at-123"]


async def test_fetch_userinfo_none_when_not_advertised():
    idp = FakeIdp()  # no userinfo_claims → discovery omits userinfo_endpoint
    provider = _provider(idp)
    assert await provider.fetch_userinfo("at-123") is None
    assert "/userinfo" not in idp.calls


async def test_fetch_userinfo_failure_raises_flow_error():
    idp = FakeIdp(userinfo_claims={"sub": "idp-subject-1"})
    idp.userinfo_response = httpx.Response(401, json={"error": "invalid_token"})
    provider = _provider(idp)
    with pytest.raises(OidcFlowError) as err:
        await provider.fetch_userinfo("expired")
    assert err.value.code == "userinfo_failed"
