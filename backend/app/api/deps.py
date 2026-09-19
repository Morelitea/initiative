from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Annotated, Optional

from fastapi import Cookie, Depends, HTTPException, Path, Query, Request, status
from fastapi.security import OAuth2PasswordBearer
import jwt
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.capabilities import Capability, user_has_capability
from app.core.config import API_V1_STR
from app.core.login_methods import LoginMethod
from app.core import auth_context
from app.core.auth_context import (
    set_api_key_credential,
    set_device_token_id,
    set_satisfied_providers,
    set_session_mfa,
    set_session_passkey,
    claims_from_provider_auth,
    set_satisfied_claims,
)
from app.services.auth import guild_provider_connections as guild_connections
from app.services.auth.assurance import SECOND_FACTOR_AMR, carries_passkey
from app.services.platform import auth_posture
from app.core.pam_context import set_active_grant
from app.core.role_context import (
    set_active_role,
    set_content_read_only_guild,
    set_override_sharing_initiatives,
)
from app.core.messages import (
    AuthMessages,
    DirectMessageMessages,
    GuildMessages,
    UserMessages,
)
from app.core.security import (
    SESSION_COOKIE_NAME,
    STEP_UP_CHALLENGE,
    AutoDelegationVerificationError,
    UploadTokenError,
    delegation_possible,
    delegation_token_kid,
    decode_session_token,
    verify_auto_delegation_token,
    verify_upload_token,
)
from app.db.session import (
    SYSTEM_SATISFIED,
    apply_override_initiatives,
    get_session,
    set_rls_context,
)
from app.models.platform.access_grant import (
    AccessGrant,
    AccessGrantPurpose,
    AccessLevel,
    SettingsLevel,
)
from app.models.platform.api_key import UserApiKey
from app.models.platform.guild import (
    GUILD_ADMIN_ROLES,
    Guild,
    GuildMembership,
    GuildRole,
    GuildStatus,
    content_role,
)
from app.models.platform.guild_auth_policy import GuildAuthPolicy
from app.models.platform.user import (
    LOGIN_STATUSES,
    User,
    UserRole,
    UserStatus,
)
from app.schemas.platform.token import TokenPayload
from app.services.auth.subject import user_for_subject
from app.services.platform import access_grants as access_grants_service
from app.services.platform import api_keys as api_keys_service
from app.services.marketplace import registration_lookup
from app.services.platform import auto_delegation_blocklist
from app.services.platform import user_tokens

SessionDep = Annotated[AsyncSession, Depends(get_session)]

oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl=f"{API_V1_STR}/auth/token", auto_error=False
)


_SAFE_HTTP_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

#: Which kind of credential authenticated a request, recorded on
#: ``request.state.credential``. Most endpoints do not care — a person acting
#: through a script is still that person. It matters where the *act* is granting
#: something authority the credential itself carries, because there the
#: credential is a party to the decision rather than a way of transporting it.
CREDENTIAL_SESSION = "session"
CREDENTIAL_API_KEY = "api_key"
CREDENTIAL_DEVICE_TOKEN = "device_token"
CREDENTIAL_DELEGATION = "delegation"

#: The credentials that are somebody signing in, as opposed to something acting
#: for them in their absence. The native app trades an email and password for a
#: device token and then uses it for everything, so it belongs here beside the
#: web session — the person is just as present either way.
FIRST_PARTY_CREDENTIALS = frozenset({CREDENTIAL_SESSION, CREDENTIAL_DEVICE_TOKEN})


async def _authenticate_device_token(
    session: AsyncSession, token: str
) -> Optional[User]:
    """Authenticate using a device token and return the associated user.

    Records which token it was (see ``app.core.auth_context``). That row is the
    server's only durable name for one installed client, and two registrations
    that have to end up pointing at the same phone -- its push token and its
    message key store -- both read it from there rather than being told an id
    by the client.
    """
    device_token = await user_tokens.get_device_token(session, token=token)
    if not device_token:
        return None
    statement = select(User).where(User.id == device_token.user_id)
    result = await session.exec(statement)
    user = result.one_or_none()
    if user is not None:
        set_device_token_id(device_token.id)
    return user


async def _authenticate_auto_delegation(
    request: Request,
    session: AsyncSession,
    token: str,
) -> Optional[User]:
    """Try to interpret ``token`` as a delegation JWT from initiative-auto.

    Returns the named user when the token verifies; ``None`` otherwise so
    the caller can fall through to other auth methods (regular JWT, API
    key, etc.) without 401-ing on what's actually a session-token-shaped
    bearer arriving at the same header.

    Authorization beyond authentication still happens downstream — this
    function only resolves identity. RLS, role-permission checks, and
    master switches gate the actual operation as if the user were
    calling directly.

    Two security checks fire here in order:
      1. Token verifies (signature, audience, issuer, required claims).
      2. ``jti`` is not in the blocklist — first presentation only.

    A verified token also pins the request's guild context. The token names its
    guild by a ``guild_ref`` claim — the reference the app was given, not a row
    id — which is resolved here to the guild it stands for and put on
    ``request.state.delegated_guild_id``: delegation tokens are minted for
    exactly one guild, and a machine caller has no guild context of its own to
    resolve from. The resolved guild is validated against the user's memberships
    and must agree with the ``/g/{guild_id}`` path, so an auto workflow always
    acts in the guild its token was issued for.
    """
    if not delegation_possible():
        return None  # no app platform here — let other auth paths run

    # Which app signed this decides which keys may verify it. The token names a
    # `kid`, and the registrations that published it must be enabled and hold
    # the `delegation` grant, so an operator ends an app's ability to act with
    # an edit rather than a key rotation. Resolving nothing ends the attempt:
    # there is no other key this token could be held against.
    candidates = await registration_lookup.delegation_keys_for(
        delegation_token_kid(token) or ""
    )

    # One candidate at a time, so the app this call is attributed to is the one
    # whose key actually verified. Two apps may publish the same `kid` — it is
    # an opaque label each picks — and everything downstream (which install must
    # exist, which app acted) has to follow the signature, not the order.
    claims = None
    signer = None
    for candidate in candidates:
        try:
            claims = verify_auto_delegation_token(token, keys=[candidate.key])
        except AutoDelegationVerificationError:
            # Could also be a session JWT or API key arriving on the same
            # header; falling through lets the caller try those.
            continue
        signer = candidate
        break

    if claims is None or signer is None:
        return None

    request.state.delegating_app = signer.registration.public_id

    # Replay guard: a delegation JWT is one-shot. Even though the JWT is
    # technically valid for 15 minutes, a captured token must not be
    # usable a second time. The pre-flight ``is_jti_redeemed`` is a fast
    # path; the ``record_jti`` insert below is the actual race-safe
    # guarantee (unique-violation on the PK).
    if await auto_delegation_blocklist.is_jti_redeemed(session, claims.jti):
        return None

    # The token names its guild by reference too, so the id everything below
    # works in is resolved here rather than taken from the token.
    from app.services.marketplace.app_refs import resolve_app_guild_ref

    resolved_guild = await resolve_app_guild_ref(ref=claims.guild_ref)
    if resolved_guild is None:
        return None
    guild_id, install_id = resolved_guild
    # Which install this delegate is, here. The reference it named the guild by
    # was minted for exactly one, so the sector is already settled by the time
    # the token verifies — and a handler that has to name something back to
    # this delegate needs the same sector to name it in.
    request.state.delegating_install_id = install_id

    # The token names its member by the reference the app was given, not by a
    # user id. Resolving it takes both the guild it was minted in and the app
    # that signed, which together are the sector it belongs to.
    resolved = await registration_lookup.resolve_delegated_member(
        guild_id, signer.registration.public_id, claims.subject
    )
    if resolved is None:
        return None

    statement = select(User).where(User.id == resolved)
    result = await session.exec(statement)
    user = result.one_or_none()
    if user is None or user.status != UserStatus.active:
        # The member the subject names has been deactivated since it was
        # minted. A delegate cannot act for a non-active account — workflows
        # die when their owner leaves, by design.
        return None

    # Identity settled, authorization next. Two parties have to have said yes:
    # the guild installed the app, and this member authorized it to carry their
    # name — to the depth this call needs. Checked against the token's own
    # claims rather than the path, so it holds for every route a delegated call
    # can reach, including the cross-guild `/me/*` views that have no path
    # guild.
    #
    # The read/write split follows the request method, the same line
    # `_enforce_api_key_scope` draws for a read-only PAT.
    if not await registration_lookup.delegation_allowed(
        guild_id,
        signer.registration.public_id,
        resolved,
        need_write=request.method not in _SAFE_HTTP_METHODS,
    ):
        return None

    # Burn the jti now. Two requests racing past the pre-flight check
    # collide on the PK and the loser's ``record_jti`` raises
    # ``DelegationReplayError``, which we convert to the same None
    # signal — the request will be re-authenticated by another path or
    # rejected by the standard 401.
    try:
        await auto_delegation_blocklist.record_jti(
            session, jti=claims.jti, expires_at=_delegation_exp_from_jwt(token)
        )
    except auto_delegation_blocklist.DelegationReplayError:
        return None

    # Bind the request to the token's guild (see docstring). Stored on
    # request.state so the guild-context resolver can read it without the
    # claims object having to travel through every auth signature.
    request.state.delegated_guild_id = guild_id

    return user


