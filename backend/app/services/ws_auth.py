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

from app.core.config import settings
from app.models.user import User, UserStatus
from app.schemas.token import TokenPayload
from app.services import user_tokens


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
    """
    # First try JWT validation.
    try:
        payload = jwt.decode(
            token, settings.jwt_signing_key, algorithms=[settings.ALGORITHM]
        )
        token_data = TokenPayload(**payload)
        if token_data.sub:
            statement = select(User).where(User.id == int(token_data.sub))
            result = await session.exec(statement)
            user = result.one_or_none()
            if (
                user
                and user.status == UserStatus.active
                and token_data.ver is not None
                and token_data.ver == user.token_version
            ):
                return user
        # Any string that decodes as one of our JWTs is a session token. A
        # revoked one (stale/absent ``ver``), an unknown/inactive user, or a
        # payload with no ``sub`` at all must not silently fall through to the
        # device-token path below — the bearer here is a session JWT, not a
        # device token.
        return None
    except jwt.PyJWTError:
        pass

    # Fall back to device token validation.
    device_token = await user_tokens.get_device_token(session, token=token)
    if device_token:
        statement = select(User).where(User.id == device_token.user_id)
        result = await session.exec(statement)
        user = result.one_or_none()
        if user and user.status == UserStatus.active:
            return user

    return None
