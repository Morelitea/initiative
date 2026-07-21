import asyncio
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncGenerator, Optional, Sequence

from alembic import command
from alembic.config import Config
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session as SyncSession
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.db import base  # noqa: F401  # ensure models are imported for Alembic

# Primary engine: non-superuser (DATABASE_URL_APP) for RLS-enforced queries.
engine = create_async_engine(settings.DATABASE_URL_APP, echo=False)

# System engine: background jobs, startup seeding, platform lifecycle.
# The textbook Postgres trusted-batch actor: BYPASSRLS, bounded by
# enumerated per-table GRANTs (migration 0129). Guild schemas still
# require SET ROLE guild_<id>, which drops the bypass.
admin_engine = create_async_engine(settings.DATABASE_URL_ADMIN, echo=False)

# Provisioning engine: superuser credentials (same as migrations) for privileged
# DDL — CREATE SCHEMA / CREATE ROLE — which app_user and app_admin can't do.
provisioning_engine = create_async_engine(settings.DATABASE_URL, echo=False)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    autoflush=False,
    expire_on_commit=False,
    class_=AsyncSession,
)

AdminSessionLocal = async_sessionmaker(
    bind=admin_engine,
    autoflush=False,
    expire_on_commit=False,
    class_=AsyncSession,
)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    # No checkout reset: context is transaction-local (set_config is_local +
    # SET LOCAL semantics), so a pooled connection carries NO role/GUC/
    # search_path state between transactions — there is nothing to clear.
    # The pool's rollback-on-return is the only baseline needed.
    async with AsyncSessionLocal() as session:
        yield session


async def get_admin_session() -> AsyncGenerator[AsyncSession, None]:
    """Get a session on the system engine (background jobs, bootstrapping,
    platform lifecycle). ``app_admin`` is the standard Postgres trusted-batch
    actor — BYPASSRLS, bounded by enumerated per-table GRANTs (0129); guild
    schemas require ``SET ROLE guild_<id>`` (dropping the bypass) via
    set_rls_context(). Context is transaction-local, so a recycled pooled
    connection starts every session at the login-role/public baseline with
    no reset round-trip."""
    async with AdminSessionLocal() as session:
        yield session


def clear_rls_context(session: AsyncSession) -> None:
    """Drop the session's stored context so no replay occurs.

    Production sessions are per-request and die with their context; a
    long-lived session that is REUSED across logical request boundaries (the
    test harness's connection-bound sessions) calls this at each boundary so
    the next transaction begins unrouted — fresh-session equivalence.
    """
    session.info.pop(_RLS_PARAMS_INFO_KEY, None)
    session.info.pop(_RLS_ESTABLISHED_INFO_KEY, None)


# --- Transaction-local RLS context -----------------------------------------
#
# All request context (assumed role, search_path, app.* GUCs) is applied with
# set_config(..., is_local => true) — the SET LOCAL equivalent — so it DIES
# WITH THE TRANSACTION. Nothing session-level is ever set: a forgotten reset
# is unrepresentable, and the connection carries zero cross-transaction state
# (the property a transaction-mode pooler requires).
#
# The parameters live in session.info; the _replay_rls_context after_begin
# hook re-applies them at the start of EVERY transaction (autobegin after a
# commit() included), on whatever pooled connection the transaction landed on.
# See history/transaction-scoped-context-design.md.

# Maximum age of a *user-derived* authorization snapshot. The stored params
# capture membership / guild role / PAM state as validated by
# establish_guild_access; replaying them indefinitely would launder a revoked
# grant. The realtime spine re-validates sockets every REAUTH_INTERVAL_SECONDS
# (= half this bound; stream_authz derives it from this constant), so any
# properly registered consumer refreshes long before the floor. Only a
# consumer that HOLDS a routed session without re-validating hits it — which
# must fail. System contexts (no user_id: workers, seeding) are not
# user-authorization snapshots and are exempt.
RLS_CONTEXT_MAX_AGE_SECONDS = 60

_RLS_PARAMS_INFO_KEY = "rls_params"

# Sentinel for ``satisfied_providers``: user-attributed system work (e.g. a
# background export running as its creator) whose enqueueing request already
# passed the guild-access gate. public.guild_auth_satisfied() treats it as
# satisfied; only grep-auditable system-engine code paths may set it.
SYSTEM_SATISFIED = "system"
_RLS_ESTABLISHED_INFO_KEY = "rls_established_at"


