from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Annotated, Any, NoReturn, Optional

from fastapi import Cookie, Depends, HTTPException, Path, Query, Request, status
from fastapi.security import OAuth2PasswordBearer
import jwt
from sqlalchemy.exc import DBAPIError
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.app_access_token import (
    AccessTokenError,
    InstallAccessToken,
    is_access_token,
    unseal_access_token,
)
from app.core.app_scopes import (
    AppScopeAccess,
    UnknownAppScope,
    expand,
    parse_scope,
    validate_scopes,
)
from app.core.capabilities import Capability, user_has_capability
from app.core.config import API_V1_STR
from app.core.login_methods import LoginMethod
from app.core import auth_context
from app.core.auth_context import (
    set_api_key_credential,
    set_asked_of_account,
    set_device_token_id,
    set_satisfied_providers,
    set_session_amr,
    claims_from_provider_auth,
    set_satisfied_claims,
)
from app.services.auth import guild_provider_connections as guild_connections
from app.services.auth.assurance import (
    SECOND_FACTOR_AMR,
    carries_passkey,
    policy_markers,
)
from app.core.login_methods import SecondFactorRequirement
from app.models.platform.app_setting import AppSetting
from app.services.platform import auth_posture
from app.services.platform.app_settings import GLOBAL_SETTINGS_ID
from app.core import audit_context
from app.core.messages import (
    AccessGrantMessages,
    AppMessages,
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
from app.db.guild_standing import GuildContext, InstallContext
from app.db.schema_provisioning import PLATFORM_SUSPENDED
from app.db.session import (
    SYSTEM_SATISFIED,
    apply_guild_standing,
    apply_install_standing,
    clear_rls_context,
    get_session,
    set_rls_context,
)
from app.models.platform.access_grant import (
    AccessGrantPurpose,
    AccessLevel,
)
from app.models.platform.api_key import UserApiKey
from app.models.platform.guild import (
    LIVE_STATUS_VALUES,
    Guild,
    GuildMembership,
    GuildRole,
    GuildStatus,
)
from app.models.platform.guild_auth_policy import GuildAuthPolicy
from app.models.platform.user import (
    LOGIN_STATUSES,
    User,
    UserStatus,
)
from app.schemas.platform.token import TokenPayload
from app.services.auth.subject import account_for_subject
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
#: An installed app's access token. Only a route that names an app scope
#: admits one (:func:`app_scope`).
CREDENTIAL_INSTALL = "install"

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

    The token is resolved on the system engine, as a personal API key is; the
    account it names is loaded on the request's own session.
    """
    device_token = await user_tokens.authenticate_device_token(token)
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
    set_session_amr(None)
    set_device_token_id(None)
    set_asked_of_account(None)
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

    # An installed app's access token is never a person. It is refused here,
    # before anything is read, and admitted only by a route that names an app
    # scope (``app_scope``), which reads it without coming through here.
    if is_access_token(token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=AuthMessages.COULD_NOT_VALIDATE_CREDENTIALS,
            headers={"WWW-Authenticate": "Bearer"},
        )

    # A personal API key names itself by its prefix; anything else is not one.
    api_auth = (
        await api_keys_service.authenticate_api_key(session, token)
        if token.startswith(api_keys_service.API_KEY_PREFIX)
        else None
    )
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

    # The satisfied-provider set the guild auth-policy gate reads. A
    # non-session credential never reaches this branch and leaves it empty.
    set_satisfied_providers(frozenset(token_data.sat or ()))
    set_satisfied_claims(claims_from_provider_auth(token_data.satd))
    # What the sign-in wrote about how it was made — the second-factor marker
    # where a code was presented, the passkey markers where a key answered.
    # Empty on every credential that is not a session.
    set_session_amr(policy_markers(token_data.amr))

    if not token_data.sub:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=AuthMessages.INVALID_TOKEN_PAYLOAD,
            headers={"WWW-Authenticate": "Bearer"},
        )

    account = await account_for_subject(session, subject=token_data.sub)
    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=AuthMessages.USER_NOT_FOUND
        )
    user, settings_row = account
    if token_data.ver is None or token_data.ver != user.token_version:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=AuthMessages.INVALID_TOKEN
        )
    # What the deployment asks of an account, off the row the lookup carried.
    set_asked_of_account(_asked_of_an_account(settings_row))
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
    from app.db.session import SystemSessionLocal

    async with SystemSessionLocal() as system_session:
        return await auth_posture.holds_second_factor(system_session, user_id=user.id)


async def platform_factor_unmet(
    session: AsyncSession,
    user: User,
    *,
    level: SecondFactorRequirement | None = None,
) -> bool:
    """Whether the deployment asks this account for a second factor it lacks.

    Also records what this request answers with, which is what the database
    reads as ``app.platform_factor`` — so a path that never asks this question
    carries no standing and the rule is applied there too, by Postgres.

    Three answers, cheapest first. A session that presented a factor answers
    every level. A deployment that asks nothing of this account's rung asks
    nothing — which is every request on a deployment that asks nobody, so the
    credential stores are never read there at all. Only what is left reads
    them.

    ``level`` is what the deployment asks, where the caller already knows —
    the guild gate reads the settings row beside the membership it is checking,
    so the question costs that path no round trip of its own. Left out, it is
    what the credential validator recorded beside the account, and read here
    only where nothing was.
    """
    if SECOND_FACTOR_AMR in auth_context.session_amr():
        auth_context.set_platform_factor(True)
        return False
    if level is None:
        level = auth_context.asked_of_account()
    if level is None:
        level = await auth_posture.second_factor_requirement(session)
    if not auth_posture.rule_covers(level, user.role):
        auth_context.set_platform_factor(True)
        return False
    held = await _account_holds_factor(user)
    auth_context.set_platform_factor(held)
    return not held


async def _active_user(
    request: Request, current_user: User, *, admit_suspended: bool = False
) -> User:
    """The caller, if their account may hold a session at all.

    A *suspended* account may hold one: signing in is how its holder is told
    they are in time out. What it reaches is the time-out allow-list and
    nothing else — the routes that take :data:`AccountHolder` and its session,
    which read the account's own state. Every other route refuses it with
    ``ACCOUNT_SUSPENDED``, so a route written tomorrow is closed to it by
    default.
    """
    if current_user.status not in LOGIN_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=AuthMessages.INACTIVE_USER
        )
    if current_user.status == UserStatus.suspended and not admit_suspended:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=AuthMessages.ACCOUNT_SUSPENDED,
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
    await _require_platform_factor(session, user)
    return user


async def _require_platform_factor(session: AsyncSession, user: User) -> None:
    if await platform_factor_unmet(session, user):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=GuildMessages.PLATFORM_AUTH_FACTOR_REQUIRED,
            headers={"WWW-Authenticate": STEP_UP_CHALLENGE},
        )


async def get_current_account_holder(
    request: Request,
    session: SessionDep,
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    """The caller on a time-out allow-list route: active, or suspended.

    Held to the same second-factor rule as :func:`get_current_active_user`.
    The routes that take it read or close the account's own state — its
    sessions, its notifications — and nothing another person can see.
    """
    user = await _active_user(request, current_user, admit_suspended=True)
    await _require_platform_factor(session, user)
    return user


async def get_account_holder_exempt_from_factor(
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    """:func:`get_current_account_holder` for a factor-exempt route."""
    return await _active_user(request, current_user, admit_suspended=True)


#: The caller on a time-out allow-list route. See :func:`_active_user`.
AccountHolder = Annotated[User, Depends(get_current_account_holder)]
FactorExemptAccountHolder = Annotated[
    User, Depends(get_account_holder_exempt_from_factor)
]


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


def require_capability(capability: Capability) -> Callable:
    """Dependency factory gating an endpoint on a platform capability.

    Access is expressed against the capability model rather than a hardcoded
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


# ``GuildContext`` is defined beside the standing it carries
# (:mod:`app.db.guild_standing`) so the routing that replays it can read it
# without importing this module. This is still the only place one is built.


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
    markers: frozenset[str] = frozenset(),
    *,
    require_second_factor: bool = False,
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
    # Asked of everybody reaching this community, whatever it says about how
    # they arrive — so it is read before a community with no sign-in rule
    # returns. The answer names no provider and no kind of factor: the
    # step-up says a factor is what is wanted.
    if require_second_factor and SECOND_FACTOR_AMR not in markers:
        raise GuildAccessError(
            GuildMessages.GUILD_AUTH_FACTOR_REQUIRED,
            step_up_guild_id=guild_id,
        )
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
    if LoginMethod.totp in policy.require_methods and SECOND_FACTOR_AMR not in markers:
        raise GuildAccessError(
            GuildMessages.GUILD_AUTH_FACTOR_REQUIRED,
            step_up_guild_id=guild_id,
        )

    # And a passkey, where the community asks for one. Read from the passkey
    # markers rather than the factor's, so each method is answered by itself:
    # an assertion records the second factor as well as the key.
    if LoginMethod.passkey in policy.require_methods and not carries_passkey(markers):
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


def _asked_of_an_account(settings_row: AppSetting | None) -> SecondFactorRequirement:
    """What the deployment asks, from the row the gate read.

    A database with no singleton yet asks nothing — the same conclusion
    ``public.platform_factor_satisfied()`` reaches from the same absence, so
    the two layers agree on a deployment that has not finished starting.
    """
    if settings_row is None:
        return SecondFactorRequirement.nobody
    return auth_posture.requirement_from_row(settings_row)


async def _read_membership_gate(
    session: AsyncSession, guild_id: int, user_id: int
) -> (
    tuple[GuildMembership, Guild, GuildAuthPolicy | None, SecondFactorRequirement, bool]
    | None
):
    """The four rows the gate needs about a member, in one query.

    ``guild_memberships``, ``guilds`` and ``guild_auth_policies`` all live in
    ``public`` and are all keyed on the guild this request addresses, so asking
    for them separately was three trips for one answer. The settings singleton
    rides along for the same reason — what the deployment asks of an account is
    decided in the same breath as what the community asks of the session, and a
    read of its own would be a round trip on every guild request there is.

    Each row still comes back under its own policies — an outer join to a row
    the session may not read yields NULL, exactly as its own SELECT would have.
    ``None`` means no membership the session can see, which is the grant
    branch's cue.
    """
    row = (
        await session.exec(
            select(GuildMembership, Guild, GuildAuthPolicy, AppSetting)
            .select_from(GuildMembership)
            .outerjoin(Guild, Guild.id == GuildMembership.guild_id)
            .outerjoin(
                GuildAuthPolicy, GuildAuthPolicy.guild_id == GuildMembership.guild_id
            )
            .outerjoin(AppSetting, AppSetting.id == GLOBAL_SETTINGS_ID)
            .where(
                GuildMembership.guild_id == guild_id,
                GuildMembership.user_id == user_id,
            )
        )
    ).one_or_none()
    if row is None:
        return None
    membership, guild, policy, settings_row = row
    if guild is None:
        raise ValueError(GuildMessages.GUILD_NOT_FOUND)
    # The age switch rides along for the same reason the factor requirement
    # does: it is decided from this same row, and reading it separately would
    # be a round trip on every guild request there is.
    age_gate_on = bool(
        settings_row is not None and settings_row.community_age_gate_enabled
    )
    return membership, guild, policy, _asked_of_an_account(settings_row), age_gate_on


async def _read_grant_gate(
    session: AsyncSession, guild_id: int
) -> tuple[Guild, GuildAuthPolicy | None, SecondFactorRequirement]:
    """The same public rows for a grantee, whose PAM context has just been
    applied — a grant reaches the guild row through its own policy leg, so this
    read cannot be folded into the membership one above."""
    row = (
        await session.exec(
            select(Guild, GuildAuthPolicy, AppSetting)
            .select_from(Guild)
            .outerjoin(GuildAuthPolicy, GuildAuthPolicy.guild_id == Guild.id)
            .outerjoin(AppSetting, AppSetting.id == GLOBAL_SETTINGS_ID)
            .where(Guild.id == guild_id)
        )
    ).one_or_none()
    if row is None:
        raise ValueError(GuildMessages.GUILD_NOT_FOUND)
    return row[0], row[1], _asked_of_an_account(row[2])


async def _load_guild_context(
    session: AsyncSession,
    current_user: User,
    guild_id: int,
    satisfied: frozenset[int] | str = frozenset(),
    *,
    for_settings: bool = False,
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

    ``for_settings`` is the community's own configuration surface, which a
    guild administrator keeps while its content is frozen: a ``read_only``
    community, and one whose sign-in policy this session does not answer, still
    has an administrator to run it. A community outside the live statuses has
    no settings surface for its members either — it is in time out, and only
    the platform brings it back. It reads the same way on both branches below,
    membership and grant. The rung guard on those routes has already refused
    anyone who does not administer it; what this establishes is the standing
    the database reads.
    """
    # A suspended account reaches no guild. Ahead of the branches below so it
    # holds for membership and for a grant alike, and it answers with the same
    # generic code every other refusal here uses, so a guild is not told that
    # one of its members was suspended. Nothing is revoked: the membership is
    # still theirs when the suspension lifts.
    if current_user.status == UserStatus.suspended:
        raise GuildAccessError()

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
        guild, policy, asked = await _read_grant_gate(session, guild_id)
        _enforce_guild_api_access(guild)
        # What the deployment asks of the account, before what this community
        # asks of the session. Asked here as well as in the dependency above
        # because the sockets, the keepalive and the stream re-check resolve
        # their guild through this function and never run that one — off the
        # row the read above already carried.
        if await platform_factor_unmet(session, current_user, level=asked):
            raise GuildAccessError(GuildMessages.PLATFORM_AUTH_FACTOR_REQUIRED)
        # The guild's sign-in policy binds grantees too — PAM is a scoped
        # access path, not a policy bypass. Content only, the same line the
        # membership branch draws: the rule a community sets for coming in
        # governs its work, and the surface that sets the rule is reachable by
        # whoever administers the community, which is what a settings grant
        # lends. The database draws the same line on its own — the standing
        # statement answers the sign-in question from the rows, and the
        # initiative gates read that answer whatever this call was for.
        if not for_settings:
            await _enforce_guild_auth_policy(
                session,
                policy,
                guild_id,
                satisfied,
                auth_context.session_amr(),
                require_second_factor=guild.require_second_factor,
            )
        # A grantee holds no membership row, and none is invented for them:
        # what the two grants reach is computed from the rows themselves by
        # the standing statement. ``context.role`` answers ``support`` — the
        # identity granted access carries — and clears no guard of its own.
        return GuildContext(
            guild=guild,
            user_id=current_user.id,
            guild_id=guild_id,
            grant=grant,
            settings_grant=settings_grant,
            settings_grant_level=(
                None if settings_grant is None else settings_grant.access_level
            ),
        )
    membership, guild, policy, asked, age_gate_on = gate
    # Membership access respects the guild's lifecycle status: the statuses
    # that serve members are named, and every other one is refused, on every
    # surface. A suspended community is in time out — its administrators are
    # members like any other until the platform lifts it.
    if guild.status not in LIVE_STATUS_VALUES:
        raise GuildAccessError()
    _enforce_guild_api_access(guild)
    # A listed community is open to anyone signed in, so the deployment's age
    # question is owed by the people in it — and the ways in that had nobody at
    # a keyboard could not put it to them. It is put here instead: at the door
    # of the community it is for, and nowhere else. A private community never
    # asks, and neither does the rest of the platform.
    #
    # Free in the common case: it stops on the account's own column, which is
    # already loaded, for everyone who has answered.
    if (
        not for_settings
        and current_user.age_confirmed_at is None
        and guild.is_community
        and age_gate_on
    ):
        raise GuildAccessError(
            GuildMessages.AGE_BELOW_MINIMUM
            if current_user.age_below_minimum_at is not None
            else GuildMessages.AGE_CONFIRMATION_REQUIRED
        )
    # And the deployment's own question, off the row the gate read carried.
    if await platform_factor_unmet(session, current_user, level=asked):
        raise GuildAccessError(GuildMessages.PLATFORM_AUTH_FACTOR_REQUIRED)
    if not for_settings:
        await _enforce_guild_auth_policy(
            session,
            policy,
            guild_id,
            satisfied,
            auth_context.session_amr(),
            require_second_factor=guild.require_second_factor,
        )
    return GuildContext(
        guild=guild,
        user_id=current_user.id,
        guild_id=guild_id,
        membership=membership,
        guild_role=membership.role.value,
        content_read_only=(
            not for_settings and guild.status == GuildStatus.read_only.value
        ),
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
    """The establishment seam for a REST request: who this reader is in the
    community the path addresses, and the session routed to match.

    Every guild-scoped router mounts under ``/g/{guild_id}``, so FastAPI injects
    the segment here; :func:`addressed_guild_id` decides whether that is the
    answer or whether the call's delegation already gave one. Membership (or a
    live PAM grant) is validated fresh; a non-member or stale grant gets 403. A
    guild-scoped route mounted *outside* the prefix fails at startup (missing
    path param) — a useful guard that every such route is path-addressed.

    The context it returns carries the standing computed in the routed schema,
    so it is resolved and applied together rather than in two steps that could
    disagree. ``RLSSessionDep`` is the other half of this one call: FastAPI
    caches a dependency per request, so it hands back the session this routed.
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
        return await establish_guild_access(session, current_user, guild_id)
    except GuildAccessError as exc:
        raise_for_guild_access(exc)


def raise_for_guild_access(exc: GuildAccessError) -> NoReturn:
    """Turn a refusal from the seam into the response it owes the caller.

    Three shapes: the two step-up 401s, which say what is missing and where to
    present it, and 403 for everything else.
    """
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


def holds_guild_role(
    context: GuildContext, *roles: GuildRole, settings: bool = False
) -> bool:
    """Whether this request reaches any of ``roles``, by the standing.

    :meth:`GuildContext.reaches` is the one answer — a rung asked for is that
    rung or above, and on the configuration surface (``settings``) a settings
    grant answers at the rung it lends — and this is its form for a guard
    naming several. Kept beside :func:`require_guild_roles` because some
    endpoints ask part-way through a handler rather than at the door, and the
    two must not drift.
    """
    if not roles:
        return True
    return any(context.reaches(role, settings=settings) for role in roles)


def require_seat(
    context: GuildContext, *, detail: str = GuildMessages.GUILD_SUPERADMIN_REQUIRED
) -> None:
    """Raise 403 unless this request holds the community's seat, by the
    standing — the membership row's, or lent by a settings grant at that
    rung."""
    if not context.seat:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


def _rung_refusal(roles: tuple[GuildRole, ...]) -> str:
    """The code a guard answers with, from the rung it names: a guard for
    the seat says so, one for an administrator says so, and one naming
    anything else says a permission is missing."""
    if roles == (GuildRole.superadmin,):
        return GuildMessages.GUILD_SUPERADMIN_REQUIRED
    if roles == (GuildRole.admin,):
        return GuildMessages.GUILD_ADMIN_REQUIRED
    return GuildMessages.GUILD_PERMISSION_REQUIRED


def require_guild_roles(
    *roles: GuildRole, settings: bool = False, write: bool = False
) -> Callable:
    """Guard an endpoint on the caller's rung in the guild named by the path.

    See :func:`holds_guild_role`, which is what it asks. ``settings`` puts the
    guard on the community's configuration surface — established by
    :func:`get_guild_settings_context`, which a settings grant may serve and
    an administrator keeps while the content is closed. ``write`` is a route
    that changes something: a grantee is then also asked for the
    ``read_write`` grant beside the rung (:func:`require_grant_writes`).
    The refusal's code comes from the rung named (:func:`_rung_refusal`).
    """
    establish = get_guild_settings_context if settings else get_guild_membership
    detail = _rung_refusal(roles)

    async def dependency(
        context: Annotated[GuildContext, Depends(establish)],
    ) -> GuildContext:
        if not holds_guild_role(context, *roles, settings=settings):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)
        if write:
            require_grant_writes(context)
        return context

    return dependency


