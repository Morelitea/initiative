import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from passlib.context import CryptContext

from app.core.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def create_access_token(subject: str, *, token_version: int, expires_delta: timedelta | None = None) -> str:
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode: dict[str, Any] = {"sub": subject, "exp": expire, "ver": token_version}
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


# Audience claim for tokens minted for the embedded advanced-tool iframe.
# The receiving service MUST verify ``aud`` matches this value before
# trusting the token. Setting it prevents replay of regular session
# tokens against the iframe backend, and vice versa.
ADVANCED_TOOL_AUDIENCE = "initiative:advanced-tool"

# Single source of truth for the handoff token's lifetime. Used both as
# the default ``expires_in`` and as the value the function reports back
# to callers, so ``AdvancedToolHandoffResponse.expires_in_seconds`` and
# the JWT's ``exp`` claim can never disagree.
ADVANCED_TOOL_HANDOFF_LIFETIME = timedelta(seconds=60)


def _resolve_handoff_signing_material() -> tuple[str, str, str | None]:
    """Pick (key, algorithm, kid) for signing advanced-tool handoff JWTs.

    Default: HS256 with SECRET_KEY — works out of the box for OSS but
    requires sharing the secret with the embed backend (single point of
    compromise).

    Preferred: RS256 with HANDOFF_SIGNING_PRIVATE_KEY_PEM — FOSS holds
    the private key, the embed verifies with the matching public key.
    A leak on the embed side cannot forge tokens, and rotation is just
    a key swap. Set HANDOFF_SIGNING_KEY_ID for a stable ``kid`` so the
    embed can pick the right verifying key out of a JWKS.
    """
    private_pem = settings.HANDOFF_SIGNING_PRIVATE_KEY_PEM
    if private_pem:
        return private_pem, "RS256", settings.HANDOFF_SIGNING_KEY_ID
    return settings.SECRET_KEY, "HS256", None


def create_advanced_tool_handoff_token(
    *,
    user_id: int,
    guild_id: int,
    guild_role: str,
    is_manager: bool,
    can_create: bool,
    scope: str,
    initiative_id: int | None = None,
    expires_in: timedelta = ADVANCED_TOOL_HANDOFF_LIFETIME,
) -> tuple[str, int]:
    """Mint a short-lived JWT used by the SPA to bootstrap the embedded
    advanced-tool iframe.

    The flow:
      1. SPA calls the handoff endpoint after the user opens the panel.
      2. Backend validates membership + master switch + URL config.
      3. Backend returns this token, which the SPA passes to the iframe via
         postMessage (never a query string).
      4. The iframe's backend verifies the token (RS256 public key OR
         HS256 shared secret), confirms ``aud == ADVANCED_TOOL_AUDIENCE``,
         and exchanges it for its own session. The ``jti`` claim is used
         as a one-shot guard — once exchanged, the embed must reject any
         repeat presentation of the same token within the 60s window.

    ``scope`` is "initiative" or "guild". For guild scope the iframe is
    used by guild admins only and there is no ``initiative_id``. The
    receiving service MUST trust this claim (not the URL query param)
    when deciding which view to render.

    The token is intentionally short-lived so a leak (browser history,
    accidental log capture) has minimal blast radius. Long-lived auth
    lives in the iframe's own session, not in this handoff.

    Returns the encoded JWT plus the integer seconds until expiry, so the
    handoff response can advertise the same lifetime that's encoded in
    the token's ``exp`` claim.
    """
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        # Unique per-token identifier so the embed can blocklist a token
        # after it's been exchanged once. Without this, the same token
        # could be redeemed multiple times within its 60s lifetime.
        "jti": str(uuid.uuid4()),
        "sub": str(user_id),
        "aud": ADVANCED_TOOL_AUDIENCE,
        "iss": "initiative",
        "iat": int(now.timestamp()),
        "exp": now + expires_in,
        # Context the receiver needs to scope the session it issues.
        "guild_id": guild_id,
        "guild_role": guild_role,
        "is_manager": is_manager,
        "scope": scope,
        # Forwarded so the proprietary backend can hide create UI for
        # members whose role doesn't grant create_advanced_tool. View
        # access is implied by the fact that we issued this token at all.
        "can_create": can_create,
    }
    if initiative_id is not None:
        payload["initiative_id"] = initiative_id

    key, algorithm, kid = _resolve_handoff_signing_material()
    headers: dict[str, Any] | None = {"kid": kid} if kid else None
    token = jwt.encode(payload, key, algorithm=algorithm, headers=headers)
    return token, int(expires_in.total_seconds())