def _delegation_exp_from_jwt(token: str) -> datetime:
    """Pull the ``exp`` timestamp out of a delegation JWT without
    re-verifying. Caller has already verified — we just need the value
    for the blocklist row's ``expires_at`` column so the cleanup job
    can prune expired entries.
    """
    payload = jwt.decode(token, options={"verify_signature": False})
    return datetime.fromtimestamp(int(payload["exp"]), tz=timezone.utc)


def _enforce_api_key_scope(request: Request, api_key: UserApiKey) -> None:
    """Apply a scoped PAT's restrictions at authentication time.

    ``read_only`` keys may only issue safe (non-mutating) HTTP methods. A
    ``guild_id``-bound key stashes its guild on ``request.state`` for
    ``get_guild_membership`` to pin against the ``/g/{guild_id}`` path — the one
    place that sees both the token's guild and the path's, mirroring how
    delegation tokens are pinned.
    """
    if api_key.read_only and request.method not in _SAFE_HTTP_METHODS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=UserMessages.API_KEY_READ_ONLY,
        )
    if api_key.guild_id is not None:
        request.state.api_key_guild_id = api_key.guild_id


async def get_current_user(
    request: Request,
    session: SessionDep,
    bearer_token: Annotated[Optional[str], Depends(oauth2_scheme)] = None,
    session_cookie: Annotated[Optional[str], Cookie(alias=SESSION_COOKIE_NAME)] = None,
) -> User:
    # Start from the fail-closed empty satisfied-provider set; only the session
    # JWT branch below records a real one (see app.core.auth_context).
    set_satisfied_providers(None)
    set_satisfied_claims(None)
    set_session_mfa(False)
    set_session_passkey(False)
    set_device_token_id(None)
    # Not an API key until the branch below says so, which is the answer a
    # community that declines them admits.
    set_api_key_credential(False)
    # Which kind of credential this turns out to be, for the few endpoints that
    # care (see `require_first_party_session`). Set before any branch can
    # return, so an unrecognized path reads as something other than a session.
    request.state.credential = None

    # Check for Authorization header - could be Bearer, DeviceToken, or API key
    auth_header = request.headers.get("Authorization", "")

    # Handle DeviceToken scheme
    if auth_header.startswith("DeviceToken "):
        device_token = auth_header[12:]  # len("DeviceToken ") = 12
        user = await _authenticate_device_token(session, device_token)
        if user:
            request.state.credential = CREDENTIAL_DEVICE_TOKEN
            return user
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=AuthMessages.INVALID_DEVICE_TOKEN,
            headers={"WWW-Authenticate": "DeviceToken"},
        )

    # Use the bearer token from OAuth2 scheme, fall back to HttpOnly cookie (web sessions)
    token = bearer_token or session_cookie
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=AuthMessages.NOT_AUTHENTICATED,
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Try API key authentication first
    api_auth = await api_keys_service.authenticate_api_key(session, token)
    if api_auth:
        user, api_key = api_auth
        _enforce_api_key_scope(request, api_key)
        set_api_key_credential(True)
        request.state.credential = CREDENTIAL_API_KEY
        return user

    # Try delegation JWT from initiative-auto (RS256, distinct audience).
    # Returns None on shape/algorithm mismatch so a regular HS256 session
    # JWT carrying through this header gracefully falls through to the
    # next branch.
    user = await _authenticate_auto_delegation(request, session, token)
    if user:
        request.state.credential = CREDENTIAL_DELEGATION
        return user

    # Try JWT authentication. Any PyJWTError (expired signature, bad sig,
    # malformed claims, …) is a credentials problem, so it should be 401
    # "please re-authenticate", not 403 "you're not allowed". The SPA's
    # 401 interceptor depends on this to auto-redirect to /welcome when
    # the access token expires.
    try:
        payload = decode_session_token(token)
        token_data = TokenPayload(**payload)
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=AuthMessages.COULD_NOT_VALIDATE_CREDENTIALS,
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    # The satisfied-provider set the guild auth-policy gate reads. Legacy
    # tokens (and every non-session credential, which never reaches this
    # branch) leave it empty — fail-closed for policy-gated guilds.
    set_satisfied_providers(frozenset(token_data.sat or ()))
    set_satisfied_claims(claims_from_provider_auth(token_data.satd))
    # The marker the sign-in wrote when a code was presented. Absent on a
    # legacy token and on every credential that is not a session, which is
    # fail-closed for a community that asks for one.
    set_session_mfa(SECOND_FACTOR_AMR in (token_data.amr or ()))
    # And which kind of key answered, where one did. A community asking for a
    # passkey is asking for that; a code presented after a password is not it.
    set_session_passkey(carries_passkey(token_data.amr or ()))

    if not token_data.sub:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=AuthMessages.INVALID_TOKEN_PAYLOAD,
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = await user_for_subject(session, subject=token_data.sub)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=AuthMessages.USER_NOT_FOUND
        )
    if token_data.ver is None or token_data.ver != user.token_version:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=AuthMessages.INVALID_TOKEN
        )
    request.state.credential = CREDENTIAL_SESSION
    # Which session this request is: what lets an endpoint act on the
    # account's other ones and leave the caller where they are.
    request.state.session_id = token_data.sid
    return user