class StaleAuthorizationContext(RuntimeError):
    """A transaction tried to begin on an authorization snapshot older than
    RLS_CONTEXT_MAX_AGE_SECONDS. Re-validate via establish_guild_access (or
    re-call set_rls_context with freshly validated inputs) instead of holding
    a routed session past the bound."""


_ROLE_RESET_SQL = "SELECT set_config('role', 'none', true)"

_CONTEXT_SQL = (
    "SELECT set_config('app.current_user_id', :uid, true), "
    "set_config('app.current_guild_id', :gid, true), "
    "set_config('app.current_guild_role', :grole, true), "
    "set_config('app.pam_guild_id', :pgid, true), "
    "set_config('app.pam_read', :pr, true), "
    "set_config('app.pam_write', :pw, true), "
    "set_config('app.satisfied_providers', :satp, true), "
    "set_config('app.billing_guild_id', :bgid, true), "
    "set_config('search_path', :sp, true), "
    "set_config('role', :role, true)"
)


def _render_context_bind_params(params: dict[str, Any]) -> dict[str, str]:
    """Compute the bind params for _CONTEXT_SQL from stored rls params.

    Pure function shared by the async apply path (set_rls_context) and the
    sync after_begin replay hook — one routing decision, two executors.
    """
    user_id = params.get("user_id")
    guild_id = params.get("guild_id")
    guild_role = params.get("guild_role")
    pam_guild_id = params.get("pam_guild_id")
    pam_read = bool(params.get("pam_read"))
    pam_write = bool(params.get("pam_write"))
    platform_role = params.get("platform_role")
    read_only = bool(params.get("read_only"))
    billing_guild_id = params.get("billing_guild_id")

    # Billing-service path (set_billing_context): assumes the
    # initiative_billing role with only the billing GUC set — no
    # user/guild/PAM context.
    if billing_guild_id is not None:
        from app.db.schema_provisioning import billing_role_name

        return {
            "uid": "",
            "gid": "",
            "grole": "",
            "pgid": "",
            "pr": "false",
            "pw": "false",
            "satp": "",
            "bgid": str(int(billing_guild_id)),
            "sp": "public",
            "role": billing_role_name(),
        }

    # Route guild-scoped tables to the active guild's schema AND assume that
    # guild's role. The login role has no standing access to any guild schema
    # (fail-closed) — it must SET ROLE into the per-guild role. int() makes
    # the schema/role name injection-safe. Route for a full guild context, or
    # for an ACTIVE PAM grant (read or write); a grant with neither flag
    # routes nowhere, so the grantee sees nothing. Lazy import avoids a
    # circular import — schema_provisioning imports this module.
    from app.db.schema_provisioning import (
        guild_readonly_role_name,
        guild_role_name,
        guild_schema_name,
        guild_support_role_name,
        platform_role_name,
    )

    pam_active = pam_read or pam_write
    route_guild = (
        guild_id if guild_id is not None else (pam_guild_id if pam_active else None)
    )
    if route_guild is None:
        # Public/platform path: assume the caller's platform-tier role when
        # one is supplied so the request is role-scoped (fail-closed);
        # 'none' (the login role) only for unauthenticated/unrouted contexts.
        sp = "public"
        role_target = (
            platform_role_name(platform_role) if platform_role is not None else "none"
        )
    else:
        sp = f"{guild_schema_name(route_guild)}, public"
        # Pick the guild role by how access was granted:
        # - read grant, or a read_only-status member (guild_id set + read_only):
        #   the SELECT-only guild_<id>_ro role — writes denied at the role level.
        # - scoped read_write grant (no membership, pam_write): the restricted
        #   guild_<id>_support role — content DML but no writes to the structural
        #   / permission tables (the ``support`` identity).
        # - otherwise (real membership, break-glass): the full guild_<id> role.
        read_only_grant = guild_id is None and pam_read and not pam_write
        support_grant = guild_id is None and pam_write
        if read_only_grant or read_only:
            name_fn = guild_readonly_role_name
        elif support_grant:
            name_fn = guild_support_role_name
        else:
            name_fn = guild_role_name
        role_target = name_fn(route_guild)

    satisfied = params.get("satisfied_providers")
    if satisfied == SYSTEM_SATISFIED:
        satp = SYSTEM_SATISFIED
    elif satisfied:
        satp = ",".join(str(int(pid)) for pid in satisfied)
    else:
        satp = ""

    return {
        "uid": str(int(user_id)) if user_id is not None else "",
        "gid": str(int(guild_id)) if guild_id is not None else "",
        "grole": guild_role if guild_role is not None else "",
        "pgid": str(int(pam_guild_id)) if pam_guild_id is not None else "",
        "pr": "true" if pam_read else "false",
        "pw": "true" if pam_write else "false",
        "satp": satp,
        "bgid": "",
        "sp": sp,
        "role": role_target,
    }


