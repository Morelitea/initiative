"""Auth service package for the login rewrite (history/auth-detailed-design.md).

Phase 0 lands the session lifecycle here; the ``IdentityProvider`` seam and the
per-provider implementations slot in alongside it in later slices.
"""

from app.services.auth.sessions import (
    IssuedSession,
    RefreshError,
    create_session,
    revoke_all_for_user,
    revoke_chain,
    revoke_session,
    rotate_session,
)

__all__ = [
    "IssuedSession",
    "RefreshError",
    "create_session",
    "rotate_session",
    "revoke_session",
    "revoke_chain",
    "revoke_all_for_user",
]
