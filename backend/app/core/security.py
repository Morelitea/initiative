import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Sequence

import bcrypt
import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core.config import settings

# Deliberately a constant, not a setting: every encode/verify in this module
# assumes HS256, and a configurable JWT algorithm invites algorithm-confusion.
JWT_ALGORITHM = "HS256"

# Cookie names are part of the auth contract, not deployment configuration.
SESSION_COOKIE_NAME = "session_token"
# The rotating refresh token rides in its own HttpOnly cookie, path-scoped to
# the auth routes (sent only on refresh/logout, never on ordinary API calls —
# smaller exposure than the session cookie).
REFRESH_COOKIE_NAME = "refresh_token"

# argon2id with library defaults — OWASP-aligned. Stored hashes embed the
# parameters, so verification keeps working if we tune these later.
_argon2_hasher = PasswordHasher()


def get_password_hash(password: str) -> str:
    """Hash a plaintext password using argon2id."""
    return _argon2_hasher.hash(password)


def verify_password(plain_password: str, hashed_password: str | None) -> bool:
    """Verify a plaintext password against either an argon2id or legacy bcrypt hash.

    A ``None`` hash means the account has no password (SSO-only) — never a
    match, so every caller gets uniform "incorrect credentials" behavior
    without a separate check. Existing users still have bcrypt hashes from the
    passlib era; those are verified directly with the bcrypt library. The login
    flow rehashes them as argon2id on next successful login (see
    ``password_needs_rehash``).
    """
    if hashed_password is None:
        return False
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


def password_needs_rehash(hashed_password: str | None) -> bool:
    """Return True if the stored hash should be rewritten on next successful login.

    Triggers for legacy bcrypt hashes and for argon2 hashes whose parameters
    have drifted from the current PasswordHasher defaults. ``None`` (no
    password set) has nothing to rehash.
    """
    if hashed_password is None:
        return False
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
    return jwt.encode(to_encode, settings.jwt_signing_key, algorithm=JWT_ALGORITHM)


# ──────────────────────────────────────────────────────────────────────────
# New login model — stateless access token (auth rewrite, Phase 0)
#
# A short-lived JWT that names both the user AND the server-side session
# (``auth_sessions.id``) that backs it, plus the auth methods/providers that
# session satisfied. It is verified locally (no per-request DB hit — the 10k+
# win) and made revocable by its paired refresh token, whose rotation lives in
# ``app.services.auth.sessions``. Its distinct ``aud`` keeps it from being
# confused with the legacy session JWT, the upload token, or the handoff token
# during the dual-verify cutover window (verification lands with the endpoint).
# ──────────────────────────────────────────────────────────────────────────

# Audience/issuer that mark a token as a new-model access credential. The
# session-JWT verification path (added with ``/auth/refresh``) MUST check both,
# and the upload/handoff paths already reject anything carrying this audience.
AUTH_ACCESS_AUDIENCE = "initiative:access"
AUTH_TOKEN_ISSUER = "initiative"


def mint_access_token(
    *,
    user_id: int,
    token_version: int,
    session_id: uuid.UUID,
    amr: list[str],
    satisfied_providers: list[int],
    expires_in: timedelta | None = None,
    now: datetime | None = None,
) -> tuple[str, int]:
    """Mint a short-lived, stateless access token for one session.

    Claims (history/auth-detailed-design.md §3.1): ``sub`` (user id), ``sid``
    (the ``auth_sessions`` row), ``ver`` (``users.token_version`` — coarse "sign
    out everywhere"), ``amr`` (auth methods satisfied), ``sat`` (satisfied-auth
    provider ids → the per-guild auth-policy gate), plus ``iss``/``aud``/
    ``iat``/``exp``. Returns ``(token, expires_in_seconds)`` so the caller can
    schedule a refresh before it lapses.
    """
    issued = now or datetime.now(timezone.utc)
    ttl = expires_in or timedelta(minutes=settings.AUTH_ACCESS_TTL_MINUTES)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "sid": str(session_id),
        "ver": token_version,
        "amr": amr,
        "sat": satisfied_providers,
        "iss": AUTH_TOKEN_ISSUER,
        "aud": AUTH_ACCESS_AUDIENCE,
        "iat": int(issued.timestamp()),
        "exp": issued + ttl,
    }
    token = jwt.encode(payload, settings.jwt_signing_key, algorithm=JWT_ALGORITHM)
    return token, int(ttl.total_seconds())