def require_first_party_session(request: Request) -> str:
    """Refuse anything but the person's own sign-in, and report which kind.

    For the handful of actions that hand out authority rather than exercise it.
    Running unattended is the whole point of the credentials this excludes — a
    workflow acts at three in the morning, a script runs on a timer, and that is
    the feature. What they cannot do is set their own bounds: a grant is what
    says how far a standing credential reaches, so it is made by the person, in
    a session of their own, rather than by the thing being granted.

    Two credentials qualify, because both are somebody signing in: a web session
    and a device token, which is what the native app exchanges an email and
    password for and then uses for everything after.

    Returns the credential kind, which is what a grant records as the factor it
    was confirmed by.
    """
    credential = getattr(request.state, "credential", None)
    if credential not in FIRST_PARTY_CREDENTIALS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=AuthMessages.SESSION_REQUIRED,
        )
    return credential


async def get_current_user_optional(
    request: Request,
    session: SessionDep,
    bearer_token: Annotated[Optional[str], Depends(oauth2_scheme)] = None,
    session_cookie: Annotated[Optional[str], Cookie(alias=SESSION_COOKIE_NAME)] = None,
) -> User | None:
    try:
        return await get_current_user(request, session, bearer_token, session_cookie)
    except HTTPException:
        return None


async def _account_holds_factor(user: User) -> bool:
    """Whether this account holds a second factor.

    Both credential stores are ``app_admin``-only, so the question goes to the
    system engine — the shape a personal API key's own lookup already uses.

    Asked afresh each time rather than remembered against the request: the
    answer changes the moment somebody enrols, and that is exactly the moment
    they are trying to get back in.
    """
    from app.db.session import AdminSessionLocal

    async with AdminSessionLocal() as admin_session:
        return await auth_posture.holds_second_factor(admin_session, user_id=user.id)


async def platform_factor_unmet(session: AsyncSession, user: User) -> bool:
    """Whether the deployment asks this account for a second factor it lacks.

    Also records what this request answers with, which is what the database
    reads as ``app.platform_factor`` — so a path that never asks this question
    carries no standing and the rule is applied there too, by Postgres.

    Three answers, cheapest first. A session that presented a factor answers
    every level. A deployment that asks nothing of this account's rung asks
    nothing — which is every request on a deployment that asks nobody, so the
    credential stores are never read there at all. Only what is left reads
    them.
    """
    if auth_context.session_mfa():
        auth_context.set_platform_factor(True)
        return False
    level = await auth_posture.second_factor_requirement(session)
    if not auth_posture.rule_covers(level, user.role):
        auth_context.set_platform_factor(True)
        return False
    held = await _account_holds_factor(user)
    auth_context.set_platform_factor(held)
    return not held


async def _active_user(request: Request, current_user: User) -> User:
    """The caller, if their account may hold a session at all.

    A *suspended* account may: its holder still reaches their own profile,
    preferences, export and deletion, and being able to sign in is how they can
    be told anything. Suspension bites at the guild instead — see
    ``_load_guild_context``.
    """
    if current_user.status not in LOGIN_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=AuthMessages.INACTIVE_USER
        )
    # Whose request this is, for the few things that run before the endpoint
    # does and have only the request to read — see
    # ``app.core.rate_limit.get_user_or_ip_key``.
    request.state.user_id = current_user.id
    return current_user


async def get_current_active_user(
    request: Request,
    session: SessionDep,
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    """The caller, held to what this deployment asks of an account.

    The active-account check, and then the deployment's own second-factor
    rule: where it covers this account and the account holds nothing to answer
    it with, the request is refused with the same 401 a community's factor
    requirement answers with, and the same dialog asks for it.

    The refusal is a 401 rather than a 403 for the reason RFC 9470 gives: the
    session authenticated, and what is missing is a factor. It names no guild,
    because this one is the deployment's.
    """
    user = await _active_user(request, current_user)
    if await platform_factor_unmet(session, user):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=GuildMessages.PLATFORM_AUTH_FACTOR_REQUIRED,
            headers={"WWW-Authenticate": STEP_UP_CHALLENGE},
        )
    return user


async def get_active_user_exempt_from_factor(
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    """The caller, on a route that stays reachable while the rule is unmet.

    Reading who you are, setting a factor up, and presenting one: without
    these an account the rule covers could not act on it. Nothing guild-scoped
    is ever reached this way — those routes resolve their guild through
    ``_load_guild_context``, which asks the same question again.
    """
    return await _active_user(request, current_user)


#: For the handful of routes above. Everything else takes ``CurrentUser``.
FactorExemptUser = Annotated[User, Depends(get_active_user_exempt_from_factor)]


def require_roles(*roles: UserRole) -> Callable:
    async def dependency(
        current_user: Annotated[User, Depends(get_current_active_user)],
    ) -> User:
        if roles and current_user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=AuthMessages.INSUFFICIENT_PRIVILEGES,
            )
        return current_user

    return dependency


def require_capability(capability: Capability) -> Callable:
    """Dependency factory gating an endpoint on a platform capability.

    Prefer this over ``require_roles`` for platform-level authorization so
    access is expressed against the capability model rather than a hardcoded
    role name (see ``app.core.capabilities``).
    """

    async def dependency(
        current_user: Annotated[User, Depends(get_current_active_user)],
    ) -> User:
        if not user_has_capability(current_user, capability):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=AuthMessages.INSUFFICIENT_PRIVILEGES,
            )
        return current_user

    return dependency


@dataclass
class GuildContext:
    guild: Guild
    membership: GuildMembership
    # The live content grant used when the caller is not a member.
    grant: Optional[AccessGrant] = None
    # The live settings rung, independent of content access.
    settings_level: Optional[SettingsLevel] = None
    # True when the guild is in ``read_only`` status and access is via real
    # membership: the session is routed into the SELECT-only ``guild_<id>_ro``
    # Postgres role so content writes are denied at the role level. Never set
    # on the grant branch — a grant carries its own read/write level.
    content_read_only: bool = False

    def settings_rung_reaches(self, role: GuildRole) -> bool:
        """Whether the settings grant includes ``role``'s authority."""
        if self.settings_level is None:
            return False
        if self.settings_level is SettingsLevel.superadmin:
            return role in (GuildRole.admin, GuildRole.superadmin)
        return role is GuildRole.admin

    @property
    def guild_id(self) -> int:
        return self.guild.id  # ty: ignore[invalid-return-type]

    @property
    def role(self) -> GuildRole:
        return self.membership.role

    @property
    def is_admin(self) -> bool:
        """Whether this request carries a guild admin's authority.

        ``superadmin`` sits above ``admin``, so it answers yes — every
        surface an admin reaches, the seat above it reaches too.
        """
        return self.role in GUILD_ADMIN_ROLES

    @property
    def is_pam(self) -> bool:
        return self.grant is not None or self.settings_level is not None

    @property
    def is_settings_only(self) -> bool:
        return self.grant is None and self.settings_level is not None


