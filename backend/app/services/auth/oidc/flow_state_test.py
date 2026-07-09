"""Adversarial tests for the encrypted OIDC flow state.

The state parameter round-trips through the browser, so the suite attacks it
from that position: tampering, expiry, cross-context tokens, wrong keys, and
malformed payloads must all be rejected; the secrets it carries must not be
readable from the token itself.
"""

from __future__ import annotations

import base64
import hashlib
import json
import time

import pytest

from app.core.config import settings
from app.core.encryption import (
    SALT_OIDC_CLIENT_SECRET,
    SALT_OIDC_FLOW_STATE,
    _get_fernet,
    encrypt_field,
)
from app.services.auth.oidc.flow_state import (
    FlowStateError,
    OidcFlowState,
    create_flow_state,
    decode_flow_state,
)

pytestmark = pytest.mark.unit


# --- round-trip ---------------------------------------------------------------


def test_round_trip():
    state, payload = create_flow_state(mobile=True, device_name="Léa's Pixel 9")
    decoded = decode_flow_state(state)
    assert decoded == payload
    assert decoded.mobile is True
    assert decoded.device_name == "Léa's Pixel 9"


def test_defaults_round_trip():
    state, payload = create_flow_state()
    decoded = decode_flow_state(state)
    assert decoded.mobile is False
    assert decoded.device_name == ""
    assert decoded.code_verifier == payload.code_verifier
    assert decoded.nonce == payload.nonce


def test_each_flow_is_unique():
    s1, p1 = create_flow_state()
    s2, p2 = create_flow_state()
    assert s1 != s2
    assert p1.code_verifier != p2.code_verifier
    assert p1.nonce != p2.nonce


# --- confidentiality ----------------------------------------------------------


def test_secrets_not_readable_from_state_token():
    """The whole point of encrypting: the verifier and nonce must not appear in
    the state string that transits the browser."""
    state, payload = create_flow_state(device_name="pixel")
    assert payload.code_verifier not in state
    assert payload.nonce not in state
    assert "pixel" not in state


# --- PKCE correctness -----------------------------------------------------------


def test_code_challenge_is_rfc7636_s256():
    _, payload = create_flow_state()
    expected = (
        base64.urlsafe_b64encode(
            hashlib.sha256(payload.code_verifier.encode("ascii")).digest()
        )
        .rstrip(b"=")
        .decode("ascii")
    )
    assert payload.code_challenge == expected
    assert "=" not in payload.code_challenge  # unpadded per the RFC


def test_verifier_meets_rfc7636_requirements():
    _, payload = create_flow_state()
    assert 43 <= len(payload.code_verifier) <= 128
    allowed = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~")
    assert set(payload.code_verifier) <= allowed


# --- rejection paths ------------------------------------------------------------


def test_tampered_state_rejected():
    state, _ = create_flow_state()
    i = len(state) // 2
    tampered = state[:i] + ("A" if state[i] != "A" else "B") + state[i + 1 :]
    with pytest.raises(FlowStateError):
        decode_flow_state(tampered)


def test_expired_state_rejected():
    payload = json.dumps(
        {"code_verifier": "v" * 43, "nonce": "n", "mobile": False, "device_name": ""}
    )
    fernet = _get_fernet(SALT_OIDC_FLOW_STATE, settings.SECRET_KEY)
    old = fernet.encrypt_at_time(
        payload.encode(), current_time=int(time.time()) - 3600
    ).decode()
    with pytest.raises(FlowStateError):
        decode_flow_state(old, max_age_seconds=600)


def test_cross_context_token_rejected():
    """A Fernet token minted under a different salt (e.g. an encrypted client
    secret) must not decode as flow state."""
    other = encrypt_field('{"code_verifier":"v","nonce":"n"}', SALT_OIDC_CLIENT_SECRET)
    with pytest.raises(FlowStateError):
        decode_flow_state(other)


def test_token_from_different_secret_key_rejected():
    other = encrypt_field(
        '{"code_verifier":"v","nonce":"n"}',
        SALT_OIDC_FLOW_STATE,
        secret_key="a-different-secret-key",
    )
    with pytest.raises(FlowStateError):
        decode_flow_state(other)


@pytest.mark.parametrize("state", ["", "garbage", "gAAAAA..not-a-token"])
def test_missing_or_garbage_state_rejected(state):
    with pytest.raises(FlowStateError):
        decode_flow_state(state)


def test_valid_token_with_non_json_payload_rejected():
    token = encrypt_field("not json", SALT_OIDC_FLOW_STATE)
    with pytest.raises(FlowStateError):
        decode_flow_state(token)


def test_valid_token_missing_required_field_rejected():
    token = encrypt_field('{"nonce":"n"}', SALT_OIDC_FLOW_STATE)  # no code_verifier
    with pytest.raises(FlowStateError):
        decode_flow_state(token)


# --- dataclass behavior ---------------------------------------------------------


def test_flow_state_is_immutable():
    _, payload = create_flow_state()
    # setattr rather than direct assignment: the runtime frozen-dataclass check is
    # what's under test, and static checkers rightly refuse the assignment form.
    with pytest.raises(AttributeError):
        setattr(payload, "nonce", "overwritten")


def test_challenge_is_deterministic_for_a_verifier():
    a = OidcFlowState(code_verifier="v" * 43, nonce="n")
    b = OidcFlowState(code_verifier="v" * 43, nonce="m")
    assert a.code_challenge == b.code_challenge