def _replay_rls_context(session: SyncSession, transaction, connection) -> None:
    """after_begin hook: re-apply the session's stored context at the start of
    every transaction, so no query ever runs without it — regardless of
    commits or which pooled connection the transaction landed on."""
    if transaction.nested:
        # SET LOCAL scopes to the top-level transaction; savepoints inherit.
        return
    params = session.info.get(_RLS_PARAMS_INFO_KEY)
    if params is None:
        return
    if params.get("user_id") is not None:
        established = session.info.get(_RLS_ESTABLISHED_INFO_KEY)
        if (
            established is None
            or time.monotonic() - established > RLS_CONTEXT_MAX_AGE_SECONDS
        ):
            raise StaleAuthorizationContext(
                "Authorization snapshot exceeded "
                f"{RLS_CONTEXT_MAX_AGE_SECONDS}s; re-validate via "
                "establish_guild_access before further queries."
            )
    bind = _render_context_bind_params(params)
    connection.execute(text(_ROLE_RESET_SQL))
    connection.execute(text(_CONTEXT_SQL), bind)


# propagate=True so the hook also fires for SQLModel's Session subclass (the
# sync session under AsyncSession). Sessions without stored params are a
# no-op, so the global listener is effectively scoped to routed sessions.
event.listen(SyncSession, "after_begin", _replay_rls_context, propagate=True)


async def set_rls_context(
    session: AsyncSession,
    user_id: Optional[int] = None,
    guild_id: Optional[int] = None,
    guild_role: Optional[str] = None,
    pam_guild_id: Optional[int] = None,
    pam_read: bool = False,
    pam_write: bool = False,
    platform_role: Optional[str] = None,
    read_only: bool = False,
    satisfied_providers: Optional[Sequence[int] | str] = None,
) -> None:
    """Set PostgreSQL context for RLS policy evaluation — transaction-local.

    Uses set_config() with is_local=true (SET LOCAL semantics): the context
    dies at COMMIT/ROLLBACK, and the _replay_rls_context after_begin hook
    re-applies it on every new transaction from the params stored here. No
    session-level state ever exists on the connection, so pooled-connection
    staleness is unrepresentable and transaction-mode poolers are safe.

    All variables are always written (defaulting to empty/false)
    so that stale values from a previous request on the same pooled
    connection can never leak into the current request.

    ``pam_read`` / ``pam_write`` flag a time-bound Privileged Access
    Management grant for the guild named by ``pam_guild_id``: additive RLS
    policies grant SELECT (read) / write into that one guild's rows while
    the flag is set. ``pam_guild_id`` is deliberately separate from
    ``current_guild_id`` — the existing write policies treat a matching
    ``current_guild_id`` as proof of membership, so a grantee must leave it
    unset and be scoped via ``pam_guild_id`` instead. A grantee gets scoped,
    time-bound access to one guild; there is no all-guild bypass.

    ``read_only`` routes a REAL MEMBER into the SELECT-only ``guild_<id>_ro``
    role while keeping the full membership GUCs — used when the guild is in
    ``read_only`` lifecycle status, so content writes die at the Postgres role
    level while reads (and the member/admin RLS legs) behave normally. It is
    independent of the PAM read-grant routing, which derives the same role
    from ``pam_read``/``pam_write``.

    ``platform_role`` is the caller's platform tier (``users.role``). When the
    request carries no guild context (and no active PAM grant), the public/platform
    path assumes ``platform_<tier>`` instead of the bare login role, so the request
    is role-scoped at the database (fail-closed) rather than running with the login
    role's broad standing grants. It is ignored when the request routes into a guild
    schema (the guild role governs there).
    """
    _VALID_ROLES = {"admin", "member"}
    if guild_role is not None and guild_role not in _VALID_ROLES:
        raise ValueError(f"Invalid guild_role: {guild_role!r}")
    # ``satisfied_providers`` feeds public.guild_auth_satisfied(): the ids the
    # session's token proved (its ``sat`` claim), or the SYSTEM_SATISFIED
    # sentinel for user-attributed system work whose enqueueing request
    # already passed the guild-access gate. Anything else must be ints.
    if isinstance(satisfied_providers, str) and satisfied_providers != SYSTEM_SATISFIED:
        raise ValueError(f"Invalid satisfied_providers: {satisfied_providers!r}")
    # Validate the tier before it reaches the SET ROLE name sink. The value comes
    # from the ``users.role`` enum, but treat the privileged role-name injection
    # point as untrusted: reject anything not on the known ladder.
    from app.db.schema_provisioning import PLATFORM_TIERS

    if platform_role is not None and platform_role not in PLATFORM_TIERS:
        raise ValueError(f"Invalid platform_role: {platform_role!r}")

    # Store params + freshness stamp BEFORE any execute: an execute may
    # autobegin a transaction, firing the replay hook, which must see the
    # new params. The stamp only refreshes here — i.e. on a call that
    # carries freshly validated inputs — never on replay.
    session.info[_RLS_PARAMS_INFO_KEY] = {
        "user_id": user_id,
        "guild_id": guild_id,
        "guild_role": guild_role,
        "pam_guild_id": pam_guild_id,
        "pam_read": pam_read,
        "pam_write": pam_write,
        "platform_role": platform_role,
        "read_only": read_only,
        "satisfied_providers": satisfied_providers,
    }
    session.info[_RLS_ESTABLISHED_INFO_KEY] = time.monotonic()

    # Only apply eagerly when a transaction is already open (the
    # mid-transaction re-route path, e.g. cross_guild loops) — there the
    # hook has already fired and the new context must land NOW. On a fresh
    # session, the caller's first statement autobegins and the hook applies
    # the stored params; applying here too would just do it twice.
    if session.in_transaction():
        await _apply_stored_context(session)