class GuildAccessError(Exception):
    """Transport-agnostic "no access to this guild" signal.

    The single entry point (``establish_guild_access`` / ``_load_guild_context``)
    raises this instead of an ``HTTPException`` so the access decision stays
    independent of how the caller speaks to the client: the REST dependency maps
    it to ``HTTPException(403)``, a WebSocket handler maps it to a ``1008`` close,
    the keepalive ``sync-content`` POST maps it to its soft-error body. It carries
    the machine-readable ``detail`` code so the REST mapping is byte-identical to
    the prior inline ``raise HTTPException``.
    """

    def __init__(
        self,
        detail: str = GuildMessages.GUILD_ACCESS_DENIED,
        *,
        step_up_provider_slug: str | None = None,
        step_up_guild_id: int | None = None,
    ) -> None:
        self.detail = detail
        # Set for GUILD_AUTH_STEP_UP_REQUIRED: which provider the session must
        # satisfy (X-Auth-Step-Up) and which guild's login flow serves it
        # (X-Auth-Step-Up-Guild) — guild-scoped providers resolve their login
        # URL through the guild, not a global slug.
        self.step_up_provider_slug = step_up_provider_slug
        self.step_up_guild_id = step_up_guild_id
        super().__init__(detail)


def _satp_param(value: frozenset[int] | str) -> list[int] | str:
    """``set_rls_context`` form of a satisfied set: the system sentinel passes
    through verbatim, a provider-id set sorts for a deterministic GUC."""
    return value if isinstance(value, str) else sorted(value)


async def _enforce_guild_auth_policy(
    session: AsyncSession,
    policy: GuildAuthPolicy | None,
    guild_id: int,
    satisfied: frozenset[int] | str,
    session_mfa: bool = False,
    session_passkey: bool = False,
) -> None:
    """Gate 0 of guild access (history/auth-detailed-design.md §5): the guild's
    sign-in policy must be satisfied by THIS session — membership and PAM
    grants alike. No policy row (or ``open``) admits any authenticated
    session; the SYSTEM_SATISFIED sentinel (user-attributed system work whose
    enqueueing request already passed this gate) passes. Mirrored at the
    database layer by ``public.guild_auth_satisfied()`` inside the guild
    RLS.

    A row can ask two things and a session has to answer both. ``provider_id``
    names one provider the session must have come through; ``require_methods``
    asks for any of this community's connections without naming which. Both
    are one question to ``guild_connection_admits``, which also applies the
    narrowing a community put on the connection.

    ``policy`` is the guild's row as the session may see it, read by whichever
    branch of :func:`_load_guild_context` got here — a member's read and a
    grantee's happen under different contexts, and each carries its own.
    """
    if satisfied == SYSTEM_SATISFIED:
        return
    if policy is None or policy.policy == "open":
        return

    def _refuse() -> None:
        raise GuildAccessError(
            detail=GuildMessages.GUILD_AUTH_STEP_UP_REQUIRED,
            step_up_provider_slug=policy.provider_slug,
            step_up_guild_id=guild_id,
        )

    if (
        policy.provider_id is not None
        and not await guild_connections.admits_this_session(
            session, guild_id=guild_id, provider_id=policy.provider_id
        )
    ):
        _refuse()

    # "Any of ours": any connection this community holds, narrowing included.
    # Named rather than counted: ``require_methods`` may hold more than one
    # method, and each is read as itself. Mirrors the matching leg in
    # ``public.guild_auth_satisfied()``, which the database applies to the same
    # row.
    if LoginMethod.sso in policy.require_methods and not (
        await guild_connections.admits_this_session(session, guild_id=guild_id)
    ):
        _refuse()

    # And the account's own second factor, where the community asks for one.
    # The answer names no provider, so the step-up says a factor is what is
    # wanted rather than pointing at a sign-in page.
    if LoginMethod.totp in policy.require_methods and not session_mfa:
        raise GuildAccessError(
            GuildMessages.GUILD_AUTH_FACTOR_REQUIRED,
            step_up_guild_id=guild_id,
        )

    # And a passkey, where the community asks for one. Read from the passkey
    # markers rather than the factor's, so each method is answered by itself:
    # an assertion records the second factor as well as the key.
    if LoginMethod.passkey in policy.require_methods and not session_passkey:
        raise GuildAccessError(
            GuildMessages.GUILD_AUTH_PASSKEY_REQUIRED,
            step_up_guild_id=guild_id,
        )


def declines_this_credential(guild: Guild) -> bool:
    """Whether ``guild`` declines the credential this request was made with.

    True only for a personal API key against a community that has switched them
    off. The key's own ``guild_id`` says nothing here: a key pinned elsewhere
    and a key pinned nowhere both address this guild the same way.

    The rule itself, so the three places that apply it read the same line — the
    guild-context gate below, the ``/uploads`` route, which resolves the guild
    itself, and the cross-guild aggregates, which visit each guild in turn (see
    ``app.services.cross_guild``).
    """
    return not guild.allow_api_keys and auth_context.api_key_credential()


def _enforce_guild_api_access(guild: Guild) -> None:
    """A community that declines personal API keys is not reached with one.

    Runs beside the sign-in gate and binds the same callers — members and
    grantees alike — because the question is what the request was made with,
    not who made it.

    Covers every path that resolves its guild through
    :func:`_load_guild_context`: REST, document downloads, the realtime sockets
    and the keepalive. The two that resolve one themselves ask the same
    question where they do it.
    """
    if declines_this_credential(guild):
        raise GuildAccessError(detail=GuildMessages.GUILD_API_KEYS_REFUSED)


async def _read_membership_gate(
    session: AsyncSession, guild_id: int, user_id: int
) -> tuple[GuildMembership, Guild, GuildAuthPolicy | None] | None:
    """The three rows the gate needs about a member, in one query.

    ``guild_memberships``, ``guilds`` and ``guild_auth_policies`` all live in
    ``public`` and are all keyed on the guild this request addresses, so asking
    for them separately was three trips for one answer. Each row still comes
    back under its own policies — an outer join to a row the session may not
    read yields NULL, exactly as its own SELECT would have. ``None`` means no
    membership the session can see, which is the grant branch's cue.
    """
    row = (
        await session.exec(
            select(GuildMembership, Guild, GuildAuthPolicy)
            .select_from(GuildMembership)
            .outerjoin(Guild, Guild.id == GuildMembership.guild_id)
            .outerjoin(
                GuildAuthPolicy, GuildAuthPolicy.guild_id == GuildMembership.guild_id
            )
            .where(
                GuildMembership.guild_id == guild_id,
                GuildMembership.user_id == user_id,
            )
        )
    ).one_or_none()
    if row is None:
        return None
    membership, guild, policy = row
    if guild is None:
        raise ValueError(GuildMessages.GUILD_NOT_FOUND)
    return membership, guild, policy


