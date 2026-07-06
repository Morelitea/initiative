"""OpenID Connect relying-party building blocks.

Kept as small, independently-testable units — the security-critical
``id_token`` verifier (:mod:`app.services.auth.oidc.id_token`) has no network
dependency so it can be exercised adversarially in isolation. Discovery, the
JWKS key resolver, PKCE/nonce, and the ``OidcProvider`` that composes them land
in follow-up slices.
"""

from app.services.auth.oidc.id_token import (
    IdTokenVerificationError,
    verify_id_token,
)

__all__ = ["IdTokenVerificationError", "verify_id_token"]