async def set_billing_context(session: AsyncSession, *, guild_id: int) -> None:
    """Route a verified billing-service request — transaction-local.

    Assumes the ``initiative_billing`` role and sets ``app.billing_guild_id``
    to the guild named in the verified request (see
    ``app.services.platform.billing``), which the role's RLS policies key on.
    Carries no user identity, so the ``RLS_CONTEXT_MAX_AGE_SECONDS`` freshness
    bound does not apply. Same storage/replay mechanics as
    :func:`set_rls_context`.
    """
    session.info[_RLS_PARAMS_INFO_KEY] = {"billing_guild_id": int(guild_id)}
    session.info[_RLS_ESTABLISHED_INFO_KEY] = time.monotonic()
    if session.in_transaction():
        await _apply_stored_context(session)


async def _apply_stored_context(session: AsyncSession) -> None:
    """Apply the session's stored context to the CURRENT transaction.

    Uses set_config() (a regular SQL function) instead of SET commands —
    set_config() is a standard SQL query guaranteed to run on the same
    connection as other session queries. Resets to the login role first, NOT
    because switching requires it (SET ROLE checks the SESSION user's
    memberships, so guild A -> guild B directly is legal) but as a defensive
    baseline: if the set below fails mid-way, the transaction is left as the
    login role, never wearing a stale guild role.
    """
    bind = _render_context_bind_params(session.info[_RLS_PARAMS_INFO_KEY])
    await session.exec(text(_ROLE_RESET_SQL))
    await session.exec(text(_CONTEXT_SQL), params=bind)


@asynccontextmanager
async def rls_session(
    user_id: int,
    guild_id: int,
    guild_role: Optional[str] = None,
) -> AsyncGenerator[AsyncSession, None]:
    """Context manager that provides a session with RLS context set.

    Example:
        async with rls_session(user_id=1, guild_id=2) as session:
            # All queries in this session will be filtered by RLS
            projects = await session.exec(select(Project))
    """
    async with AsyncSessionLocal() as session:
        async with session.begin():
            await set_rls_context(
                session,
                user_id=user_id,
                guild_id=guild_id,
                guild_role=guild_role,
            )
            yield session


BACKEND_DIR = Path(__file__).resolve().parents[2]
ALEMBIC_INI_PATH = BACKEND_DIR / "alembic.ini"
ALEMBIC_SCRIPT_LOCATION = BACKEND_DIR / "alembic"


def _get_alembic_config() -> Config:
    config = Config(str(ALEMBIC_INI_PATH))
    config.set_main_option("script_location", str(ALEMBIC_SCRIPT_LOCATION))
    # Use superuser URL for migrations (needs CREATE ROLE and DDL privileges)
    config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)
    config.attributes["configure_logger"] = False
    config.attributes["url_configured"] = True
    return config


async def run_migrations() -> None:
    config = _get_alembic_config()
    await asyncio.to_thread(command.upgrade, config, "head")