def _note_privileged_request(current_user: User, guild_context: GuildContext) -> None:
    """Record on the request's own context which grant is serving it.

    Read back when the response is finished, to write the one line that says
    what this request did with the grant (``app.core.request_audit``).
    """
    grant, settings_grant = guild_context.grant, guild_context.settings_grant
    issued = grant or settings_grant
    audit_context.note_grant(
        actor_user_id=current_user.id,
        guild_id=guild_context.guild_id,
        grant_id=grant.id if grant is not None else None,
        access_level=grant.access_level if grant is not None else None,
        settings_grant_id=settings_grant.id if settings_grant is not None else None,
        settings_level=(
            settings_grant.access_level if settings_grant is not None else None
        ),
        break_glass=(
            issued.requested_by_id == issued.approved_by_id
            if issued is not None
            else None
        ),
    )


async def apply_guild_session_context(
    session: AsyncSession,
    current_user: User,
    guild_context: GuildContext,
    satisfied: frozenset[int] | str = frozenset(),
    *,
    for_seat: bool = False,
) -> GuildContext:
    """Route ``session`` into ``guild_context``'s community and compute the
    reader's standing there, returning the context that says what it is.

    The second and third of the seam's three round trips. The first — the
    lookup that decided there is any access at all, and which Postgres role
    this assumes — has already run (:func:`_load_guild_context`), and what it
    found is the ``guild_context`` handed in here.

    The routing writes the community, the credential and an empty standing.
    The standing statement then fills it, in the routed schema, from the
    database's own rows. Between the two the standing answers no to every
    membership leg, so a routing that stops half-way loses rows rather than
    gaining them.

    ``for_seat`` is the four configuration routes asking for the seat's role
    rather than the community's. It is honoured only where the seat is within
    reach; holding it and asking for it are two conditions, and an ordinary
    request by a seat holder routes as an ordinary member.
    """

    seat = for_seat and guild_context.reaches_seat

    if guild_context.is_settings_only:
        _note_privileged_request(current_user, guild_context)
        await set_rls_context(
            session,
            user_id=current_user.id,
            context=guild_context,
            settings_guild_id=guild_context.guild_id,
            seat=seat,
            platform_role=current_user.role.value,
            satisfied_providers=_satp_param(satisfied),
            satisfied_claims=auth_context.satisfied_claims(),
            session_amr=auth_context.session_amr(),
        )
        return await apply_guild_standing(session, guild_context)

    if guild_context.is_pam:
        _note_privileged_request(current_user, guild_context)
        # The routing needs the grant's level to pick the Postgres role; the
        # statement below recomputes the flags the policies read from the
        # grant rows, so what a leg answers to is the row rather than what the
        # lookup carried out of it.
        grant = guild_context.grant
        access_level = (
            grant.access_level if grant is not None else AccessLevel.read.value
        )
        await set_rls_context(
            session,
            user_id=current_user.id,
            context=guild_context,
            guild_id=None,
            pam_guild_id=guild_context.guild_id,
            pam_read=True,
            pam_write=(access_level == AccessLevel.read_write.value),
            # Break-glass is a pair: the content grant names the community on
            # the PAM axis, and a settings grant beside it names the same one
            # on the configuration axis, which is what the shared tables' own
            # policies read.
            settings_guild_id=(
                guild_context.guild_id
                if guild_context.settings_grant is not None
                else None
            ),
            seat=seat,
            platform_role=current_user.role.value,
            satisfied_providers=_satp_param(satisfied),
            satisfied_claims=auth_context.satisfied_claims(),
            session_amr=auth_context.session_amr(),
        )
        return await apply_guild_standing(session, guild_context)

    await set_rls_context(
        session,
        user_id=current_user.id,
        context=guild_context,
        guild_id=guild_context.guild_id,
        # Recorded, not routed with: the community's own role governs inside
        # the schema. It is what a later hop back out to ``public`` re-assumes.
        platform_role=current_user.role.value,
        # Community in read_only status: the membership legs evaluate normally
        # but the session assumes the SELECT-only guild_<id>_ro Postgres role,
        # so content writes are refused by Postgres rather than by app code.
        read_only=guild_context.content_read_only,
        seat=seat,
        satisfied_providers=_satp_param(satisfied),
        satisfied_claims=auth_context.satisfied_claims(),
        session_amr=auth_context.session_amr(),
    )
    return await apply_guild_standing(session, guild_context)


