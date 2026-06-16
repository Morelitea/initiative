import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core.config import settings

# argon2id with library defaults — OWASP-aligned. Stored hashes embed the
# parameters, so verification keeps working if we tune these later.
_argon2_hasher = PasswordHasher()


def get_password_hash(password: str) -> str:
    """Hash a plaintext password using argon2id."""
    return _argon2_hasher.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plaintext password against either an argon2id or legacy bcrypt hash.

    Existing users still have bcrypt hashes from the passlib era; those are
    verified directly with the bcrypt library. The login flow rehashes them
    as argon2id on next successful login (see ``password_needs_rehash``).
    """
    if hashed_password.startswith("$argon2"):
        try:
            _argon2_hasher.verify(hashed_password, plain_password)
            return True
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            return False
    if hashed_password.startswith(("$2a$", "$2b$", "$2y$")):
        try:
            return bcrypt.checkpw(
                plain_password.encode("utf-8"),
                hashed_password.encode("utf-8"),
            )
        except ValueError:
            return False
    return False


def password_needs_rehash(hashed_password: str) -> bool:
    """Return True if the stored hash should be rewritten on next successful login.

    Triggers for legacy bcrypt hashes and for argon2 hashes whose parameters
    have drifted from the current PasswordHasher defaults.
    """
    if not hashed_password.startswith("$argon2"):
        return True
    try:
        return _argon2_hasher.check_needs_rehash(hashed_password)
    except InvalidHashError:
        return True


def create_access_token(
    subject: str, *, token_version: int, expires_delta: timedelta | None = None
) -> str:
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode: dict[str, Any] = {"sub": subject, "exp": expire, "ver": token_version}
    return jwt.encode(to_encode, settings.jwt_signing_key, algorithm=settings.ALGORITHM)


# ──────────────────────────────────────────────────────────────────────────
# Scoped upload tokens
#
# Native (Capacitor) WebViews can't attach an Authorization header or send the
# HttpOnly session cookie to <img>/<iframe> media loads, so the URL has to carry
# the credential as a ``?token=`` query param. Putting the 7-day session JWT
# there leaks a full-API credential into logs, history, and Referer headers.
# Instead the app mints one of these: a short-lived, uploads-only JWT that the
# /uploads route (and document download routes) accept via ``?token=`` but that
# is useless for any other API call (it carries no ``ver`` and a distinct
# ``aud``/``scope``, so ``get_current_user`` rejects it).
# ──────────────────────────────────────────────────────────────────────────

# Audience + scope claims that mark a token as a scoped upload credential. The
# uploads auth dependency MUST verify both before honoring a query-param token,
# and the general session-JWT path MUST reject any token carrying this audience.
UPLOAD_TOKEN_AUDIENCE = "initiative:uploads"
UPLOAD_TOKEN_SCOPE = "uploads"

# Short lifetime: long enough to render a page's worth of media after the SPA
# fetches one, short enough that a leak (history, Referer, proxy log) is stale
# fast. The SPA refreshes it transparently when it expires.
UPLOAD_TOKEN_LIFETIME = timedelta(minutes=10)


class UploadTokenError(Exception):
    """Raised when a presented upload token fails verification."""


def create_upload_token(
    *,
    user_id: int,
    expires_in: timedelta = UPLOAD_TOKEN_LIFETIME,
) -> tuple[str, int]:
    """Mint a short-lived, uploads-scoped JWT for ``user_id``.

    Returns ``(token, expires_in_seconds)`` so the SPA can schedule a refresh
    before the token lapses. Signed with the same HS256 JWT key as the session
    JWT but distinguished by its ``aud``/``scope`` claims and the absence of
    ``ver`` — the general auth path will not accept it.
    """
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "aud": UPLOAD_TOKEN_AUDIENCE,
        "scope": UPLOAD_TOKEN_SCOPE,
        "iat": int(now.timestamp()),
        "exp": now + expires_in,
    }
    token = jwt.encode(payload, settings.jwt_signing_key, algorithm=settings.ALGORITHM)
    return token, int(expires_in.total_seconds())


def verify_upload_token(token: str) -> int:
    """Verify a scoped upload token and return the user id it names.

    Raises :class:`UploadTokenError` on any failure (bad signature, expired,
    wrong audience, missing/extra-scoped claims). The caller treats that as
    "this isn't a valid upload token" and 401s — it never falls back to
    accepting it as a session credential.
    """
    try:
        payload = jwt.decode(
            token,
            settings.jwt_signing_key,
            algorithms=[settings.ALGORITHM],
            audience=UPLOAD_TOKEN_AUDIENCE,
            options={"require": ["exp", "iat", "sub", "aud"]},
        )
    except jwt.PyJWTError as exc:
        raise UploadTokenError(str(exc)) from exc

    if payload.get("scope") != UPLOAD_TOKEN_SCOPE:
        raise UploadTokenError("not an uploads-scoped token")

    sub = payload.get("sub")
    try:
        return int(sub)
    except (TypeError, ValueError) as exc:
        raise UploadTokenError("sub must be a numeric user id") from exc


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

    Default: HS256 with the JWT signing key — works out of the box for OSS
    but requires sharing the secret with the embed backend (single point of
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
    return settings.jwt_signing_key, "HS256", None


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


# ──────────────────────────────────────────────────────────────────────────
# Inbound delegation from initiative-auto
#
# When auto calls our API on behalf of a user, it presents a JWT signed
# with its private key (RS256). We verify here using the public half
# configured at AUTO_DELEGATION_PUBLIC_KEY_PEM and resolve the JWT to a
# user_id that the auth dependency then loads as a User. From that
# point on the request runs through our normal RLS + role-permission
# stack — the delegation just answers "who is acting", not "what can
# they do".
# ──────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class AutoDelegationClaims:
    """Validated payload of a delegation JWT minted by initiative-auto."""

    jti: str
    user_id: int
    guild_id: int
    initiative_id: int | None
    workflow_id: int | None


class AutoDelegationVerificationError(Exception):
    """Raised when the inbound delegation JWT fails any check."""


def verify_auto_delegation_token(token: str) -> AutoDelegationClaims:
    """Verify a delegation JWT minted by initiative-auto.

    Disabled when ``AUTO_DELEGATION_PUBLIC_KEY_PEM`` is unset — that
    config gap surfaces as a verification error so the auth dep can
    fall through to its other token paths instead of 500'ing.
    """
    if not settings.AUTO_DELEGATION_PUBLIC_KEY_PEM:
        raise AutoDelegationVerificationError("delegation auth not configured")

    try:
        payload = jwt.decode(
            token,
            settings.AUTO_DELEGATION_PUBLIC_KEY_PEM,
            algorithms=["RS256"],
            audience=settings.AUTO_DELEGATION_AUDIENCE,
            issuer=settings.AUTO_DELEGATION_ISSUER,
            options={"require": ["exp", "iat", "iss", "aud", "sub", "jti"]},
        )
    except jwt.PyJWTError as e:
        raise AutoDelegationVerificationError(f"jwt verification failed: {e}") from e

    try:
        user_id = int(payload["sub"])
    except (KeyError, TypeError, ValueError) as e:
        raise AutoDelegationVerificationError(
            f"sub must be a numeric user id: {e}"
        ) from e

    guild_id = payload.get("guild_id")
    if not isinstance(guild_id, int):
        raise AutoDelegationVerificationError("guild_id must be an int")

    initiative_id = payload.get("initiative_id")
    if initiative_id is not None and not isinstance(initiative_id, int):
        raise AutoDelegationVerificationError(
            "initiative_id must be an int when present"
        )

    workflow_id = payload.get("workflow_id")
    if workflow_id is not None and not isinstance(workflow_id, int):
        raise AutoDelegationVerificationError("workflow_id must be an int when present")

    return AutoDelegationClaims(
        jti=str(payload["jti"]),
        user_id=user_id,
        guild_id=guild_id,
        initiative_id=initiative_id,
        workflow_id=workflow_id,
    )