async def _read_grant_gate(
    session: AsyncSession, guild_id: int
) -> tuple[Guild, GuildAuthPolicy | None]:
    """The same two public rows for a grantee, whose PAM context has just been
    applied — a grant reaches the guild row through its own policy leg, so this
    read cannot be folded into the membership one above."""
    row = (
        await session.exec(
            select(Guild, GuildAuthPolicy)
            .select_from(Guild)
            .outerjoin(GuildAuthPolicy, GuildAuthPolicy.guild_id == Guild.id)
            .where(Guild.id == guild_id)
        )
    ).one_or_none()
    if row is None:
        raise ValueError(GuildMessages.GUILD_NOT_FOUND)
    return row[0], row[1]


async def _load_guild_context(
    session: AsyncSession,
    current_user: User,
    guild_id: int,
    satisfied: frozenset[int] | str = frozenset(),
) -> GuildContext:
    """Resolve and validate the guild context for one guild.

    ``guild_id`` is the single guild the request operates in (on REST it comes
    from the ``/g/{guild_id}/...`` path, which is only a selector, never a trust
    boundary). Access is validated fresh on every call — real membership or a
    live PAM grant, else ``GuildAccessError`` — so a stale or mistyped guild id
    fails closed. The caller has already coerced ``guild_id`` to ``int`` before
    it reaches the privileged ``SET ROLE``/``search_path`` sink.

    Transport-agnostic: it takes only the resolved ``guild_id``. The REST-only
    auto-delegation guard (token-guild must equal path-guild) lives in
    ``get_guild_membership``, where both values exist — WS / keepalive callers
    have no delegation token, so the shared resolver never deals with one.
    """
    # A suspended account reaches no guild. Ahead of the branches below so it
    # holds for membership and for a grant alike, and it answers with the same
    # generic code every other refusal here uses, so a guild is not told that
    # one of its members was suspended. Nothing is revoked: the membership is
    # still theirs when the suspension lifts.
    if current_user.status == UserStatus.suspended:
        raise GuildAccessError()

    # What the deployment asks of the account, before what this community asks
    # of the session. Here as well as in the dependency above because the
    # sockets, the keepalive and the stream re-check resolve their guild
    # through this function and never run that one.
    if await platform_factor_unmet(session, current_user):
        raise GuildAccessError(GuildMessages.PLATFORM_AUTH_FACTOR_REQUIRED)

    # Establish the caller context before loading their membership.
    await set_rls_context(
        session,
        user_id=current_user.id,
    )

    gate = await _read_membership_gate(session, guild_id, current_user.id)
    if gate is None:
        # Resolve live grants when the caller has no membership.
        grant = await access_grants_service.get_live_grant(
            session, user_id=current_user.id, guild_id=guild_id
        )
        settings_grant = await access_grants_service.get_live_grant(
            session,
            user_id=current_user.id,
            guild_id=guild_id,
            purpose=AccessGrantPurpose.settings,
        )
        if grant is None and settings_grant is None:
            raise GuildAccessError()
        is_read_write = (
            grant is not None and grant.access_level == AccessLevel.read_write.value
        )
        # Establish the grant context before loading guild metadata.
        await set_rls_context(
            session,
            user_id=current_user.id,
            pam_guild_id=guild_id,
            pam_read=True,
            pam_write=is_read_write,
        )
        guild, policy = await _read_grant_gate(session, guild_id)
        _enforce_guild_api_access(guild)
        # The guild's sign-in policy binds grantees too — PAM is a scoped
        # access path, not a policy bypass.
        await _enforce_guild_auth_policy(
            session,
            policy,
            guild_id,
            satisfied,
            auth_context.session_mfa(),
            auth_context.session_passkey(),
        )
        # Every grantee gets the ``support`` role — a first-class identity for
        # PAM access rather than a ``member`` masquerade. It is the content
        # grant's identity and clears no guard of its own: what of the
        # community's configuration this request may work is the settings grant
        # beside it, read at its own rung (``settings_rung_reaches``). The role
        # is in-memory only; it never reaches ``set_rls_context`` (the
        # ``is_pam`` branch passes ``guild_role=None``), so the ``guild_role``
        # GUC and DB enum stay admin/member.
        synthetic = GuildMembership(
            guild_id=guild_id,
            user_id=current_user.id,
            role=GuildRole.support,
        )
        return GuildContext(
            guild=guild,
            membership=synthetic,
            grant=grant,
            settings_level=(
                SettingsLevel(settings_grant.access_level) if settings_grant else None
            ),
        )
    membership, guild, policy = gate
    # Membership access respects the guild's lifecycle status.
    if guild.status == GuildStatus.suspended.value:
        raise GuildAccessError()
    _enforce_guild_api_access(guild)
    await _enforce_guild_auth_policy(
        session,
        policy,
        guild_id,
        satisfied,
        auth_context.session_mfa(),
        auth_context.session_passkey(),
    )
    return GuildContext(
        guild=guild,
        membership=membership,
        content_read_only=(guild.status == GuildStatus.read_only.value),
    )


def addressed_guild_id(request: Request, path_guild_id: int) -> int:
    """Which guild this request operates in.

    Two kinds of caller say it two ways.

    A **browser** says it in the path, and has to: a tab, a download, an
    ``<img>``, an SSE stream and a WebSocket all carry the guild, and the URL is
    the only thing all of them can carry (#680 removed the header version).

    A **delegate** says it in its token, and only there. It holds one
    credential, that credential is for one guild, and which guild was settled
    when the call authenticated. Our id is an index and its reference is minted
    for it alone, so neither is a name it should be spelling into a URL — the
    segment it writes is its own business, and this does not read it.

    See ``history/opaque-identity-design.md`` §13.
    """
    delegated = getattr(request.state, "delegated_guild_id", None)
    return path_guild_id if delegated is None else delegated