async def get_guild_settings_context(
    request: Request,
    session: SessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_id: Annotated[int, Path(description="Guild this request configures")],
) -> GuildContext:
    """The establishment seam for a request to the community's own
    configuration and roster.

    :func:`get_guild_membership` for the surface an administrator keeps while
    the content is closed, and the one a settings grant may serve: the same
    lookup, routing and standing, established ``for_settings`` — so the
    community's sign-in rule, a ``read_only`` freeze and the deployment's age
    question, which govern its work, do not stand between an administrator and
    the settings that govern them. A suspended community has no settings
    surface for its members: it is in time out.
    """
    guild_id = addressed_guild_id(request, guild_id)
    key_guild = getattr(request.state, "api_key_guild_id", None)
    if key_guild is not None and key_guild != guild_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=GuildMessages.GUILD_ACCESS_DENIED,
        )
    try:
        return await establish_guild_access(
            session, current_user, guild_id, for_settings=True
        )
    except GuildAccessError as exc:
        raise_for_guild_access(exc)


async def get_guild_session(
    session: SessionDep,
    guild_context: Annotated[GuildContext, Depends(get_guild_membership)],
) -> AsyncSession:
    """The session :func:`get_guild_membership` routed, for content requests.

    The routing and the standing are applied there — one seam call, of which
    this is the other half — so this adds only the refusal a content request
    owes a settings-only grant. Context is transaction-local and replayed at
    the start of every transaction (see ``app.db.session``), so post-commit
    queries need no manual re-apply.
    """
    if guild_context.is_settings_only:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=GuildMessages.GUILD_ACCESS_DENIED,
        )
    return session


