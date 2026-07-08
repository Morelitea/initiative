"""OpenID Connect relying-party building blocks.

Small, independently-testable units — discovery, the id_token verifier, and the
JWKS key resolver so far; PKCE/nonce and the ``OidcProvider`` that composes them
land in follow-up slices.
"""

from app.services.auth.oidc.discovery import (
    DiscoveryError,
    OidcDiscovery,
    OidcMetadata,
)
from app.services.auth.oidc.id_token import (
    IdTokenVerificationError,
    verify_id_token,
)
from app.services.auth.oidc.jwks import JwksResolutionError, JwksResolver

__all__ = [
    "DiscoveryError",
    "IdTokenVerificationError",
    "JwksResolutionError",
    "JwksResolver",
    "OidcDiscovery",
    "OidcMetadata",
    "verify_id_token",
]