async def get_guild_membership(
    request: Request,
    session: SessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_id: Annotated[int, Path(description="Guild this request operates in")],
) -> GuildContext:
    """Strict guild context for the guild this request addresses.

    Every guild-scoped router mounts under ``/g/{guild_id}``, so FastAPI injects
    the segment here; :func:`addressed_guild_id` decides whether that is the
    answer or whether the call's delegation already gave one. Membership (or a
    live PAM grant) is validated fresh; a non-member or stale grant gets 403. A
    guild-scoped route mounted *outside* the prefix fails at startup (missing
    path param) — a useful guard that every such route is path-addressed.
    """
    guild_id = addressed_guild_id(request, guild_id)
    # A guild-bound API key (PAT) is pinned to one guild the same way: refuse if
    # the path addresses a different guild than the key was scoped to.
    key_guild = getattr(request.state, "api_key_guild_id", None)
    if key_guild is not None and key_guild != guild_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=GuildMessages.GUILD_ACCESS_DENIED,
        )
    try:
        return await _load_guild_context(
            session,
            current_user,
            guild_id,
            satisfied=auth_context.satisfied_providers(),
        )
    except GuildAccessError as exc:
        if exc.detail in (
            GuildMessages.GUILD_AUTH_FACTOR_REQUIRED,
            GuildMessages.GUILD_AUTH_PASSKEY_REQUIRED,
            GuildMessages.PLATFORM_AUTH_FACTOR_REQUIRED,
        ):
            # 401 for the same reason as the provider step-up below, and apart
            # from it because what satisfies these is presented against the
            # session already open rather than a sign-in page to visit. RFC
            # 9470 all the same: the session authenticated, and what is missing
            # is a factor. The detail says which of the two, so the dialog
            # knows whether to ask for a code or run a ceremony.
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=exc.detail,
                headers={
                    "WWW-Authenticate": STEP_UP_CHALLENGE,
                    "X-Auth-Step-Up-Guild": (
                        str(exc.step_up_guild_id)
                        if exc.step_up_guild_id is not None
                        else ""
                    ),
                },
            ) from exc
        if exc.detail == GuildMessages.GUILD_AUTH_STEP_UP_REQUIRED:
            # 401, not 403: the session lacks an auth factor, not a permission.
            #
            # Said twice, for two audiences. ``WWW-Authenticate`` is the
            # standard form (RFC 9470), which an OAuth client library can act
            # on knowing nothing about this app. The ``X-Auth-Step-Up`` pair
            # names *which* provider serves the factor and which guild's login
            # flow reaches it — ours to answer, and what our own SPA reads.
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=exc.detail,
                headers={
                    "WWW-Authenticate": STEP_UP_CHALLENGE,
                    "X-Auth-Step-Up": exc.step_up_provider_slug or "",
                    "X-Auth-Step-Up-Guild": (
                        str(exc.step_up_guild_id)
                        if exc.step_up_guild_id is not None
                        else ""
                    ),
                },
            ) from exc
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=exc.detail
        ) from exc


def holds_guild_role(context: GuildContext, *roles: GuildRole) -> bool:
    """Whether this request answers a guard asking for any of ``roles``.

    Asking for ``admin`` asks for admin *or above*, so a superadmin satisfies
    every guard an ordinary admin satisfies — the seat sits above ``admin``,
    and this is the one place that has to know it for all of them.

    A live settings grant answers at its own rung. It confers no content access
    with it: the session is still routed as the grant's read/write level says.

    The predicate behind :func:`require_guild_roles`, separate from it because
    some endpoints ask the same question part-way through a handler rather than
    at the door — and the two must never drift into different answers.
    """
    accepted = frozenset(roles)
    if GuildRole.admin in accepted:
        accepted |= GUILD_ADMIN_ROLES
    if not accepted:
        return True
    if any(context.settings_rung_reaches(role) for role in accepted):
        return True
    return context.membership.role in accepted


def require_guild_roles(*roles: GuildRole) -> Callable:
    """Guard an endpoint on the caller's role in the guild named by the path.

    See :func:`holds_guild_role`, which is what it asks.
    """

    async def dependency(
        context: Annotated[GuildContext, Depends(get_guild_membership)],
    ) -> GuildContext:
        if not holds_guild_role(context, *roles):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=GuildMessages.GUILD_PERMISSION_REQUIRED,
            )
        return context

    return dependency


async def _apply_guild_session_context(
    session: AsyncSession,
    current_user: User,
    guild_context: GuildContext,
    satisfied: frozenset[int] | str = frozenset(),
) -> AsyncSession:
    """Route ``session`` into ``guild_context``'s guild: set the RLS/session
    variables (and the request-scoped PAM/role contexts) for the user+guild,
    PAM-scoped when access is via a grant."""

    if guild_context.is_settings_only:
        set_active_grant(None, None)
        set_active_role(None, None)
        set_override_sharing_initiatives(None)
        set_content_read_only_guild(None)
        await set_rls_context(
            session,
            user_id=current_user.id,
            settings_guild_id=guild_context.guild_id,
            platform_role=current_user.role.value,
            satisfied_providers=_satp_param(satisfied),
            satisfied_claims=auth_context.satisfied_claims(),
            session_mfa=auth_context.session_mfa(),
        )
        return session

    if guild_context.is_pam:
        # Apply a content grant at its recorded access level.
        grant = guild_context.grant
        access_level = (
            grant.access_level if grant is not None else AccessLevel.read.value
        )
        set_active_grant(guild_context.guild_id, access_level)
        # Grant access does not create membership.
        set_active_role(None, None)
        # A PAM grantee holds no initiative role, so no "Full access" override.
        set_override_sharing_initiatives(None)
        set_content_read_only_guild(None)
        # Keep membership and grant contexts distinct.
        await set_rls_context(
            session,
            user_id=current_user.id,
            guild_id=None,
            guild_role=None,
            pam_guild_id=guild_context.guild_id,
            pam_read=True,
            pam_write=(access_level == AccessLevel.read_write.value),
            platform_role=current_user.role.value,
            satisfied_providers=_satp_param(satisfied),
            satisfied_claims=auth_context.satisfied_claims(),
            session_mfa=auth_context.session_mfa(),
            session_passkey=auth_context.session_passkey(),
        )
        return session

    set_active_grant(None, None)
    # Record the membership role for this request's active guild so the sync
    # access checks can apply the guild-admin leg of the initiative-scope gate.
    set_active_role(guild_context.guild_id, guild_context.role.value)
    # Frozen guild (read_only lifecycle status): the DB role already refuses
    # writes; recording it here makes the app-layer DAC engine agree, so every
    # derived permission (my_permission_level, writable filters, WS can_write)
    # reports read from ONE flag instead of per-surface re-derivations.
    set_content_read_only_guild(
        guild_context.guild_id if guild_context.content_read_only else None
    )
    # Apply the member's guild context.
    await set_rls_context(
        session,
        user_id=current_user.id,
        guild_id=guild_context.guild_id,
        # The effective content role, which is where a superadmin reads
        # as an admin — see ``models.platform.guild.content_role``.
        guild_role=content_role(guild_context.role),
        # Recorded, not routed with: the guild role governs inside the schema.
        # It is what a later hop back out to ``public`` re-assumes.
        platform_role=current_user.role.value,
        # Guild in read_only status: keep the full membership GUCs (so the
        # initiative-member and admin RLS legs evaluate normally) but assume
        # the SELECT-only guild_<id>_ro Postgres role — content writes are
        # denied by Postgres, not app code.
        read_only=guild_context.content_read_only,
        satisfied_providers=_satp_param(satisfied),
        satisfied_claims=auth_context.satisfied_claims(),
        session_mfa=auth_context.session_mfa(),
        session_passkey=auth_context.session_passkey(),
    )
    # The initiatives where this member holds "Full access", for the sync DAC
    # checks (gate 4, without an async query) and for the policies that read
    # the same override. Runs in the routed guild schema (after SET ROLE), so
    # it sees this guild's roles — and resolving it and recording it are the
    # same statement, which is what keeps the context above written once.
    from app.services import rls as rls_service

    override_ids = await apply_override_initiatives(
        session, rls_service.override_sharing_initiatives_select(current_user.id)
    )
    set_override_sharing_initiatives(override_ids)
    return session