def decode_session_token(token: str) -> dict[str, Any]:
    """Decode a session credential, accepting BOTH schemes during the
    dual-verify cutover window (history/auth-detailed-design.md §3.1):

    - the **new-model access token** — ``aud=initiative:access`` /
      ``iss=initiative``, additionally carrying ``sid``/``amr``/``sat``.
    - the **legacy session JWT** — no ``aud``/``iss``.

    Both carry ``sub`` + ``ver`` (the caller checks ``ver`` against
    ``users.token_version``). Raises :class:`jwt.PyJWTError` for anything else,
    which every call site already maps to 401. Crucially this keeps the session
    path refusing **scoped** tokens: an upload/handoff token carries a *foreign*
    ``aud`` that fails the new decode (wrong audience) AND the legacy decode
    (which rejects any token bearing an ``aud``), so neither is honored as a
    session. Bad signature / expiry / missing claims raise as before.

    New scheme is tried first, so once issuance flips it's the single-decode
    fast path; during the window a legacy token pays one extra HMAC verify.
    """
    try:
        return jwt.decode(
            token,
            settings.jwt_signing_key,
            algorithms=[JWT_ALGORITHM],
            audience=AUTH_ACCESS_AUDIENCE,
            issuer=AUTH_TOKEN_ISSUER,
            options={"require": ["exp", "sub", "ver", "aud", "iss"]},
        )
    except (
        jwt.InvalidAudienceError,
        jwt.InvalidIssuerError,
        jwt.MissingRequiredClaimError,
    ):
        # These three mean "not a new-model token" — absent/foreign aud or iss,
        # or missing the new claims — so fall back to the legacy scheme. An
        # expired/invalid-signature/malformed JWT raises a *different* PyJWTError
        # (ExpiredSignature/InvalidSignature/Decode) that is NOT caught here, so
        # it propagates with its true type instead of being masked by the
        # legacy decode's audience error — keeping cutover-window logs honest.
        # A legacy token bearing any aud (upload/handoff) still fails the legacy
        # decode below and is rejected.
        return jwt.decode(token, settings.jwt_signing_key, algorithms=[JWT_ALGORITHM])


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
    satisfied_providers: Sequence[int] = (),
    expires_in: timedelta = UPLOAD_TOKEN_LIFETIME,
) -> tuple[str, int]:
    """Mint a short-lived, uploads-scoped JWT for ``user_id``.

    Returns ``(token, expires_in_seconds)`` so the SPA can schedule a refresh
    before the token lapses. Signed with the same HS256 JWT key as the session
    JWT but distinguished by its ``aud``/``scope`` claims and the absence of
    ``ver`` — the general auth path will not accept it.

    ``satisfied_providers`` copies the minting session's ``sat`` claim so a
    download/keepalive in a policy-gated guild carries the same satisfaction
    as the session that requested it (bounded by this token's short lifetime).
    """
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "aud": UPLOAD_TOKEN_AUDIENCE,
        "scope": UPLOAD_TOKEN_SCOPE,
        "sat": [int(pid) for pid in satisfied_providers],
        "iat": int(now.timestamp()),
        "exp": now + expires_in,
    }
    token = jwt.encode(payload, settings.jwt_signing_key, algorithm=JWT_ALGORITHM)
    return token, int(expires_in.total_seconds())


