"""OpenID Connect relying-party building blocks.

Small, independently-testable units — the id_token verifier and the JWKS key
resolver so far; discovery, PKCE/nonce, and the ``OidcProvider`` that composes
them land in follow-up slices.
"""

from app.services.auth.oidc.id_token import (
    IdTokenVerificationError,
    verify_id_token,
)
from app.services.auth.oidc.jwks import JwksResolutionError, JwksResolver

__all__ = [
    "IdTokenVerificationError",
    "JwksResolutionError",
    "JwksResolver",
    "verify_id_token",
]