async def get_guild_session(
    session: SessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: Annotated[GuildContext, Depends(get_guild_membership)],
) -> AsyncSession:
    """Get a session with RLS context set for the current user and guild.

    This dependency injects PostgreSQL context (via set_config with
    is_local=true) that RLS policies use to filter data. Use this instead
    of SessionDep when you need database-level access control.

    Context is transaction-local and replayed automatically at the start of
    every transaction (see app.db.session), so post-commit queries need no
    manual re-apply.
    """
    if guild_context.is_settings_only:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=GuildMessages.GUILD_ACCESS_DENIED,
        )
    return await _apply_guild_session_context(
        session,
        current_user,
        guild_context,
        satisfied=auth_context.satisfied_providers(),
    )


async def get_guild_settings_session(
    session: SessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: Annotated[GuildContext, Depends(get_guild_membership)],
) -> AsyncSession:
    """Route a guild configuration request, including settings-only grants."""
    return await _apply_guild_session_context(
        session,
        current_user,
        guild_context,
        satisfied=auth_context.satisfied_providers(),
    )


async def establish_guild_access(
    session: AsyncSession,
    current_user: User,
    guild_id: int,
    satisfied_providers: frozenset[int] | str | None = None,
) -> GuildContext:
    """Resolve guild access AND apply the session context — the single entry
    point for callers that can't use the REST dependency chain.

    *Resolve* access (membership / live PAM / break-glass, else
    ``GuildAccessError``) then *apply* the RLS + ``active_role`` + ``active_grant``
    context, returning the ``GuildContext``. REST composes the same two primitives
    via DI (``get_guild_membership`` → ``get_guild_session``); WebSocket and
    keepalive handlers call this so they cannot resolve-without-applying — the
    omission that denied a guild admin on the collaboration socket while the REST
    read allowed them. The caller maps ``GuildAccessError`` to its transport
    (REST → 403, WebSocket → 1008, keepalive → soft error body).

    ``satisfied_providers`` feeds the guild auth-policy gate and the
    ``app.satisfied_providers`` GUC. ``None`` (the default) reads the ambient
    ``auth_context`` the credential validator recorded — right for every path
    serving a live session. Explicit values are for the two non-session cases:
    user-attributed system jobs pass ``SYSTEM_SATISFIED``, and the stream
    re-auth sweep replays the set captured at socket join.
    """
    satisfied = (
        auth_context.satisfied_providers()
        if satisfied_providers is None
        else satisfied_providers
    )
    guild_context = await _load_guild_context(
        session, current_user, guild_id, satisfied=satisfied
    )
    await _apply_guild_session_context(
        session, current_user, guild_context, satisfied=satisfied
    )
    return guild_context


# Dependency for routes that need RLS-aware database access
RLSSessionDep = Annotated[AsyncSession, Depends(get_guild_session)]
SettingsRLSSessionDep = Annotated[AsyncSession, Depends(get_guild_settings_session)]


async def _include_deleted_flag(
    session: RLSSessionDep,
    include_deleted: Annotated[
        bool,
        Query(
            description=(
                "Also return the resource if it is in the trash. For reading a "
                "resource back after a deleted event — the row still exists "
                "until retention purges it, and access is checked exactly as "
                "for a live one."
            )
        ),
    ] = False,
) -> bool:
    """Opt a detail GET into seeing trashed rows.

    Flips the request session's soft-delete filter off (``session.info`` —
    see ``app.db.soft_delete_filter``) so every load in the handler, including
    the DAC loaders, can resolve a trashed row. Discloses nothing new: RLS and
    the per-resource access checks run unchanged, and the trash surface already
    shows these rows to the same audience.
    """
    if include_deleted:
        session.info["include_deleted"] = True
    return include_deleted


IncludeDeletedDep = Annotated[bool, Depends(_include_deleted_flag)]


async def _apply_user_session_context(
    session: AsyncSession, current_user: User
) -> AsyncSession:
    """Route ``session`` for the public/platform path: no guild, the caller's
    own tier. The body both user-session dependencies share."""
    await set_rls_context(
        session,
        user_id=current_user.id,
        platform_role=current_user.role.value,
    )
    return session


async def get_factor_exempt_user_session(
    session: SessionDep,
    current_user: FactorExemptUser,
) -> AsyncSession:
    """The platform-path session for a route that stays reachable while the
    deployment's second-factor rule is unmet — routed exactly as the ordinary
    one, and holding no more."""
    return await _apply_user_session_context(session, current_user)


FactorExemptSessionDep = Annotated[
    AsyncSession, Depends(get_factor_exempt_user_session)
]


async def get_user_session(
    session: SessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> AsyncSession:
    """Get a session with user context only (no guild).

    For cross-guild operations like guild creation, listing user's guilds,
    or accepting invites where no specific guild context is needed.

    This is the authenticated *public/platform* path: it carries no guild
    context, so the session assumes the caller's platform-tier role
    (``platform_<users.role>``) rather than the broad login role — the request
    is role-scoped at the database and fails closed if a downstream query forgets
    to route. Guild-addressed work uses ``get_guild_session`` instead, which
    ``SET ROLE``s into the guild role.

    No standing all-guild bypass: a platform role's cross-user/guild
    reach on this path is authorized by the ``platform_<tier>`` RLS policies
    (Phase 2), and reaching a guild's *data* requires an explicit break-glass
    PAM grant (§7), never an ambient flag.
    """
    return await _apply_user_session_context(session, current_user)


# Dependency for routes that need user-level RLS without guild context
UserSessionDep = Annotated[AsyncSession, Depends(get_user_session)]


async def _load_active_user_by_id(session: AsyncSession, user_id: int) -> User:
    """Load a user by id for the uploads route, enforcing active status.

    Shared by the scoped-upload-token path so a deactivated account can't
    keep pulling media with a still-valid token.
    """
    statement = select(User).where(User.id == user_id)
    result = await session.exec(statement)
    user = result.one_or_none()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=AuthMessages.USER_NOT_FOUND
        )
    if user.status != UserStatus.active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=AuthMessages.INACTIVE_USER
        )
    return user


async def _authenticate_upload_query_token(
    session: AsyncSession, token_param: str
) -> User:
    """Resolve a ``?token=`` query-param credential for /uploads/*.

    Query params leak via logs, browser history, and Referer headers, so this
    path deliberately accepts ONLY URL-safe, narrowly-scoped credentials:

      1. A short-lived, uploads-scoped JWT minted by ``POST /auth/upload-token``
         (native <img>/<iframe> media loads can't send headers or cookies).
      2. A device token (native long-lived credential, already used this way).

    It intentionally does NOT accept a full session JWT or an API key — those
    are long-lived, full-API credentials that must never ride in a URL. A
    session JWT presented here therefore 401s.
    """
    # 1. Scoped upload token (preferred for native media).
    try:
        (
            user_id,
            token_satisfied,
            token_claims,
            token_mfa,
            token_passkey,
        ) = verify_upload_token(token_param)
    except UploadTokenError:
        pass
    else:
        # The scoped token copied its minting session's satisfied set — record
        # it so the guild auth-policy gate treats this request as that session.
        set_satisfied_providers(token_satisfied)
        set_satisfied_claims(token_claims)
        set_session_mfa(token_mfa)
        set_session_passkey(token_passkey)
        return await _load_active_user_by_id(session, user_id)

    # 2. Device token fallback (native apps historically pass these as ?token=).
    user = await _authenticate_device_token(session, token_param)
    if user:
        if user.status != UserStatus.active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=AuthMessages.INACTIVE_USER,
            )
        return user

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=AuthMessages.COULD_NOT_VALIDATE_CREDENTIALS,
        headers={"WWW-Authenticate": "Bearer"},
    )