async def get_guild_settings_session(
    session: SessionDep,
    _guild_context: Annotated[GuildContext, Depends(get_guild_settings_context)],
) -> AsyncSession:
    """The session :func:`get_guild_settings_context` routed, for the
    community's configuration and roster."""
    return session


async def get_guild_settings_write_session(
    session: SessionDep,
    guild_context: Annotated[GuildContext, Depends(get_guild_settings_context)],
) -> AsyncSession:
    """The same session, for a configuration route that changes something: a
    grantee is asked for the ``read_write`` grant beside the rung."""
    require_grant_writes(guild_context)
    return session


async def establish_guild_access(
    session: AsyncSession,
    current_user: User,
    guild_id: int,
    satisfied_providers: frozenset[int] | str | None = None,
    *,
    for_settings: bool = False,
    for_seat: bool = False,
) -> GuildContext:
    """Resolve guild access AND apply the session context — the single entry
    point for callers that can't use the REST dependency chain.

    *Resolve* access (membership / live PAM / break-glass, else
    ``GuildAccessError``), *route* the session and *compute the standing*,
    returning the completed ``GuildContext``. REST reaches the same three steps
    through ``get_guild_membership``; WebSocket and keepalive handlers call this
    so they cannot resolve-without-applying — the omission that denied a guild
    admin on the collaboration socket while the REST read allowed them. The caller maps ``GuildAccessError`` to its transport
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
        session, current_user, guild_id, satisfied=satisfied, for_settings=for_settings
    )
    return await apply_guild_session_context(
        session, current_user, guild_context, satisfied=satisfied, for_seat=for_seat
    )


@dataclass(frozen=True)
class VerifiedInstall:
    """An install whose token has been verified: the community it is installed
    in, the install, the client the token was issued to, the scopes it carries,
    and the one initiative it is narrowed to, when it is."""

    guild_id: int
    install_id: int
    client_id: str
    scopes: frozenset[str]
    initiative_id: int | None = None


class InstallAccessError(Exception):
    """Transport-agnostic "this install may not act here" signal.

    Raised by :func:`establish_install_access` when the install's standing is
    not live, or its community cannot be routed into. The route dependency maps
    it to 401.
    """


async def establish_install_access(
    session: AsyncSession, install: VerifiedInstall
) -> InstallContext:
    """Route ``session`` as an installed app and compute its standing — the
    establishment seam for an install, beside :func:`establish_guild_access`.

    Two statements and no lookup ahead of them: the routing (the community's
    ``guild_<id>_app`` role, the install, its client, its token's scopes and
    the narrowed initiative, all from ``install``), and the install standing
    statement, which reads everything else from rows. The context it returns
    is what that statement computed, and is stored with the routing for the
    replay hook.

    Raises :class:`InstallAccessError` when the standing is not live — the
    community is not in use, the install or its registration is off, or the
    registration is not the client the token names — and when the community
    has no role or schema to route into. The session is left unrouted after a
    refusal of the second kind, with its transaction rolled back.
    """
    try:
        scopes = validate_scopes(install.scopes)
    except UnknownAppScope as exc:
        raise InstallAccessError("unknown scope") from exc
    pending = InstallContext(
        guild_id=int(install.guild_id),
        install_id=int(install.install_id),
        client_id=install.client_id,
        token_scopes=scopes,
        scope_initiative_id=(
            int(install.initiative_id) if install.initiative_id is not None else None
        ),
    )
    try:
        await set_rls_context(
            session,
            guild_id=pending.guild_id,
            context=pending,
            install_id=pending.install_id,
            token_client_id=pending.client_id,
            token_scopes=pending.token_scopes,
            scope_initiative_id=pending.scope_initiative_id,
        )
        completed = await apply_install_standing(session, pending)
    except DBAPIError as exc:
        # A community that was deleted has no role left to assume and no schema
        # to read, which is the same answer as an install that may not act.
        clear_rls_context(session)
        await session.rollback()
        raise InstallAccessError("community cannot be routed") from exc
    if not completed.live:
        raise InstallAccessError("install is not live")
    return completed


#: Who a scoped route is serving: a person's standing in the community, or an
#: installed app's.
ActorContext = GuildContext | InstallContext

#: The attribute a scoped route's dependency carries its scope on, for a walk
#: over the routes.
APP_SCOPE_ATTRIBUTE = "__app_scope__"


def _refuse_install_credential() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=AuthMessages.COULD_NOT_VALIDATE_CREDENTIALS,
        headers={"WWW-Authenticate": "Bearer"},
    )


def scope_covers(scopes: frozenset[str], scope: str) -> bool:
    """Whether ``scopes`` include ``scope``. Writing implies reading."""
    resource, access = parse_scope(scope)
    try:
        read, write = expand(scopes)
    except UnknownAppScope:
        return False
    return resource in (write if access is AppScopeAccess.write else read)


async def _establish_install_request(
    request: Request, session: AsyncSession, token: str, scope: str
) -> InstallContext:
    """Admit an installed app's request to a route that names ``scope``.

    The token is read locally; nothing reaches the database until it has been
    unsealed and found to be an installation token. Then the seam routes the
    request's session as the install and computes its standing, the two
    statements an install pays before its handler.
    """
    try:
        unsealed = unseal_access_token(token)
    except AccessTokenError as exc:
        raise _refuse_install_credential() from exc
    if not isinstance(unsealed, InstallAccessToken):
        raise _refuse_install_credential()

    install = VerifiedInstall(
        guild_id=unsealed.guild_id,
        install_id=unsealed.install_id,
        client_id=unsealed.client_id,
        scopes=unsealed.scopes,
        initiative_id=unsealed.initiative_id,
    )
    try:
        context = await establish_install_access(session, install)
    except InstallAccessError as exc:
        raise _refuse_install_credential() from exc

    request.state.credential = CREDENTIAL_INSTALL
    # Whose request this is, for the rate limiter's key (see
    # ``app.core.rate_limit.get_user_or_ip_key``).
    request.state.app_install = (
        context.client_id,
        context.guild_id,
        context.install_id,
    )
    if not scope_covers(context.token_scopes, scope):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=AppMessages.SCOPE_REQUIRED,
        )
    return context


def app_scope(scope: str) -> Callable[..., Awaitable[ActorContext]]:
    """The dependency a route names to admit an installed app, at ``scope``.

    A person passes through to the ordinary seam, exactly as
    :data:`GuildContextDep` would take them, so one route serves both. An
    installation token is admitted only here: :func:`get_current_user` refuses
    one, so a route that names no scope cannot be reached by an app. For an
    install, the guild comes from the token and the path's ``{guild_id}`` is
    not read (``history/opaque-identity-design.md`` §13); a token whose scopes
    do not cover ``scope`` gets 403 (``APP_SCOPE_REQUIRED``).

    Either way the request's session — the one :data:`SessionDep` hands out,
    which FastAPI resolves once per request — is routed before the handler
    runs. A scoped route reads it through :data:`ActorSessionDep`.

    The returned callable carries ``scope`` on :data:`APP_SCOPE_ATTRIBUTE`.
    A route names it the way the type checker reads, as a module-level alias
    or inline::

        DocumentsRead = Annotated[ActorContext, Depends(app_scope("documents:read"))]

        async def list_documents(actor: DocumentsRead, session: ActorSessionDep): ...
    """
    parse_scope(scope)

    async def dependency(
        request: Request,
        session: SessionDep,
        guild_id: Annotated[int, Path(description="Guild this request operates in")],
        bearer_token: Annotated[Optional[str], Depends(oauth2_scheme)] = None,
        session_cookie: Annotated[
            Optional[str], Cookie(alias=SESSION_COOKIE_NAME)
        ] = None,
    ) -> ActorContext:
        if bearer_token and is_access_token(bearer_token):
            return await _establish_install_request(
                request, session, bearer_token, scope
            )
        # A person: the same three dependencies a content route composes, in
        # the same order, called here so an install never passes through them.
        user = await get_current_user(request, session, bearer_token, session_cookie)
        user = await get_current_active_user(request, session, user)
        context = await get_guild_membership(request, session, user, guild_id)
        if context.is_settings_only:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=GuildMessages.GUILD_ACCESS_DENIED,
            )
        return context

    setattr(dependency, APP_SCOPE_ATTRIBUTE, scope)
    dependency.__name__ = f"app_scope_{scope.replace(':', '_')}"
    dependency.__qualname__ = dependency.__name__
    return dependency


def route_app_scope(route: Any) -> str | None:
    """The app scope a route names, or ``None``: read from its dependencies."""
    dependant = getattr(route, "dependant", None)
    pending = list(getattr(dependant, "dependencies", ()) or ())
    while pending:
        current = pending.pop()
        found = getattr(current.call, APP_SCOPE_ATTRIBUTE, None)
        if isinstance(found, str):
            return found
        pending.extend(current.dependencies or ())
    return None


async def get_actor_session(request: Request, session: SessionDep) -> AsyncSession:
    """The session a scoped route's :func:`app_scope` dependency routed.

    The same instance, since FastAPI resolves :data:`SessionDep` once per
    request, and every dependency resolves before the handler runs, so by then
    it is routed as the person or the install. A route that takes this without
    naming a scope is a wiring mistake, and is refused as one.
    """
    if route_app_scope(request.scope.get("route")) is None:
        raise RuntimeError("ActorSessionDep is for a route that names an app scope")
    return session


#: The routed session of a route that names an app scope.
ActorSessionDep = Annotated[AsyncSession, Depends(get_actor_session)]


async def get_guild_seat_context(
    guild_id: int,
    session: SessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> GuildContext:
    """Route this request into the community's seat, or refuse it.

    The seat is the rung above ``admin``: a community's sign-in configuration
    and what it pays for. It is reached by the membership row that says so, or
    by a live settings grant at that rung, and the session assumes
    ``guild_<id>_superadmin`` — the one role whose floor carries those tables.
    Every other route by the same person routes as an ordinary member.
    """
    try:
        context = await establish_guild_access(
            session, current_user, guild_id, for_settings=True, for_seat=True
        )
    except GuildAccessError as exc:
        raise_for_guild_access(exc)
    if not context.seat:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=GuildMessages.GUILD_SUPERADMIN_REQUIRED,
        )
    return context


async def get_guild_seat_session(
    session: SessionDep,
    _context: Annotated[GuildContext, Depends(get_guild_seat_context)],
) -> AsyncSession:
    """The session :func:`get_guild_seat_context` routed, for the four
    configuration routes the seat holds."""
    return session


def require_grant_writes(context: GuildContext) -> None:
    """Refuse a change from a grantee whose grants read.

    A settings rung reaches the community's configuration; changing it takes
    a ``read_write`` content grant beside the rung — the two asks together.
    The membership row's administrator is not a grantee and passes.
    """
    if not context.grant_writes:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=AccessGrantMessages.WRITE_GRANT_REQUIRED,
        )


async def get_guild_seat_write_context(
    context: Annotated[GuildContext, Depends(get_guild_seat_context)],
) -> GuildContext:
    """The seat, for a route that changes what the seat holds.

    Held by the membership row, the seat writes. Lent by a settings grant, it
    reads, and writes only beside a live ``read_write`` content grant."""
    require_grant_writes(context)
    return context


async def get_guild_seat_write_session(
    session: SessionDep,
    _context: Annotated[GuildContext, Depends(get_guild_seat_write_context)],
) -> AsyncSession:
    """The session :func:`get_guild_seat_write_context` routed."""
    return session


# Dependency for routes that need RLS-aware database access
RLSSessionDep = Annotated[AsyncSession, Depends(get_guild_session)]
SettingsContextDep = Annotated[GuildContext, Depends(get_guild_settings_context)]
# The configuration surface, by rung: what an administrator keeps while the
# content is closed and what a settings grant may serve, and — for a route
# that changes something — asking a grantee for the read_write grant beside
# the rung.
SettingsAdminContextDep = Annotated[
    GuildContext, Depends(require_guild_roles(GuildRole.admin, settings=True))
]
SettingsAdminWriteContextDep = Annotated[
    GuildContext,
    Depends(require_guild_roles(GuildRole.admin, settings=True, write=True)),
]
SettingsSeatWriteContextDep = Annotated[
    GuildContext,
    Depends(require_guild_roles(GuildRole.superadmin, settings=True, write=True)),
]
SettingsRLSSessionDep = Annotated[AsyncSession, Depends(get_guild_settings_session)]
SettingsWriteSessionDep = Annotated[
    AsyncSession, Depends(get_guild_settings_write_session)
]
SeatContextDep = Annotated[GuildContext, Depends(get_guild_seat_context)]
SeatWriteContextDep = Annotated[GuildContext, Depends(get_guild_seat_write_context)]
SeatSessionDep = Annotated[AsyncSession, Depends(get_guild_seat_session)]
SeatWriteSessionDep = Annotated[AsyncSession, Depends(get_guild_seat_write_session)]


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
    own tier. The body the user-session dependencies share.

    A suspended account holds no rung while it is in time out, so it is routed
    as ``platform_suspended`` whatever ``users.role`` says — its own rows, read,
    and nothing written. The rung comes back untouched when the suspension
    lifts.
    """
    tier = (
        PLATFORM_SUSPENDED
        if current_user.status == UserStatus.suspended
        else current_user.role.value
    )
    await set_rls_context(
        session,
        user_id=current_user.id,
        platform_role=tier,
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


async def get_account_holder_session(
    session: SessionDep,
    current_user: AccountHolder,
) -> AsyncSession:
    """The platform-path session for a time-out allow-list route."""
    return await _apply_user_session_context(session, current_user)


async def get_factor_exempt_account_holder_session(
    session: SessionDep,
    current_user: FactorExemptAccountHolder,
) -> AsyncSession:
    """The platform-path session for a factor-exempt time-out allow-list route."""
    return await _apply_user_session_context(session, current_user)


AccountHolderSessionDep = Annotated[AsyncSession, Depends(get_account_holder_session)]
FactorExemptAccountHolderSessionDep = Annotated[
    AsyncSession, Depends(get_factor_exempt_account_holder_session)
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
            token_markers,
        ) = verify_upload_token(token_param)
    except UploadTokenError:
        pass
    else:
        # The scoped token copied its minting session's satisfied set — record
        # it so the guild auth-policy gate treats this request as that session.
        set_satisfied_providers(token_satisfied)
        set_satisfied_claims(token_claims)
        set_session_amr(policy_markers(token_markers))
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
    set_session_amr(None)
    set_device_token_id(None)
    set_api_key_credential(False)
    set_asked_of_account(None)

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

    # An installed app's access token is never a person, here as on every
    # other route that names no app scope.
    if is_access_token(token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=AuthMessages.COULD_NOT_VALIDATE_CREDENTIALS,
            headers={"WWW-Authenticate": "Bearer"},
        )

    # A personal API key names itself by its prefix; anything else is not one.
    api_auth = (
        await api_keys_service.authenticate_api_key(session, token)
        if token.startswith(api_keys_service.API_KEY_PREFIX)
        else None
    )
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

    account = await account_for_subject(session, subject=token_data.sub)
    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=AuthMessages.USER_NOT_FOUND
        )
    user, settings_row = account
    if token_data.ver is None or token_data.ver != user.token_version:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=AuthMessages.INVALID_TOKEN
        )
    set_asked_of_account(_asked_of_an_account(settings_row))
    if user.status != UserStatus.active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=AuthMessages.INACTIVE_USER
        )
    set_satisfied_providers(frozenset(token_data.sat or ()))
    set_satisfied_claims(claims_from_provider_auth(token_data.satd))
    # What the session proved about the person, read from its own ``amr`` as
    # ``get_current_user`` reads it — a community asking for either answers a
    # picture and a download the same way it answers a page.
    set_session_amr(policy_markers(token_data.amr))
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