def verify_upload_token(token: str) -> tuple[int, frozenset[int]]:
    """Verify a scoped upload token; return the user id and satisfied set.

    Raises :class:`UploadTokenError` on any failure (bad signature, expired,
    wrong audience, missing/extra-scoped claims). The caller treats that as
    "this isn't a valid upload token" and 401s — it never falls back to
    accepting it as a session credential.
    """
    try:
        payload = jwt.decode(
            token,
            settings.jwt_signing_key,
            algorithms=[JWT_ALGORITHM],
            audience=UPLOAD_TOKEN_AUDIENCE,
            options={"require": ["exp", "iat", "sub", "aud"]},
        )
    except jwt.PyJWTError as exc:
        raise UploadTokenError(str(exc)) from exc

    if payload.get("scope") != UPLOAD_TOKEN_SCOPE:
        raise UploadTokenError("not an uploads-scoped token")

    sub = payload.get("sub")
    try:
        user_id = int(sub)
    except (TypeError, ValueError) as exc:
        raise UploadTokenError("sub must be a numeric user id") from exc
    try:
        satisfied = frozenset(int(pid) for pid in payload.get("sat") or ())
    except (TypeError, ValueError) as exc:
        raise UploadTokenError("sat must be a list of provider ids") from exc
    return user_id, satisfied


class HandoffSigningNotConfiguredError(RuntimeError):
    """Raised when a handoff token is requested but no RS256 signing key is
    configured. The token is verified by a separate service, so there is no
    symmetric fallback — the caller must translate this into a fail-closed
    response (503) rather than mint an unverifiable token."""


def _resolve_handoff_signing_material() -> tuple[str, str, str | None]:
    """Return (private_key_pem, "RS256", kid) for signing handoff JWTs.

    Handoff tokens cross a trust boundary: the receiving service verifies them
    with the public half of this key, so they are always RS256 — never a
    symmetric scheme that would force sharing a secret across that boundary.
    Set HANDOFF_SIGNING_KEY_ID for a stable ``kid`` so the receiver can pick
    the right verifying key out of a JWKS during rotation.

    Fails closed (raises) when no key is configured: a deployment that links a
    companion service must also supply HANDOFF_SIGNING_PRIVATE_KEY_PEM.
    """
    private_pem = settings.HANDOFF_SIGNING_PRIVATE_KEY_PEM
    if not private_pem:
        raise HandoffSigningNotConfiguredError(
            "HANDOFF_SIGNING_PRIVATE_KEY_PEM is required to mint handoff tokens"
        )
    return private_pem, "RS256", settings.HANDOFF_SIGNING_KEY_ID


BILLING_PORTAL_AUDIENCE = "initiative:billing-portal"

# This handoff's lifetime, owned here like the support handoff's below. Used
# both as the default ``expires_in`` and as the value the function reports back,
# so the response's ``expires_in_seconds`` and the JWT's ``exp`` claim can never
# disagree.
BILLING_PORTAL_HANDOFF_LIFETIME = timedelta(seconds=60)


def create_billing_portal_handoff_token(
    *,
    user_id: int,
    guild_id: int,
    guild_role: str,
    expires_in: timedelta = BILLING_PORTAL_HANDOFF_LIFETIME,
) -> tuple[str, int]:
    """Mint the billing-portal handoff token (RS256; raises if unconfigured)."""
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "jti": str(uuid.uuid4()),
        "sub": str(user_id),
        "aud": BILLING_PORTAL_AUDIENCE,
        "iss": "initiative",
        "iat": int(now.timestamp()),
        "exp": now + expires_in,
        "guild_id": guild_id,
        "guild_role": guild_role,
    }
    key, algorithm, kid = _resolve_handoff_signing_material()
    headers: dict[str, Any] | None = {"kid": kid} if kid else None
    token = jwt.encode(payload, key, algorithm=algorithm, headers=headers)
    return token, int(expires_in.total_seconds())


class AppPlatformSigningNotConfiguredError(RuntimeError):
    """Raised when app-platform signing material is needed but absent.

    The app platform has its own dedicated keypair and deliberately no
    fallback to any other configured key: an app verifies context JWTs against
    the published public half, and two boundaries sharing one key would share
    one rotation. Callers translate this into a fail-closed 503.
    """