async def _resolve_upload_user(
    request: Request,
    session: SessionDep,
    bearer_token: Annotated[Optional[str], Depends(oauth2_scheme)] = None,
    token_param: Annotated[Optional[str], Query(alias="token")] = None,
    session_cookie: Annotated[Optional[str], Cookie(alias=SESSION_COOKIE_NAME)] = None,
) -> User:
    """Auth dependency for /uploads/* and authenticated document downloads.

    Held to the deployment's second-factor rule like any other request: this
    resolves its own caller rather than going through
    ``get_current_active_user``, so it asks the same question itself.

    Two trust tiers, by where the credential arrives:

      * Authorization header or HttpOnly cookie — not exposed in URLs, so the
        full credential set is honored (session JWT, API key, delegation JWT,
        DeviceToken scheme). This is the web <img> path (cookie) and direct API
        callers.
      * ``?token=`` query param — leaks via logs/history/Referer, so only a
        short-lived uploads-scoped token or a device token is accepted (see
        ``_authenticate_upload_query_token``). A full session JWT here is
        rejected; native clients fetch a scoped token from
        ``POST /auth/upload-token`` instead.
    """
    # Fail-closed default; the session-JWT and scoped-token branches record the
    # credential's real satisfied set (see app.core.auth_context).
    set_satisfied_providers(None)
    set_satisfied_claims(None)
    set_session_mfa(False)
    set_session_passkey(False)
    set_device_token_id(None)
    set_api_key_credential(False)

    auth_header = request.headers.get("Authorization", "")

    # 1. DeviceToken scheme (Authorization header only — device tokens aren't safe in URLs)
    if auth_header.startswith("DeviceToken "):
        device_token = auth_header[12:]  # len("DeviceToken ") = 12
        user = await _authenticate_device_token(session, device_token)
        if user:
            if user.status != UserStatus.active:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=AuthMessages.INACTIVE_USER,
                )
            return user
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=AuthMessages.INVALID_DEVICE_TOKEN,
            headers={"WWW-Authenticate": "DeviceToken"},
        )

    # 2. Header bearer or cookie carries the full-trust credential. A ?token=
    #    query param, by contrast, is restricted to URL-safe scoped credentials.
    header_token = bearer_token or session_cookie
    if not header_token:
        if token_param:
            return await _authenticate_upload_query_token(session, token_param)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=AuthMessages.NOT_AUTHENTICATED,
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = header_token

    # Try API key authentication first
    api_auth = await api_keys_service.authenticate_api_key(session, token)
    if api_auth:
        user, api_key = api_auth
        if user.status != UserStatus.active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=AuthMessages.INACTIVE_USER,
            )
        _enforce_api_key_scope(request, api_key)
        set_api_key_credential(True)
        return user

    # Try delegation JWT from initiative-auto. Same chain placement as
    # ``get_current_user`` so /uploads/* accepts auto-driven workflow
    # downloads without per-route changes. Falls through on shape /
    # algorithm / audience mismatch so a regular HS256 session JWT
    # arriving on the same header still hits the standard JWT branch
    # below.
    user = await _authenticate_auto_delegation(request, session, token)
    if user:
        # Delegation already enforces ``user.status == active``;
        # ``_authenticate_auto_delegation`` returned None otherwise.
        return user

    # Try JWT authentication. Expired / malformed tokens are 401 (not 403)
    # so the SPA can auto-redirect to /welcome when the session lapses.
    try:
        payload = decode_session_token(token)
        token_data = TokenPayload(**payload)
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=AuthMessages.COULD_NOT_VALIDATE_CREDENTIALS,
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not token_data.sub:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=AuthMessages.INVALID_TOKEN_PAYLOAD,
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = await user_for_subject(session, subject=token_data.sub)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=AuthMessages.USER_NOT_FOUND
        )
    if token_data.ver is None or token_data.ver != user.token_version:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=AuthMessages.INVALID_TOKEN
        )
    if user.status != UserStatus.active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=AuthMessages.INACTIVE_USER
        )
    set_satisfied_providers(frozenset(token_data.sat or ()))
    set_satisfied_claims(claims_from_provider_auth(token_data.satd))
    # What the session proved about the person, read from its own ``amr`` as
    # ``get_current_user`` reads it — a community asking for either answers a
    # picture and a download the same way it answers a page.
    set_session_mfa(SECOND_FACTOR_AMR in (token_data.amr or ()))
    set_session_passkey(carries_passkey(token_data.amr or ()))
    return user


async def get_upload_user(
    request: Request,
    session: SessionDep,
    bearer_token: Annotated[Optional[str], Depends(oauth2_scheme)] = None,
    token_param: Annotated[Optional[str], Query(alias="token")] = None,
    session_cookie: Annotated[Optional[str], Cookie(alias=SESSION_COOKIE_NAME)] = None,
) -> User:
    """The media path's caller, held to the deployment's second-factor rule.

    The resolution itself is next door and unchanged; this is where the one
    question every other request answers is asked of this one too, once the
    credential has named somebody.
    """
    user = await _resolve_upload_user(
        request, session, bearer_token, token_param, session_cookie
    )
    if await platform_factor_unmet(session, user):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=GuildMessages.PLATFORM_AUTH_FACTOR_REQUIRED,
            headers={"WWW-Authenticate": STEP_UP_CHALLENGE},
        )
    return user


UploadUserDep = Annotated[User, Depends(get_upload_user)]


async def require_direct_messages_enabled(session: UserSessionDep) -> None:
    """Refuse every direct-message route when the deployment does not offer them.

    Applied once, to the routers rather than to the endpoints, so the whole
    surface answers the same way and a route added later is covered by having
    been added to the router. It shares the caller's session: every endpoint
    behind it takes ``UserSessionDep``, so FastAPI resolves that dependency once
    and this costs a single indexed read rather than a second connection.

    Nothing is deleted while it is off -- devices, keys, policies and accepted
    channels all stay -- so the only thing switching it back on has to do is
    stop refusing.
    """
    from app.services.platform import app_settings as app_settings_service

    if not await app_settings_service.direct_messages_enabled(session):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=DirectMessageMessages.DISABLED_FOR_PLATFORM,
        )


DirectMessagesEnabledDep = Depends(require_direct_messages_enabled)
