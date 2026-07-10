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
from app.core.config import API_V1_STR, settings
from app.core.pam_context import set_active_grant
from app.core.role_context import (
    set_active_role,
    set_content_read_only_guild,
    set_override_sharing_initiatives,
)
from app.core.messages import AuthMessages, GuildMessages, UserMessages
from app.core.security import (
    SESSION_COOKIE_NAME,
    AutoDelegationVerificationError,
    UploadTokenError,
    decode_session_token,
    verify_auto_delegation_token,
    verify_upload_token,
)
from app.db.session import get_session, set_rls_context
from app.models.platform.access_grant import AccessGrant, AccessLevel
from app.models.platform.api_key import UserApiKey
from app.models.platform.guild import Guild, GuildMembership, GuildRole, GuildStatus
from app.models.platform.user import User, UserRole, UserStatus
from app.schemas.platform.token import TokenPayload
from app.services.platform import access_grants as access_grants_service
from app.services.platform import api_keys as api_keys_service
from app.services.platform import auto_delegation_blocklist
from app.services.platform import guilds as guilds_service
from app.services.platform import user_tokens

SessionDep = Annotated[AsyncSession, Depends(get_session)]

oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl=f"{API_V1_STR}/auth/token", auto_error=False
)


async def _authenticate_device_token(
    session: AsyncSession, token: str
) -> Optional[User]:
    """Authenticate using a device token and return the associated user."""
    device_token = await user_tokens.get_device_token(session, token=token)
    if not device_token:
        return None
    statement = select(User).where(User.id == device_token.user_id)
    result = await session.exec(statement)
    return result.one_or_none()


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

    A verified token also pins the request's guild context to the token's
    ``guild_id`` claim (via ``request.state.delegated_guild_id``): delegation
    tokens are minted for exactly one guild, and a machine caller has no
    guild context of its own to resolve from. The claim is validated against
    the user's memberships and must agree with the ``/g/{guild_id}`` path, so an
    auto workflow always acts in the guild its token was issued for.
    """
    if not settings.AUTO_DELEGATION_PUBLIC_KEY_PEM:
        return None  # delegation disabled — let other auth paths run

    try:
        claims = verify_auto_delegation_token(token)
    except AutoDelegationVerificationError:
        # Could be a session JWT or API key arriving on the same header.
        # Returning None lets the caller try those instead of failing.
        return None

    # Replay guard: a delegation JWT is one-shot. Even though the JWT is
    # technically valid for 15 minutes, a captured token must not be
    # usable a second time. The pre-flight ``is_jti_redeemed`` is a fast
    # path; the ``record_jti`` insert below is the actual race-safe
    # guarantee (unique-violation on the PK).
    if await auto_delegation_blocklist.is_jti_redeemed(session, claims.jti):
        return None

    statement = select(User).where(User.id == claims.user_id)
    result = await session.exec(statement)
    user = result.one_or_none()
    if user is None or user.status != UserStatus.active:
        # The user the token names doesn't exist or has been deactivated
        # since the token was minted. Auto can't impersonate non-active
        # accounts — workflows die when their owner leaves, by design.
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
    request.state.delegated_guild_id = claims.guild_id

    return user


def _delegation_exp_from_jwt(token: str) -> datetime:
    """Pull the ``exp`` timestamp out of a delegation JWT without
    re-verifying. Caller has already verified — we just need the value
    for the blocklist row's ``expires_at`` column so the cleanup job
    can prune expired entries.
    """
    payload = jwt.decode(token, options={"verify_signature": False})
    return datetime.fromtimestamp(int(payload["exp"]), tz=timezone.utc)


_SAFE_HTTP_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


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
    # Check for Authorization header - could be Bearer, DeviceToken, or API key
    auth_header = request.headers.get("Authorization", "")

    # Handle DeviceToken scheme
    if auth_header.startswith("DeviceToken "):
        device_token = auth_header[12:]  # len("DeviceToken ") = 12
        user = await _authenticate_device_token(session, device_token)
        if user:
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
        return user

    # Try delegation JWT from initiative-auto (RS256, distinct audience).
    # Returns None on shape/algorithm mismatch so a regular HS256 session
    # JWT carrying through this header gracefully falls through to the
    # next branch.
    user = await _authenticate_auto_delegation(request, session, token)
    if user:
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

    if not token_data.sub:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=AuthMessages.INVALID_TOKEN_PAYLOAD,
            headers={"WWW-Authenticate": "Bearer"},
        )

    statement = select(User).where(User.id == int(token_data.sub))
    result = await session.exec(statement)
    user = result.one_or_none()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=AuthMessages.USER_NOT_FOUND
        )
    if token_data.ver is None or token_data.ver != user.token_version:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=AuthMessages.INVALID_TOKEN
        )
    return user


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


async def get_current_active_user(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    if current_user.status != UserStatus.active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=AuthMessages.INACTIVE_USER
        )
    return current_user


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
    # Set when access is via a time-bound PAM grant rather than real
    # membership. The ``membership`` is then a synthesized member-role stand-in
    # so ``.role`` stays valid for endpoint guards, while RLS context is driven
    # off the grant (scoped pam_read/pam_write, not the all-guild bypass).
    grant: Optional[AccessGrant] = None
    # True when the grant is a read_write *break-glass* grant held by a
    # ``data.bypass`` user. Break-glass is deliberately unlimited — the holder
    # acts as a full guild admin for the grant's window (synthesized admin role
    # + guild-admin RLS context), unlike a regular PAM grant which stays scoped
    # to content read/write. Still grant-gated: no live grant, no reach.
    break_glass: bool = False
    # True when the guild is in ``read_only`` status and access is via real
    # membership: the session is routed into the SELECT-only ``guild_<id>_ro``
    # Postgres role so content writes are denied at the role level. Never set
    # on the grant branches — PAM/break-glass override the guild status.
    content_read_only: bool = False

    @property
    def guild_id(self) -> int:
        return self.guild.id  # ty: ignore[invalid-return-type]

    @property
    def role(self) -> GuildRole:
        return self.membership.role

    @property
    def is_pam(self) -> bool:
        return self.grant is not None


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

    def __init__(self, detail: str = GuildMessages.GUILD_ACCESS_DENIED) -> None:
        self.detail = detail
        super().__init__(detail)


async def _load_guild_context(
    session: AsyncSession,
    current_user: User,
    guild_id: int,
) -> GuildContext:
    """Resolve and validate the guild context for one guild.

    ``guild_id`` is the single guild the request operates in (on REST it comes
    from the ``/g/{guild_id}/...`` path, which is only a selector, never a trust
    boundary). Access is validated fresh on every call — real membership or a
    live PAM grant, else ``GuildAccessError`` — so a forged or stale guild can
    never read another guild's data. The caller has already coerced ``guild_id``
    to ``int`` before it reaches the privileged ``SET ROLE``/``search_path`` sink.

    Transport-agnostic: it takes only the resolved ``guild_id``. The REST-only
    auto-delegation guard (token-guild must equal path-guild) lives in
    ``get_guild_membership``, where both values exist — WS / keepalive callers
    have no delegation token, so the shared resolver never deals with one.
    """
    # Set minimal RLS context before querying guild_memberships (RLS-protected).
    # Full guild context is set later by get_guild_session / RLSSessionDep.
    # No standing bypass: a user reads their own membership row via the own-row
    # policy leg; a non-member ``data.bypass`` holder finds nothing here and must
    # break-glass into a PAM grant (below) to reach the guild — never ambiently.
    await set_rls_context(
        session,
        user_id=current_user.id,
    )

    membership = await guilds_service.get_membership(
        session,
        guild_id=guild_id,
        user_id=current_user.id,
    )
    if membership is None:
        # No standing membership — fall back to a live PAM grant for this
        # guild. The grantee can read (and write, if read_write) within the
        # grant's window; RLS scopes it to this one guild via the pam flags
        # set in get_guild_session. A synthesized member-role membership keeps
        # ``GuildContext.role`` valid for endpoint guards without conferring
        # any guild privilege on its own.
        grant = await access_grants_service.get_live_grant(
            session, user_id=current_user.id, guild_id=guild_id
        )
        if grant is None:
            raise GuildAccessError()
        # A read_write grant held by a ``data.bypass`` user is a *break-glass*
        # grant: the holder acts as a full guild admin for its window (see
        # GuildContext.break_glass). A read grant — or any grant held by a
        # non-bypass requester (support/moderator's request→approve flow) — stays
        # a scoped PAM grantee. Both are gated on the live grant existing.
        is_read_write = grant.access_level == AccessLevel.read_write.value
        break_glass = is_read_write and user_has_capability(
            current_user, Capability.DATA_BYPASS
        )
        # Apply the pam context now so the grantee can actually read the guild
        # row (and below, get_guild_session re-applies the full context). The
        # guilds table has an additive pam_read policy keyed on pam_guild_id.
        await set_rls_context(
            session,
            user_id=current_user.id,
            pam_guild_id=guild_id,
            pam_read=True,
            pam_write=is_read_write,
        )
        guild = await guilds_service.get_guild(session, guild_id=guild_id)
        # Break-glass acts as a full guild admin; a scoped grantee gets the
        # ``support`` role — a first-class identity for PAM access rather than a
        # ``member`` masquerade. ``support`` clears no admin guard (it is not
        # ``admin``) but does open the guild settings surface (bound by the
        # grant's read/write level at the Postgres role layer). The role is
        # in-memory only; it never reaches ``set_rls_context`` (the ``is_pam``
        # branch passes ``guild_role=None``), so the ``guild_role`` GUC and DB
        # enum stay admin/member.
        synthetic = GuildMembership(
            guild_id=guild_id,
            user_id=current_user.id,
            role=GuildRole.admin if break_glass else GuildRole.support,
        )
        return GuildContext(
            guild=guild, membership=synthetic, grant=grant, break_glass=break_glass
        )
    guild = await guilds_service.get_guild(session, guild_id=guild_id)
    # Guild lifecycle status gates REAL MEMBERS ONLY — the grant branch above
    # deliberately never consults it (PAM/break-glass behave exactly as against
    # an active guild, so suspending a guild can never lock operators out).
    # This resolver is the one layer where a grantee is still distinguishable
    # from a member: at the DB layer break-glass is byte-identical to a real
    # guild admin, so the status check cannot live in RLS. ``suspended`` fails
    # closed with the generic access-denied code (the status is not disclosed
    # to members); ``read_only`` keeps membership but routes the session into
    # the SELECT-only guild role (see _apply_guild_session_context).
    if guild.status == GuildStatus.suspended.value:
        raise GuildAccessError()
    return GuildContext(
        guild=guild,
        membership=membership,
        content_read_only=(guild.status == GuildStatus.read_only.value),
    )


async def get_guild_membership(
    request: Request,
    session: SessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_id: Annotated[int, Path(description="Guild this request operates in")],
) -> GuildContext:
    """Strict guild context resolved from the ``/g/{guild_id}`` path segment.

    Every guild-scoped router mounts under that prefix, so FastAPI injects
    ``guild_id`` from the path into this dependency. Membership (or a live PAM
    grant) is validated fresh; a non-member or stale grant gets 403. A
    guild-scoped route mounted *outside* the prefix fails at startup (missing
    path param) — a useful guard that every such route is path-addressed.
    """
    # Auto-delegation tokens are pinned to one guild at mint time; refuse if the
    # path addresses a different guild than the token was minted for. This is a
    # REST/token-only guard (a delegation token can only arrive over HTTP), so it
    # lives here — the one place that sees both the token's guild and the path's —
    # not in the shared resolver that the WebSocket/keepalive callers also use.
    delegated = getattr(request.state, "delegated_guild_id", None)
    if delegated is not None and delegated != guild_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=GuildMessages.GUILD_ACCESS_DENIED,
        )
    # A guild-bound API key (PAT) is pinned to one guild the same way: refuse if
    # the path addresses a different guild than the key was scoped to.
    key_guild = getattr(request.state, "api_key_guild_id", None)
    if key_guild is not None and key_guild != guild_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=GuildMessages.GUILD_ACCESS_DENIED,
        )
    try:
        return await _load_guild_context(session, current_user, guild_id)
    except GuildAccessError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=exc.detail
        ) from exc


def require_guild_roles(*roles: GuildRole) -> Callable:
    async def dependency(
        context: Annotated[GuildContext, Depends(get_guild_membership)],
    ) -> GuildContext:
        if roles and context.membership.role not in roles:
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
) -> AsyncSession:
    """Route ``session`` into ``guild_context``'s guild: set the RLS/session
    variables (and the request-scoped PAM/role contexts) for the user+guild,
    PAM-scoped when access is via a grant."""
    if guild_context.break_glass:
        # Break-glass (read_write grant + data.bypass): deliberately unlimited —
        # the holder acts as a full guild admin for the grant's window. Route
        # exactly like a real guild admin (current_guild_id + current_guild_role
        # 'admin' + SET ROLE guild_<id>) so every guild-admin RLS/app-layer leg
        # fires, including management ops. We intentionally DON'T set the PAM
        # active-grant context: that would trip the grant-only management blocks
        # (e.g. PROJECT_GRANT_CANNOT_MANAGE_MEMBERS) — break-glass has no limits.
        # Still grant-gated: this path is only reached because a live grant exists.
        set_active_grant(None, None)
        set_active_role(guild_context.guild_id, GuildRole.admin.value)
        # Break-glass acts as a full guild admin, which already bypasses gate 4
        # everywhere; the per-initiative "Full access" set is moot here.
        set_override_sharing_initiatives(None)
        # Break-glass overrides the guild lifecycle status by design.
        set_content_read_only_guild(None)
        await set_rls_context(
            session,
            user_id=current_user.id,
            guild_id=guild_context.guild_id,
            guild_role=GuildRole.admin.value,
        )
        return session

    if guild_context.is_pam:
        # Scoped, time-bound access via a PAM grant — NOT the all-guild bypass.
        # Read grants get SELECT into this guild only; read_write also gets
        # writes. guild_role is left unset so guild-role-gated paths don't treat
        # the grantee as a member.
        grant = guild_context.grant
        access_level = (
            grant.access_level if grant is not None else AccessLevel.read.value
        )
        # Mirror the grant into the request-scoped PAM context so the app-layer
        # resource access checks (require_*_access) honor it consistently with
        # RLS — what the grantee can list, they can also open/edit per level.
        set_active_grant(guild_context.guild_id, access_level)
        # No real membership — leave the role context clear so role-gated
        # paths (initiative-scope guild-admin bypass) don't treat the grantee
        # as a member.
        set_active_role(None, None)
        # A PAM grantee holds no initiative role, so no "Full access" override.
        set_override_sharing_initiatives(None)
        # A scoped grant overrides the guild lifecycle status by design (its
        # read/write level is enforced at the Postgres role layer instead).
        set_content_read_only_guild(None)
        # Leave current_guild_id unset — the existing write policies treat a
        # matching current_guild_id as proof of membership. Scope the grant via
        # pam_guild_id instead.
        await set_rls_context(
            session,
            user_id=current_user.id,
            guild_id=None,
            guild_role=None,
            pam_guild_id=guild_context.guild_id,
            pam_read=True,
            pam_write=(access_level == AccessLevel.read_write.value),
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
    # No standing all-guild bypass: a guild admin sees the whole guild via the
    # ``current_guild_role='admin'`` RLS leg (and the guild role they SET into),
    # never an ambient bypass. A ``data.bypass`` holder who isn't a member reaches
    # this guild only through a break-glass PAM grant (the ``is_pam`` branch above).
    await set_rls_context(
        session,
        user_id=current_user.id,
        guild_id=guild_context.guild_id,
        guild_role=guild_context.role.value,
        # Guild in read_only status: keep the full membership GUCs (so the
        # initiative-member and admin RLS legs evaluate normally) but assume
        # the SELECT-only guild_<id>_ro Postgres role — content writes are
        # denied by Postgres, not app code.
        read_only=guild_context.content_read_only,
    )
    # Precompute the initiatives where this member holds "Full access" so the
    # sync DAC checks can apply the gate-4 override without an async query. Runs
    # in the routed guild schema (after SET ROLE), so it sees this guild's roles.
    from app.services import rls as rls_service

    override_ids = await rls_service.override_sharing_initiative_ids(
        session, user_id=current_user.id
    )
    set_override_sharing_initiatives(frozenset(override_ids))
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
    return await _apply_guild_session_context(session, current_user, guild_context)


async def establish_guild_access(
    session: AsyncSession,
    current_user: User,
    guild_id: int,
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
    """
    guild_context = await _load_guild_context(session, current_user, guild_id)
    await _apply_guild_session_context(session, current_user, guild_context)
    return guild_context


# Dependency for routes that need RLS-aware database access
RLSSessionDep = Annotated[AsyncSession, Depends(get_guild_session)]


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

    No standing all-guild bypass: a platform admin's cross-user/guild
    reach on this path is authorized by the ``platform_<tier>`` RLS policies
    (Phase 2), and reaching a guild's *data* requires an explicit break-glass
    PAM grant (§7), never an ambient flag.
    """
    await set_rls_context(
        session,
        user_id=current_user.id,
        platform_role=current_user.role.value,
    )
    return session


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
        user_id = verify_upload_token(token_param)
    except UploadTokenError:
        pass
    else:
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


async def get_upload_user(
    request: Request,
    session: SessionDep,
    bearer_token: Annotated[Optional[str], Depends(oauth2_scheme)] = None,
    token_param: Annotated[Optional[str], Query(alias="token")] = None,
    session_cookie: Annotated[Optional[str], Cookie(alias=SESSION_COOKIE_NAME)] = None,
) -> User:
    """Auth dependency for /uploads/* and authenticated document downloads.

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

    statement = select(User).where(User.id == int(token_data.sub))
    result = await session.exec(statement)
    user = result.one_or_none()
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
    return user


UploadUserDep = Annotated[User, Depends(get_upload_user)]