def app_platform_signing_enabled() -> bool:
    """True when this deployment can sign for the app platform."""
    return bool(settings.APP_PLATFORM_SIGNING_PRIVATE_KEY_PEM)


def resolve_app_platform_signing_material() -> tuple[str, str, str | None]:
    """Return (private_key_pem, "RS256", kid) for app-platform tokens."""
    private_pem = settings.APP_PLATFORM_SIGNING_PRIVATE_KEY_PEM
    if not private_pem:
        raise AppPlatformSigningNotConfiguredError(
            "APP_PLATFORM_SIGNING_PRIVATE_KEY_PEM is required to run the app "
            "platform; it has no fallback to another service's key"
        )
    return private_pem, "RS256", settings.APP_PLATFORM_SIGNING_KEY_ID


def app_platform_audience(public_id: str) -> str:
    """The ``aud`` a token minted for one app service carries."""
    return f"{settings.APP_PLATFORM_AUDIENCE_PREFIX}{public_id}"


# Pinned on both sides of the boundary — not deployment knobs.
BILLING_SUPPORT_HANDOFF_ISSUER = "initiative"
BILLING_SUPPORT_HANDOFF_AUDIENCE = "initiative:billing-support"

# Lifetime of a billing-support handoff, and the ceiling the receiver accepts.
BILLING_SUPPORT_HANDOFF_LIFETIME = timedelta(seconds=60)
BILLING_SUPPORT_HANDOFF_MAX_LIFETIME = timedelta(seconds=300)


class BillingSupportHandoffNotConfiguredError(RuntimeError):
    """Raised when a billing-support handoff is requested but the shared
    signing material is absent. Fails closed — the caller returns 503."""


def billing_support_handoff_enabled() -> bool:
    """True when this deployment can mint billing-support handoffs."""
    return bool(
        settings.BILLING_SUPPORT_HANDOFF_SECRET and settings.BILLING_SUPPORT_HANDOFF_KID
    )


def create_billing_support_handoff_token(
    *,
    user_id: int,
    guild_id: int,
    grant_id: int | str,
    approver_id: int | str | None = None,
    expires_in: timedelta = BILLING_SUPPORT_HANDOFF_LIFETIME,
) -> tuple[str, int]:
    """Mint the billing-support handoff token.

    ``grant_id`` names the ``access_grants`` row that authorises the visit, so
    both sides log the same grant.
    """
    if not billing_support_handoff_enabled():
        raise BillingSupportHandoffNotConfiguredError(
            "BILLING_SUPPORT_HANDOFF_SECRET and _KID are required to mint "
            "billing-support handoffs"
        )
    lifetime = min(expires_in, BILLING_SUPPORT_HANDOFF_MAX_LIFETIME)
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "jti": str(uuid.uuid4()),
        "sub": str(user_id),
        "aud": BILLING_SUPPORT_HANDOFF_AUDIENCE,
        "iss": BILLING_SUPPORT_HANDOFF_ISSUER,
        "iat": int(now.timestamp()),
        "exp": int((now + lifetime).timestamp()),
        "guild_id": int(guild_id),
        "grant_id": str(grant_id),
    }
    if approver_id is not None:
        payload["approver"] = str(approver_id)
    token = jwt.encode(
        payload,
        settings.BILLING_SUPPORT_HANDOFF_SECRET,
        algorithm="HS256",
        headers={"kid": settings.BILLING_SUPPORT_HANDOFF_KID},
    )
    return token, int(lifetime.total_seconds())


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


def auto_delegation_configured() -> bool:
    """True when this deployment has an automation delegate.

    The delegate is identified by the public half of its signing key, so the
    presence of that key is what "a delegate exists here" means. Single source
    of truth for every surface that is delegate-owned: the subscription
    endpoints refuse without it and the outbound dispatcher stays inert.
    """
    return bool(settings.AUTO_DELEGATION_PUBLIC_KEY_PEM)


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
