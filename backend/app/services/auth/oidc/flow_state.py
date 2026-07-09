"""PKCE + nonce generation and the encrypted OIDC login-flow state.

One login attempt's transient secrets — the PKCE ``code_verifier`` and the
id_token ``nonce`` — must round-trip from ``begin`` (the redirect to the IdP)
to ``complete`` (the callback). They travel in the ``state`` parameter as a
**Fernet-encrypted** payload: confidential (nothing readable in redirect URLs
or logs), tamper-proof, and TTL-bound via the token's authenticated timestamp.
Stateless — nothing is stored server-side, so it works across replicas; a
``SECRET_KEY`` rotation simply invalidates in-flight logins (they retry).

``create_flow_state()`` mints the state + payload; ``decode_flow_state()``
returns the payload or raises :class:`FlowStateError` (fail-closed). The
``code_challenge`` sent to the IdP is derived with S256 (RFC 7636).
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
from dataclasses import dataclass

from cryptography.fernet import InvalidToken

from app.core.encryption import SALT_OIDC_FLOW_STATE, decrypt_field, encrypt_field

# One login attempt should complete well within this window; older state is
# rejected (the user just signs in again).
DEFAULT_MAX_AGE_SECONDS: int = 600

# 64 random bytes -> 86 urlsafe chars, within RFC 7636's 43-128 verifier length.
_VERIFIER_BYTES: int = 64
_NONCE_BYTES: int = 32

# device_name is a client-supplied display label that rides inside the state
# param and thus the authorization URL — cap it so it can't inflate the URL.
DEVICE_NAME_MAX_CHARS: int = 64


class FlowStateError(Exception):
    """The flow state is missing, expired, or invalid; the login attempt must
    be rejected (fail-closed)."""


@dataclass(frozen=True)
class OidcFlowState:
    """The per-login-attempt payload carried (encrypted) in ``state``."""

    code_verifier: str
    nonce: str
    mobile: bool = False
    device_name: str = ""

    @property
    def code_challenge(self) -> str:
        """S256 challenge for ``code_verifier`` (RFC 7636 §4.2)."""
        digest = hashlib.sha256(self.code_verifier.encode("ascii")).digest()
        return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def create_flow_state(
    *, mobile: bool = False, device_name: str = ""
) -> tuple[str, OidcFlowState]:
    """Generate a fresh verifier + nonce and return ``(state, payload)`` —
    ``state`` is the encrypted token to send to the IdP, ``payload`` supplies
    the ``code_challenge`` and ``nonce`` for the authorization request.
    ``device_name`` is truncated to :data:`DEVICE_NAME_MAX_CHARS` (a display
    label, not an identifier)."""
    payload = OidcFlowState(
        code_verifier=secrets.token_urlsafe(_VERIFIER_BYTES),
        nonce=secrets.token_urlsafe(_NONCE_BYTES),
        mobile=mobile,
        device_name=device_name[:DEVICE_NAME_MAX_CHARS],
    )
    plaintext = json.dumps(
        {
            "code_verifier": payload.code_verifier,
            "nonce": payload.nonce,
            "mobile": payload.mobile,
            "device_name": payload.device_name,
        },
        separators=(",", ":"),
    )
    return encrypt_field(plaintext, SALT_OIDC_FLOW_STATE), payload


def decode_flow_state(
    state: str, *, max_age_seconds: int = DEFAULT_MAX_AGE_SECONDS
) -> OidcFlowState:
    """Decrypt and validate the callback's ``state``, or raise
    :class:`FlowStateError` (expired, tampered, wrong key/salt, malformed)."""
    if not state:
        raise FlowStateError("missing flow state")
    try:
        plaintext = decrypt_field(
            state, SALT_OIDC_FLOW_STATE, ttl_seconds=max_age_seconds
        )
    # UnicodeDecodeError: decrypt_field decodes the plaintext as UTF-8, and this
    # function's contract is FlowStateError for every invalid input.
    except (InvalidToken, UnicodeDecodeError) as exc:
        raise FlowStateError("invalid or expired flow state") from exc
    try:
        data = json.loads(plaintext)
        decoded = OidcFlowState(
            code_verifier=data["code_verifier"],
            nonce=data["nonce"],
            mobile=bool(data.get("mobile", False)),
            device_name=str(data.get("device_name", ""))[:DEVICE_NAME_MAX_CHARS],
        )
    except (ValueError, KeyError, TypeError) as exc:
        raise FlowStateError("malformed flow state payload") from exc
    # A flow state exists to carry these two secrets; empty ones are malformed
    # (and downstream verification treats them as caller errors, not bad input).
    if not isinstance(decoded.code_verifier, str) or not decoded.code_verifier:
        raise FlowStateError("malformed flow state payload")
    if not isinstance(decoded.nonce, str) or not decoded.nonce:
        raise FlowStateError("malformed flow state payload")
    return decoded
