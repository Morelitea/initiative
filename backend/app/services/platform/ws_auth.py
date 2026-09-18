"""Shared WebSocket authentication helper.

The four realtime WebSocket endpoints (events, counters, queues,
collaboration) all authenticate the first message identically: try the
bearer string as a session JWT, fall back to a device token, and require
the resolved user to be ``active``.

Previously each endpoint inlined this logic and only checked
``status == active`` on the JWT path — they never compared the token's
``ver`` claim to ``user.token_version``. That let a stolen-but-unexpired
session JWT keep opening realtime sockets after logout / password reset /
password change (all of which revoke purely by bumping ``token_version``),
even though the HTTP path (``app.api.deps.get_current_user``) rejected the
same token.

Factoring the validate-and-load step into this single helper keeps the
WS paths in lockstep with the HTTP path so the ``token_version`` check
can't silently drift out of one of them again.
"""

from typing import Optional

import jwt
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.auth_context import (
    claims_from_provider_auth,
    set_satisfied_claims,
    set_satisfied_providers,
)
from app.core.security import decode_session_token
from app.models.platform.user import User, UserStatus
from app.schemas.platform.token import TokenPayload
from app.services.auth.subject import user_for_subject
from app.services.platform import user_tokens


def _is_a_jwt(token: str) -> bool:
    """Whether ``token`` is a JWT, whatever it says and whoever signed it.

    Asked of the library rather than of the string's shape, so this agrees
    with what the decode above was trying to read.
    """
    try:
        jwt.get_unverified_header(token)
    except jwt.PyJWTError:
        return False
    return True


async def authenticate_ws_token(token: str, session: AsyncSession) -> Optional[User]:
    """Validate a session JWT or device token and return the active user.

    Returns ``None`` (rather than raising) when authentication fails so
    callers can close the socket with a policy-violation code.

    Session JWTs must carry a ``ver`` claim matching the user's current
    ``token_version`` — this mirrors ``get_current_user`` so logout /
    password reset / password change (which bump ``token_version``)
    revoke realtime sockets too. Device tokens are revoked separately
    (consumed / expired in the database) and are validated by
    ``user_tokens.get_device_token``.

    Like the HTTP validators, this records the credential's satisfied-provider
    set in ``app.core.auth_context`` (empty for device tokens and legacy JWTs),
    so the ``establish_guild_access`` call that follows applies the guild
    auth-policy gate to the socket exactly as REST would.
    """
    set_satisfied_providers(None)
    set_satisfied_claims(None)

    # First try JWT validation.
    try:
        payload = decode_session_token(token)
        token_data = TokenPayload(**payload)
        if token_data.sub:
            user = await user_for_subject(session, subject=token_data.sub)
            if (
                user
                and user.status == UserStatus.active
                and token_data.ver is not None
                and token_data.ver == user.token_version
            ):
                set_satisfied_providers(frozenset(token_data.sat or ()))
                set_satisfied_claims(claims_from_provider_auth(token_data.satd))
                return user
        # A session token that resolved nobody — revoked by ``ver``, naming an
        # unknown or inactive account — is refused here rather than offered to
        # the device-token path below.
        return None
    except jwt.PyJWTError:
        # And so is one that did not decode. A device token is an opaque
        # ``secrets.token_urlsafe`` value, so a bearer that parses as a JWT is
        # somebody presenting a session credential whatever is wrong with it;
        # only a string that is no JWT at all can be the other kind.
        if _is_a_jwt(token):
            return None

    # Fall back to device token validation.
    device_token = await user_tokens.get_device_token(session, token=token)
    if device_token:
        statement = select(User).where(User.id == device_token.user_id)
        result = await session.exec(statement)
        user = result.one_or_none()
        if user and user.status == UserStatus.active:
            return user

    return None
