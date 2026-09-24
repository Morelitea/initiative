import asyncio
import json
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncGenerator, Optional, Sequence

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from asyncpg.exceptions import InvalidCatalogNameError
from sqlalchemy import event, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session as SyncSession
from sqlalchemy.pool import NullPool
from sqlmodel.ext.asyncio.session import AsyncSession
from starlette.requests import HTTPConnection

from app.core import audit_context, metrics
from app.core.config import settings
from app.db import base  # noqa: F401  # ensure models are imported for Alembic
from app.db import cohorts
from app.db.guild_standing import (
    GuildContext,
    InstallContext,
    compute_guild_standing,
    compute_install_standing,
    empty_standing,
    standing_bind_params,
)

logger = logging.getLogger(__name__)

# Primary engine: non-superuser (DATABASE_URL_APP) for RLS-enforced queries.
# With DB_COHORTS above 1 this is the platform pool: requests that address no
# community. Each cohort's requests draw from a pool of their own
# (``app.db.cohorts``).
engine = create_async_engine(
    settings.DATABASE_URL_APP,
    echo=False,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_recycle=settings.DB_POOL_RECYCLE_SECONDS,
)

# System engine: background jobs, startup seeding, platform lifecycle.
# The textbook Postgres trusted-batch actor: BYPASSRLS, bounded by
# enumerated per-table GRANTs (migration 0129). Guild schemas still
# require SET ROLE guild_<id>, which drops the bypass.
system_engine = create_async_engine(
    settings.DATABASE_URL_ADMIN,
    echo=False,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_recycle=settings.DB_POOL_RECYCLE_SECONDS,
)
_SYSTEM_LOGIN_ROLE, _ = settings.database_login("DATABASE_URL_ADMIN")

# Provisioning engine: superuser credentials (same as migrations) for privileged
# DDL — CREATE SCHEMA / CREATE ROLE — which app_user and app_admin can't do.
provisioning_engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    pool_recycle=settings.DB_POOL_RECYCLE_SECONDS,
)

#: Connections kept for reader-written SQL. Small on purpose: it is the bound
#: on how much of the database's attention those statements can hold.
QUERY_POOL_SIZE = 4
#: How long a query waits for one of them before giving up.
QUERY_POOL_TIMEOUT_SECONDS = 5

#: A pool of its own for reader-written SQL, so what those statements wait for
#: is each other rather than the requests serving every other page. Same login
#: as the request path — the difference is the role each statement assumes and
#: the transaction it runs in, not who connects.
query_engine = create_async_engine(
    settings.DATABASE_URL_APP,
    echo=False,
    pool_size=QUERY_POOL_SIZE,
    max_overflow=0,
    pool_timeout=QUERY_POOL_TIMEOUT_SECONDS,
    pool_recycle=settings.DB_POOL_RECYCLE_SECONDS,
)

#: A statement that takes longer than this is logged with the request it served,
#: and counted. Half a second is also a common ``log_min_duration_statement``,
#: so this log and the database's own agree on what "slow" is.
SLOW_STATEMENT_SECONDS = 0.5

#: How much of a slow statement's text its log line keeps.
_SLOW_STATEMENT_TEXT_LIMIT = 2000

#: Where a statement's start time rides between the two cursor events.
_STARTED_AT = "_initiative_started_at"


def instrument_engine(
    target: AsyncEngine, label: str, *, flag_slow: bool = True, log_text: bool = True
) -> None:
    """Time every statement ``target`` runs, and report its pool.

    ``flag_slow`` logs and counts statements over :data:`SLOW_STATEMENT_SECONDS`;
    ``log_text`` puts the statement's text on that line. The text is the SQL
    as written, never the values bound into it.
    """
    metrics.watch_pool(label, target)
    duration = metrics.db_statement_duration.labels(engine=label)
    slow = metrics.db_slow_statements.labels(engine=label)

    def started(_conn, _cursor, _statement, _parameters, context, _executemany):
        setattr(context, _STARTED_AT, time.perf_counter())

    def finished(_conn, _cursor, statement, _parameters, context, _executemany):
        began = getattr(context, _STARTED_AT, None)
        if began is None:
            return
        elapsed = time.perf_counter() - began
        duration.observe(elapsed)
        if not flag_slow or elapsed < SLOW_STATEMENT_SECONDS:
            return
        slow.inc()
        request = audit_context.current()
        written = ""
        if log_text:
            written = ": " + " ".join(statement.split())[:_SLOW_STATEMENT_TEXT_LIMIT]
        logger.warning(
            "Slow statement on the %s engine, %.0f ms (request %s)%s",
            label,
            elapsed * 1000,
            request.request_id if request is not None else "none",
            written,
        )

    event.listen(target.sync_engine, "before_cursor_execute", started)
    event.listen(target.sync_engine, "after_cursor_execute", finished)


instrument_engine(engine, "request")
instrument_engine(system_engine, "system")
# Schema provisioning is DDL, which is expected to take its time.
instrument_engine(provisioning_engine, "provisioning", flag_slow=False)
# What a reader writes is theirs, so its text stays out of the log.
instrument_engine(query_engine, "query", log_text=False)
if settings.DB_COHORTS > 1:
    cohorts.tag_engine(engine, cohorts.PLATFORM)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    autoflush=False,
    expire_on_commit=False,
    class_=AsyncSession,
)

SystemSessionLocal = async_sessionmaker(
    bind=system_engine,
    autoflush=False,
    expire_on_commit=False,
    class_=AsyncSession,
)


async def get_session(
    connection: HTTPConnection,
) -> AsyncGenerator[AsyncSession, None]:
    # No checkout reset: context is transaction-local (set_config is_local +
    # SET LOCAL semantics), so a pooled connection carries NO role/GUC/
    # search_path state between transactions — there is nothing to clear.
    # The pool's rollback-on-return is the only baseline needed.
    #
    # The pool is chosen here, before the first statement, from the community
    # the path addresses: by the time the seam routes the session, the
    # credential and membership lookups have already begun a transaction on it.
    guild_id = cohorts.addressed_guild_id(connection.path_params)
    async with cohorts.request_sessionmaker(guild_id)() as session:
        cohorts.mark_request_session(session)
        yield session


async def get_system_session() -> AsyncGenerator[AsyncSession, None]:
    """Get a session on the system engine (background jobs, bootstrapping,
    platform lifecycle). ``app_admin`` is the standard Postgres trusted-batch
    actor — BYPASSRLS, bounded by enumerated per-table GRANTs (0129); guild
    schemas require ``SET ROLE guild_<id>`` (dropping the bypass) via
    set_rls_context(). Context is transaction-local, so a recycled pooled
    connection starts every session at the login-role/public baseline with
    no reset round-trip."""
    async with SystemSessionLocal() as session:
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

# The platform tier this REQUEST authenticated as, held in the SQLAlchemy
# session's Python state — never on the connection. It is read only by
# set_rls_context, which resolves it into the stored params below; from there it
# reaches Postgres the same way every other value does, as a transaction-local
# set_config replayed per transaction. Nothing here survives a request, and
# nothing here is session state at the database.
_RLS_TIER_INFO_KEY = "rls_platform_tier"


class StaleAuthorizationContext(RuntimeError):
    """A transaction tried to begin on an authorization snapshot older than
    RLS_CONTEXT_MAX_AGE_SECONDS. Re-validate via establish_guild_access (or
    re-call set_rls_context with freshly validated inputs) instead of holding
    a routed session past the bound."""


def _search_path(*schemas: str) -> str:
    """The schemas a request resolves unqualified names against, in priority order.

    ``pg_temp`` is named explicitly, and last. Postgres searches it FIRST for
    relation names when it is left off the path, and the shared functions in
    ``public`` (``initiative_access``, ``capture_change``) resolve guild tables
    through whatever path their caller carries — that is what lets one
    definition serve every guild schema. Naming every schema here keeps their
    resolution a property of the route rather than of the connection.
    """
    return ", ".join((*schemas, "pg_temp"))


#: Clears the role and path a pooled connection may still carry. For entry
#: points that build their own session (websockets, background re-auth) instead
#: of going through ``get_session``, which resets per request.
CONNECTION_RESET_SQL = (
    "SELECT set_config('role', 'none', false), "
    f"set_config('search_path', '{_search_path('public')}', false)"
)

#: The GUC naming the initiatives this request holds "Full access" in. One of
#: the standing keys: written empty by the routing statement below and filled
#: by the standing statement (``app.db.guild_standing``).
OVERRIDE_INITIATIVES_GUC = "app.override_initiatives"

#: The whole of a routing, in one statement. It returns to the login role
#: first and assumes the routed role last, so a statement that fails part-way
#: leaves the transaction aborted on the login role, never wearing a stale
#: guild role.
_CONTEXT_SQL = (
    "SELECT set_config('role', 'none', true), "
    "set_config('app.current_user_id', :uid, true), "
    "set_config('app.current_guild_id', :gid, true), "
    "set_config('app.pam_guild_id', :pgid, true), "
    "set_config('app.settings_guild_id', :setgid, true), "
    "set_config('app.pam_read', :pr, true), "
    "set_config('app.pam_write', :pw, true), "
    "set_config('app.satisfied_providers', :satp, true), "
    "set_config('app.satisfied_claims', :satc, true), "
    "set_config('app.session_amr', :amr, true), "
    "set_config('app.platform_role', :prole, true), "
    "set_config('app.platform_factor', :pfac, true), "
    "set_config('app.billing_guild_id', :bgid, true), "
    "set_config('app.scope_initiative_id', :sinit, true), "
    "set_config('app.via_dashboard_id', :vdash, true), "
    "set_config('app.query', :q, true), "
    "set_config('app.guild_auth_ok', :gok, true), "
    # The installed app this routes, when it is one: which install, the client
    # its token was issued to, and the scopes the token carries. Written from
    # the verified install, the way the user is written from the credential.
    "set_config('app.current_install_id', :iid, true), "
    "set_config('app.token_client_id', :tcid, true), "
    "set_config('app.token_scopes', :tsc, true), "
    # The reader's standing in the community this routes into — written here
    # so a routing always states it, and stated as nothing until the statement
    # that computes it has run. See app.db.guild_standing.
    "set_config('app.standing_guild_id', :sgid, true), "
    "set_config('app.guild_admin', :gadm, true), "
    "set_config('app.guild_seat', :gseat, true), "
    "set_config('app.settings_rung', :srung, true), "
    "set_config('app.member_initiatives', :minit, true), "
    "set_config('app.manager_initiatives', :mginit, true), "
    "set_config('app.member_role_ids', :mrole, true), "
    "set_config('app.role_grants', :rgr, true), "
    "set_config('app.role_denies', :rdn, true), "
    "set_config('app.enabled_tools', :etool, true), "
    f"set_config('{OVERRIDE_INITIATIVES_GUC}', :ovr, true), "
    "set_config('app.install_read', :iread, true), "
    "set_config('app.install_write', :iwrite, true), "
    "set_config('search_path', :sp, true), "
    "set_config('role', :role, true)"
)


#: The standing keys, as the statement above names them. One mapping rather
#: than the pair of spellings repeated at each of the three return points.
_STANDING_BINDS: dict[str, str] = {
    "standing_guild_id": "sgid",
    "guild_admin": "gadm",
    "guild_seat": "gseat",
    "settings_rung": "srung",
    "member_initiatives": "minit",
    "manager_initiatives": "mginit",
    "member_role_ids": "mrole",
    "role_grants": "rgr",
    "role_denies": "rdn",
    "enabled_tools": "etool",
    "override_initiatives": "ovr",
    "install_read": "iread",
    "install_write": "iwrite",
}


def _standing_binds(standing: dict[str, str]) -> dict[str, str]:
    return {bind: standing[key] for key, bind in _STANDING_BINDS.items()}


def _render_context_bind_params(params: dict[str, Any]) -> dict[str, str]:
    """Compute the bind params for _CONTEXT_SQL from stored rls params.

    Pure function shared by the async apply path (set_rls_context) and the
    sync after_begin replay hook — one routing decision, two executors.
    """
    if params.get("install_id") is not None:
        return _render_install_bind_params(params)

    user_id = params.get("user_id")
    guild_id = params.get("guild_id", params.get("system_guild_id"))
    pam_guild_id = params.get("pam_guild_id")
    pam_read = bool(params.get("pam_read"))
    pam_write = bool(params.get("pam_write"))
    settings_guild_id = params.get("settings_guild_id")
    seat = bool(params.get("seat"))
    platform_role = params.get("platform_role")
    read_only = bool(params.get("read_only"))
    query = bool(params.get("query"))
    billing_guild_id = params.get("billing_guild_id")
    system_guild_id = params.get("system_guild_id")
    scope_initiative_id = params.get("scope_initiative_id")
    via_dashboard_id = params.get("via_dashboard_id")
    # The standing, as the seam's statement computed it — or nothing, which is
    # what a routing writes until that statement has run.
    context = params.get("context")
    standing = standing_bind_params(context)
    if context is not None and context.standing_guild_id is not None:
        # Recomputed from the grant rows by the same statement, so the grant
        # flags a replay writes are the database's answer rather than what the
        # lookup read.
        pam_read = context.pam_read
        pam_write = context.pam_write

    # Billing-service path (set_billing_context): assumes the
    # initiative_billing role with only the billing GUC set — no
    # user/guild/PAM context.
    if billing_guild_id is not None:
        from app.db.schema_provisioning import billing_role_name

        return {
            "uid": "",
            "gid": "",
            "pgid": "",
            "setgid": "",
            "pr": "false",
            "pw": "false",
            "satp": "",
            "satc": "",
            # No session at all on this path, so it recorded nothing about
            # how anybody signed in.
            "amr": "",
            # No account either, so no rung and no standing under the
            # deployment's own rule.
            "prole": "",
            "pfac": "false",
            "bgid": str(int(billing_guild_id)),
            "iid": "",
            "tcid": "",
            "tsc": "",
            "sinit": "",
            "vdash": "",
            "q": "false",
            # No person and no community, so no standing either: the role is
            # the whole of what this path may read.
            "gok": "false",
            **_standing_binds(empty_standing()),
            "sp": _search_path("public"),
            "role": billing_role_name(),
        }

    # Route guild-scoped tables to the active guild's schema AND assume that
    # guild's role. The login role has no standing access to any guild schema
    # (fail-closed) — it must SET ROLE into the per-guild role. int() makes
    # the schema/role name injection-safe. Route for a full guild context, or
    # for an ACTIVE PAM grant (read or write), or for a settings-only grant.
    # Lazy import avoids a circular import — schema_provisioning imports this
    # module.
    from app.db.schema_provisioning import (
        guild_query_role_name,
        guild_readonly_role_name,
        guild_role_name,
        guild_schema_name,
        guild_superadmin_role_name,
        guild_support_role_name,
        platform_role_name,
    )

    pam_active = pam_read or pam_write
    route_guild = guild_id
    if route_guild is None and pam_active:
        route_guild = pam_guild_id
    if route_guild is None:
        route_guild = settings_guild_id
    if system_guild_id is not None:
        # Trusted system maintenance keeps the login role (app_admin, whose
        # narrowly enumerated guild-table grants are provisioned separately)
        # so PostgreSQL keeps its BYPASSRLS attribute. Only the schema route
        # changes. An app_user session remains app_user and therefore has no
        # direct privilege on these tables.
        sp = _search_path(guild_schema_name(system_guild_id), "public")
        role_target = "none"
    elif route_guild is None:
        # Public/platform path: assume the caller's platform-tier role when
        # one is supplied so the request is role-scoped (fail-closed);
        # 'none' (the login role) only for unauthenticated/unrouted contexts.
        sp = _search_path("public")
        role_target = (
            platform_role_name(platform_role) if platform_role is not None else "none"
        )
    else:
        sp = _search_path(guild_schema_name(route_guild), "public")
        # Pick the guild role by how access was granted:
        # - a seat request (``seat``): guild_<id>_superadmin, which reads the
        #   community and writes its sign-in configuration. Asked for by the
        #   route, not by holding the seat.
        # - read grant, or a read_only-status member (guild_id set + read_only):
        #   the SELECT-only guild_<id>_ro role — writes denied at the role level.
        # - scoped read_write grant (no membership, pam_write): the restricted
        #   guild_<id>_support role — content DML but no writes to the structural
        #   / permission tables (the ``support`` identity).
        # - settings-only grant: the SELECT-only role. A settings rung reads;
        #   writing what it reaches takes a read_write content grant beside it,
        #   which is the case above.
        # - otherwise (real membership): the full guild_<id> role.
        read_only_grant = guild_id is None and pam_read and not pam_write
        support_grant = guild_id is None and pam_write
        settings_only = (
            guild_id is None and not pam_active and settings_guild_id is not None
        )
        if seat:
            name_fn = guild_superadmin_role_name
        elif query:
            # A query runs as the query role whatever else the request is:
            # a member's, a read-only member's, or a grantee's.
            name_fn = guild_query_role_name
        elif read_only_grant or read_only or settings_only:
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

    # What each satisfied provider asserted for the claims some community
    # narrows it by, as the JSON object the gate reads with ``->``. Empty
    # string when the credential records none, which the gate treats as
    # nothing asserted.
    claims = params.get("satisfied_claims") or {}
    satc = json.dumps(claims, separators=(",", ":"), sort_keys=True) if claims else ""

    # Which of the markers a community can ask about the credential recorded,
    # comma-joined the way the satisfied-provider set above is. The vocabulary
    # is closed (``POLICY_AMR_MARKERS``), so the delimiter cannot appear inside
    # a value; sorted so one session always writes one string. Empty when the
    # credential recorded none, which every leg reads as unanswered.
    amr = ",".join(sorted(params.get("session_amr") or ()))
    # And whether the account answers the deployment's own second-factor rule:
    # a factor it holds, or one this session presented. Read beside the rung
    # the rule is scoped by, which every routed request already carries.
    pfac = "true" if params.get("platform_factor") else "false"

    # The community's sign-in gate, which the standing statement answers from
    # the database for a person. A context with no person behind it is not a
    # session to gate — the same first leg public.guild_auth_satisfied() reads
    # — and neither is user-attributed system work whose enqueueing request
    # already passed it.
    system_session = user_id is None or satp == SYSTEM_SATISFIED
    guild_auth_ok = system_session or (context is not None and context.guild_auth_ok)

    return {
        "uid": str(int(user_id)) if user_id is not None else "",
        "gid": str(int(guild_id)) if guild_id is not None else "",
        "pgid": str(int(pam_guild_id)) if pam_guild_id is not None else "",
        "setgid": str(int(settings_guild_id)) if settings_guild_id is not None else "",
        "amr": amr,
        "prole": platform_role or "",
        "pfac": pfac,
        "pr": "true" if pam_read else "false",
        "pw": "true" if pam_write else "false",
        "satp": satp,
        "satc": satc,
        "bgid": "",
        "iid": "",
        "tcid": "",
        "tsc": "",
        "gok": "true" if guild_auth_ok else "false",
        **_standing_binds(standing),
        "sinit": str(int(scope_initiative_id))
        if scope_initiative_id is not None
        else "",
        "vdash": str(int(via_dashboard_id)) if via_dashboard_id is not None else "",
        # Reader-written SQL, as the policies see it. The role already says
        # so; this says it where a policy can read it, which is what lets a
        # rule apply to the query surface and nowhere else.
        "q": "true" if query else "false",
        "sp": sp,
        "role": role_target,
    }


def _render_install_bind_params(params: dict[str, Any]) -> dict[str, str]:
    """The routing binds for an installed app acting in its community.

    Assumes ``guild_<id>_app`` with the community's schema on the path. No
    person: the user, every credential value and the grant flags are written
    empty. The install, its client and its token's scopes are the routing's own
    values, and the standing is what the install standing statement computed —
    or nothing, until it has run.
    """
    from app.db.schema_provisioning import guild_app_role_name, guild_schema_name

    guild_id = int(params["guild_id"])
    context = params.get("context")
    completed = (
        isinstance(context, InstallContext) and context.standing_guild_id is not None
    )
    scope_initiative_id = params.get("scope_initiative_id")
    return {
        "uid": "",
        "gid": str(guild_id),
        "pgid": "",
        "setgid": "",
        "pr": "false",
        "pw": "false",
        "satp": "",
        "satc": "",
        "amr": "",
        "prole": "",
        "pfac": "false",
        "bgid": "",
        "iid": str(int(params["install_id"])),
        "tcid": str(params.get("token_client_id") or ""),
        # The vocabulary is closed (``app.core.app_scopes``), so the delimiter
        # cannot appear inside a scope; sorted so one token writes one string.
        "tsc": ",".join(sorted(params.get("token_scopes") or ())),
        "sinit": str(int(scope_initiative_id))
        if scope_initiative_id is not None
        else "",
        "vdash": "",
        "q": "false",
        "gok": "true" if completed and context.guild_auth_ok else "false",
        **_standing_binds(standing_bind_params(context if completed else None)),
        "sp": _search_path(guild_schema_name(guild_id), "public"),
        "role": guild_app_role_name(guild_id),
    }


def _replay_rls_context(session: SyncSession, transaction, connection) -> None:
    """after_begin hook: re-apply the session's stored context at the start of
    every transaction, so no query ever runs without it — regardless of
    commits or which pooled connection the transaction landed on."""
    if transaction.nested:
        # SET LOCAL scopes to the top-level transaction; savepoints inherit.
        return
    if session.info.get(cohorts.READ_ONLY_INFO_KEY):
        connection.exec_driver_sql("SET TRANSACTION READ ONLY")
    params = session.info.get(_RLS_PARAMS_INFO_KEY)
    if params is None:
        return
    if params.get("user_id") is not None or params.get("install_id") is not None:
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
    cohorts.note_route(connection, cohorts.routed_guild_id(params))
    bind = _render_context_bind_params(params)
    connection.execute(text(_CONTEXT_SQL), bind)


# propagate=True so the hook also fires for SQLModel's Session subclass (the
# sync session under AsyncSession). Sessions without stored params are a
# no-op, so the global listener is effectively scoped to routed sessions.
event.listen(SyncSession, "after_begin", _replay_rls_context, propagate=True)


async def set_rls_context(
    session: AsyncSession,
    user_id: Optional[int] = None,
    guild_id: Optional[int] = None,
    context: GuildContext | InstallContext | None = None,
    pam_guild_id: Optional[int] = None,
    pam_read: bool = False,
    pam_write: bool = False,
    platform_role: Optional[str] = None,
    read_only: bool = False,
    query: bool = False,
    satisfied_providers: Optional[Sequence[int] | str] = None,
    satisfied_claims: Optional[dict] = None,
    session_amr: frozenset[str] | None = None,
    platform_factor: Optional[bool] = None,
    scope_initiative_id: Optional[int] = None,
    via_dashboard_id: Optional[int] = None,
    settings_guild_id: Optional[int] = None,
    seat: bool = False,
    install_id: Optional[int] = None,
    token_client_id: Optional[str] = None,
    token_scopes: frozenset[str] | None = None,
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

    ``context`` is a person's standing in the community this routes into, as
    the establishment seam computed it (``app.db.guild_standing``). It carries
    the values the initiative gates read — membership, initiative roles, the
    admin fact, the tool switches — and is written with the routing so the two
    always name the same community. A routing with no context writes the
    standing empty, which answers no on every one of those legs. Routing a
    person into a community without one is refused: the seam is where that
    decision is made, and ``establish_guild_access`` is the way to it.

    ``pam_read`` / ``pam_write`` flag a time-bound Privileged Access
    Management grant for the guild named by ``pam_guild_id``: additive RLS
    policies grant SELECT (read) / write into that one guild's rows while
    the flag is set. ``pam_guild_id`` is deliberately separate from
    ``current_guild_id``: a grant records the guild it reaches in its own
    field, and a membership records its own. A grantee gets scoped,
    time-bound access to one guild; there is no all-guild bypass.

    ``seat`` routes into ``guild_<id>_superadmin``, the role that carries the
    community's own sign-in configuration. It is what the route asked for, not
    what the caller holds: an ordinary request by a seat holder routes as
    ``guild_<id>``, so a content read never carries those grants.

    ``read_only`` routes a REAL MEMBER into the SELECT-only ``guild_<id>_ro``
    role while keeping the full membership GUCs — used when the guild is in
    ``read_only`` lifecycle status, so content writes die at the Postgres role
    level while reads (and the member/admin RLS legs) behave normally. It is
    independent of the PAM read-grant routing, which derives the same role
    from ``pam_read``/``pam_write``.

    ``via_dashboard_id`` names the dashboard this request is drawing. A grant
    whose grantee is that dashboard answers while it is set and at no other
    time, which is what makes a published view a property of the fetch rather
    than of the reader. It is written by the one path that runs a placed
    widget's stored statement, after that dashboard's own gates have admitted
    the reader — never from anything a request supplies.

    ``scope_initiative_id`` narrows the read to one initiative: rows belonging
    to another are not part of the answer, whatever else the context allows.
    It only ever removes rows — an initiative the caller could not reach
    anyway yields nothing — and it is what lets an initiative-scoped surface
    ask a guild-scoped question and get its own initiative's answer. Unset
    means no narrowing, which is every ordinary request.

    ``install_id`` routes an installed app acting in the community named by
    ``guild_id``: it assumes ``guild_<id>_app`` and writes no person.
    ``token_client_id`` and ``token_scopes`` are the client the install's token
    was issued to and the scopes it carries, and ``scope_initiative_id`` the
    initiative it is narrowed to. ``context`` is then the ``InstallContext``
    the establishment seam built (``app.api.deps.establish_install_access``),
    and a routing that names an install without one is refused.

    ``platform_factor`` says whether the account answers the deployment's own
    second-factor rule — a factor it holds, or one this session presented. It
    rides beside the tier because the rule is scoped by rung, and both are read
    by ``public.platform_factor_satisfied()``, which decides the rule itself
    from the settings row. ``None`` (the default) reads what this request's
    gate resolved; pass a value only where there is no such gate.

    ``platform_role`` is the caller's platform tier (``users.role``). When the
    request carries no guild context (and no active PAM grant), the public/platform
    path assumes ``platform_<tier>`` instead of the bare login role, so the request
    is role-scoped at the database (fail-closed) rather than running with the login
    role's broad standing grants. It is ignored when the request routes into a guild
    schema (the community's own role governs there) — pass it anyway, so the
    tier is on the session for the trip back out.

    The tier is remembered **for the request** — in the SQLAlchemy session's
    Python state, not on the connection — and reapplied to any later call that
    names a ``user_id`` without one, so re-establishing context part-way through
    keeps the role it authenticated as. Passing a tier sets it; passing no
    ``user_id`` clears it. What is remembered is only an input to this function:
    it is resolved here and written into the stored params, so it reaches
    Postgres as the same transaction-local ``set_config`` as everything else and
    is replayed per transaction. Every parameter is still written from this
    call's arguments, so nothing carries between requests on a pooled connection.

    **This routes a session; it does not establish a request.** It writes GUCs
    on the session handed to it and touches no task-scoped state, which is what
    makes it safe to call on a *second* session while a request is being served
    — ``published_views`` loading a row as its author, ``intake`` opening a case
    in the operations guild. Resolving who somebody is in a community, and
    computing what that gives them, is the establishment seam's job
    (``deps.apply_guild_session_context``, via ``establish_guild_access``):
    this call applies the answer it reached.
    """
    # Which of the request shapes these arguments form — and a refusal if they
    # form none of them. This is where the rules that used to be prose in this
    # docstring are actually applied: a grant carrying a guild, a narrowing
    # with nothing to narrow, a person routed into a community without the
    # standing the seam computes. Imported here, beside the tier list below,
    # to keep this module's import graph as it is.
    from app.db.request_context import classify

    classify(
        user_id=user_id,
        guild_id=guild_id,
        context=context,
        pam_guild_id=pam_guild_id,
        pam_read=pam_read,
        pam_write=pam_write,
        settings_guild_id=settings_guild_id,
        platform_role=platform_role,
        read_only=read_only,
        query=query,
        satisfied_providers=satisfied_providers,
        satisfied_claims=satisfied_claims,
        session_amr=session_amr,
        scope_initiative_id=scope_initiative_id,
        via_dashboard_id=via_dashboard_id,
        install_id=install_id,
        token_client_id=token_client_id,
        token_scopes=token_scopes,
    )
    # Whether the account answers the deployment's own second-factor rule.
    # Ambient by default, from the context the request's gate resolved once —
    # the same shape ``establish_guild_access`` reads its satisfied set with,
    # and what lets a service re-route a request's session without carrying
    # the fact through every signature between here and the gate.
    if platform_factor is None:
        from app.core import auth_context

        platform_factor = auth_context.platform_factor()

    # ``satisfied_providers`` feeds public.guild_auth_satisfied(): the ids the
    # session's token proved (its ``sat`` claim), or the SYSTEM_SATISFIED
    # sentinel for user-attributed system work whose enqueueing request
    # already passed the guild-access gate. Anything else must be ints.
    if isinstance(satisfied_providers, str) and satisfied_providers != SYSTEM_SATISFIED:
        raise ValueError(f"Invalid satisfied_providers: {satisfied_providers!r}")
    # Validate the tier before it reaches the SET ROLE name sink. The value comes
    # from the ``users.role`` enum, but treat the privileged role-name injection
    # point as untrusted: reject anything not on the known ladder.
    from app.db.schema_provisioning import PLATFORM_ROUTES

    if platform_role is not None and platform_role not in PLATFORM_ROUTES:
        raise ValueError(f"Invalid platform_role: {platform_role!r}")

    # A call that names a user but not their tier is re-establishing this
    # request's own context — returning from a guild excursion, or narrowing
    # after a lookup — not becoming somebody else. Give it back the tier the
    # request authenticated as, so the role it assumes is that one rather than
    # the login role underneath it. A call that names no user is an
    # unattributed context (workers, seeding, the deliberate reset) and forgets
    # it. Resolved into the stored params below, so the replay hook reapplies
    # it per transaction like every other value.
    if platform_role is not None:
        session.info[_RLS_TIER_INFO_KEY] = platform_role
    elif user_id is None:
        session.info.pop(_RLS_TIER_INFO_KEY, None)
    else:
        platform_role = session.info.get(_RLS_TIER_INFO_KEY)

    # Store params + freshness stamp BEFORE any execute: an execute may
    # autobegin a transaction, firing the replay hook, which must see the
    # new params. The stamp only refreshes here — i.e. on a call that
    # carries freshly validated inputs — never on replay.
    session.info[_RLS_PARAMS_INFO_KEY] = {
        "user_id": user_id,
        "guild_id": guild_id,
        "context": context,
        "pam_guild_id": pam_guild_id,
        "pam_read": pam_read,
        "pam_write": pam_write,
        "settings_guild_id": settings_guild_id,
        "seat": seat,
        "platform_role": platform_role,
        "read_only": read_only,
        "query": query,
        "satisfied_providers": satisfied_providers,
        "satisfied_claims": satisfied_claims,
        "session_amr": session_amr,
        "platform_factor": platform_factor,
        "scope_initiative_id": scope_initiative_id,
        "via_dashboard_id": via_dashboard_id,
        "install_id": install_id,
        "token_client_id": token_client_id,
        "token_scopes": token_scopes,
    }
    session.info[_RLS_ESTABLISHED_INFO_KEY] = time.monotonic()

    # Only apply eagerly when a transaction is already open (the
    # mid-transaction re-route path, e.g. cross_guild loops) — there the
    # hook has already fired and the new context must land NOW. On a fresh
    # session, the caller's first statement autobegins and the hook applies
    # the stored params; applying here too would just do it twice.
    if session.in_transaction():
        await _apply_stored_context(session)


def rls_context_params(session: AsyncSession) -> dict[str, Any]:
    """The context this session established, as ``set_rls_context`` keywords.

    For a caller that needs a second session to see what this one sees — the
    query surface runs on a pool of its own. Handing over the stored parameters
    keeps one decision about who the request is, rather than a second reading
    of the same guild context somewhere else.
    """
    params = session.info.get(_RLS_PARAMS_INFO_KEY)
    if not params:
        raise RuntimeError("no RLS context has been established on this session")
    return dict(params)


async def apply_guild_standing(
    session: AsyncSession, context: GuildContext
) -> GuildContext:
    """Compute this request's standing and record it on the session.

    The second half of the establishment seam: the routing has just written the
    community context and cleared every standing key, so what
    :data:`app.db.guild_standing.STANDING_SQL` writes is the whole of it. Its
    returned row completes ``context``, which is stored with the routing
    parameters so the replay hook re-applies routing and standing together —
    one entry, one community.
    """
    completed = context.with_standing(await compute_guild_standing(session))
    params = session.info.get(_RLS_PARAMS_INFO_KEY)
    if params is not None:
        params["context"] = completed
    return completed


async def apply_install_standing(
    session: AsyncSession, context: InstallContext
) -> InstallContext:
    """Compute an installed app's standing and record it on the session.

    The second half of the install seam, as :func:`apply_guild_standing` is of
    the person seam: the routing has just written the install and cleared every
    standing key, and :data:`app.db.guild_standing.INSTALL_STANDING_SQL`
    writes the whole of it. The completed context is stored with the routing
    parameters, so the replay hook re-applies both together.
    """
    completed = context.with_standing(await compute_install_standing(session))
    params = session.info.get(_RLS_PARAMS_INFO_KEY)
    if params is not None:
        params["context"] = completed
    return completed


def routed_guild_id(session: AsyncSession) -> int | None:
    """The guild this session is currently routed to, or ``None`` if it is not.

    Ids of things that live in a guild schema — documents, initiatives — are
    per-schema sequences, so the same number names a different row in each
    guild. Anything keyed by one of them outside the database needs the guild
    beside it, and where the id was read through a routed session, that routing
    is the answer.

    Membership, a content grant and a settings grant each name the community in
    their own field, and any of the three is the community this session reads.
    """
    params = session.info.get(_RLS_PARAMS_INFO_KEY) or {}
    for key in ("guild_id", "system_guild_id", "pam_guild_id", "settings_guild_id"):
        guild_id = params.get(key)
        if guild_id is not None:
            return int(guild_id)
    return None


def require_routed_guild_id(session: AsyncSession) -> int:
    """The guild this session is routed to, for a payload that has to name one.

    A serializer runs inside the routed session that read its rows, so there is
    one. Raising beats reporting a community nobody routed into.
    """
    guild_id = routed_guild_id(session)
    if guild_id is None:
        raise RuntimeError(
            "no community is routed on this session; set_rls_context must run "
            "before guild content is serialized"
        )
    return guild_id


def guild_context(session: AsyncSession) -> GuildContext | None:
    """The standing this session was routed with, or ``None``.

    The context *is* part of the stored routing parameters, so reading it here
    and reading the routed community are one lookup rather than two that can
    disagree. A context whose community is not the one the session is routed to
    is not returned: a cross-guild gather re-routes between communities, and a
    standing means nothing outside the one it was computed in.
    """
    params = session.info.get(_RLS_PARAMS_INFO_KEY) or {}
    context = params.get("context")
    if not isinstance(context, GuildContext):
        return None
    return context if context.guild_id == routed_guild_id(session) else None


def require_guild_context(session: AsyncSession) -> GuildContext:
    """The standing this session was routed with, for a caller that needs one.

    Raising beats deciding on a standing nobody computed: every leg of one
    answers no when it is missing, which reads as a refusal rather than as the
    missing routing it is.
    """
    context = guild_context(session)
    if context is None:
        raise RuntimeError(
            "no standing is recorded on this session; establish_guild_access "
            "must run before a decision is made from one"
        )
    return context


def install_context(session: AsyncSession) -> InstallContext | None:
    """The installed app's standing this session was routed with, or ``None``.

    The install counterpart of :func:`guild_context`, read from the same stored
    parameters and held to the routed community the same way.
    """
    params = session.info.get(_RLS_PARAMS_INFO_KEY) or {}
    context = params.get("context")
    if not isinstance(context, InstallContext):
        return None
    return context if context.guild_id == routed_guild_id(session) else None


def require_install_context(session: AsyncSession) -> InstallContext:
    """The installed app's standing this session was routed with, for a caller
    that needs one."""
    context = install_context(session)
    if context is None:
        raise RuntimeError(
            "no install standing is recorded on this session; "
            "establish_install_access must run before a decision is made from one"
        )
    return context


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


async def set_system_guild_context(session: AsyncSession, *, guild_id: int) -> None:
    """Route trusted system maintenance without dropping its login identity.

    The ordinary guild route assumes ``guild_<id>`` and therefore drops
    ``app_admin``'s BYPASSRLS attribute. A small set of lifecycle operations
    must process every matching row regardless of tenant policy; provisioning
    grants ``app_admin`` direct access only to the tables those operations use.
    A request-path ``app_user`` session remains unprivileged and fails closed.
    """
    is_system_login = (
        await session.exec(
            text("SELECT session_user = :role"),
            params={"role": _SYSTEM_LOGIN_ROLE},
        )
    ).one()[0]
    if not is_system_login:
        raise PermissionError(
            "system guild routing requires the configured system login"
        )

    session.info.pop(_RLS_TIER_INFO_KEY, None)
    session.info[_RLS_PARAMS_INFO_KEY] = {"system_guild_id": int(guild_id)}
    session.info[_RLS_ESTABLISHED_INFO_KEY] = time.monotonic()
    if session.in_transaction():
        await _apply_stored_context(session)


async def _apply_stored_context(session: AsyncSession) -> None:
    """Apply the session's stored context to the CURRENT transaction.

    Uses set_config() (a regular SQL function) instead of SET commands —
    set_config() is a standard SQL query guaranteed to run on the same
    connection as other session queries. The statement resets to the login
    role first, NOT because switching requires it (SET ROLE checks the SESSION
    user's memberships, so guild A -> guild B directly is legal) but as a
    defensive baseline (see :data:`_CONTEXT_SQL`).
    """
    params = session.info[_RLS_PARAMS_INFO_KEY]
    connection = await session.connection()
    cohorts.note_route(connection.sync_connection, cohorts.routed_guild_id(params))
    bind = _render_context_bind_params(params)
    await session.exec(text(_CONTEXT_SQL), params=bind)


@asynccontextmanager
async def guild_schema_context(
    session: AsyncSession,
    *,
    guild_id: int,
) -> AsyncGenerator[AsyncSession, None]:
    """Borrow an already-open session for one guild's schema, then hand it back.

    A platform/bootstrapping handler runs with ``search_path = public`` and
    cannot see guild content at all, so work that has to touch a guild schema
    from there routes the session in first (the same move
    ``seed_guild_content`` and the ``oidc_sync`` per-guild loop make). What this
    adds is the return trip: several callers keep using the session after the
    excursion, so whatever context they were carrying is put back on the way
    out — including the freshness stamp, which this excursion must not renew.

    A session that carried no context at all (the system engine on its login
    role) is returned to exactly that: the current transaction is neutralized
    and the stored params are dropped, so later transactions start pristine
    rather than replaying a context this helper invented.

    The session must already be inside the caller's transaction; this neither
    commits nor rolls back.
    """
    previous = session.info.get(_RLS_PARAMS_INFO_KEY)
    previous_established = session.info.get(_RLS_ESTABLISHED_INFO_KEY)
    # The excursion routes with no user of its own, which forgets the tier; the
    # caller on the other side of it is still the same request.
    previous_tier = session.info.get(_RLS_TIER_INFO_KEY)
    routed = False
    try:
        await set_rls_context(session, guild_id=guild_id)
        routed = True
        yield session
    finally:
        # Restoring the stored params comes first and cannot fail, so the
        # caller's next transaction replays the caller's own context whatever
        # happened in between.
        session.info[_RLS_PARAMS_INFO_KEY] = previous if previous is not None else {}
        if previous_established is not None:
            session.info[_RLS_ESTABLISHED_INFO_KEY] = previous_established
        if previous_tier is not None:
            session.info[_RLS_TIER_INFO_KEY] = previous_tier
        else:
            session.info.pop(_RLS_TIER_INFO_KEY, None)
        # Routing that did not complete leaves a transaction that accepts no
        # further statements, and its own rollback puts the settings back; more
        # SQL there would only replace the real error with a second one.
        if routed and session.in_transaction():
            await _apply_stored_context(session)
        if previous is None:
            session.info.pop(_RLS_PARAMS_INFO_KEY, None)
            session.info.pop(_RLS_ESTABLISHED_INFO_KEY, None)


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


def _database_name(url: str) -> str:
    return make_url(url).database or "?"


def migration_chain() -> tuple[frozenset[str], str | None]:
    """Every revision this image ships, and the newest of them.

    Read from the files in the image, without touching the database: it is what
    a stamped database is checked against before alembic is asked to upgrade it
    (see ``check_pre_baseline_db``). ``(frozenset(), None)`` if the chain cannot
    be read, so a caller diagnosing a database treats it as unknown rather than
    as empty.
    """
    try:
        chain = ScriptDirectory.from_config(_get_alembic_config())
        revisions = frozenset(step.revision for step in chain.walk_revisions())
        return revisions, chain.get_current_head()
    except Exception:
        return frozenset(), None


def _missing_database_error() -> RuntimeError:
    """What to raise when DATABASE_URL names a database that is not there.

    The database itself is infrastructure's to make, not the app's: the
    compose image creates it from POSTGRES_DB on first boot, and an existing
    install has one already. Say so, rather than let a connection error
    surface as forty frames of driver traceback — from whichever of the two
    startup connections reaches it first.
    """
    name = _database_name(settings.DATABASE_URL)
    return RuntimeError(
        f"Database {name!r} does not exist. The compose image creates it "
        f"from POSTGRES_DB the first time its volume is initialised, and "
        f"only then — on a server that already has a volume, make it by "
        f"hand as the superuser:\n"
        f"  docker exec -e PGPASSWORD=<pw> <container> \\\n"
        f"    psql -U <superuser> -d postgres -c 'CREATE DATABASE {name}'\n"
        f"The app does not create its own database; it takes ownership "
        f"of an existing one at startup."
    )


#: The advisory-lock key a process holds while it migrates. Arbitrary and
#: app-specific: all it has to be is the same number in every build, and a
#: different one from the suite's (``conftest.py``).
MIGRATION_LOCK_KEY = 0x1417A7E50D


@asynccontextmanager
async def migration_lock() -> AsyncGenerator[None, None]:
    """Take the database's migration lock for the duration of the block.

    Alembic runs in-process at startup, so instances sharing a database take
    turns here rather than upgrading it at the same time. The lock rides a
    connection of its own — opened for this, closed after, which is what
    releases it — because the upgrade runs on connections alembic opens for
    itself. AUTOCOMMIT keeps that connection merely idle, rather than idle in
    a transaction, for however long the upgrade ahead of it takes.
    """
    lock_engine = create_async_engine(
        settings.DATABASE_URL, poolclass=NullPool, isolation_level="AUTOCOMMIT"
    )
    params = {"key": MIGRATION_LOCK_KEY}
    try:
        conn = await lock_engine.connect()
    except InvalidCatalogNameError as exc:
        await lock_engine.dispose()
        raise _missing_database_error() from exc
    try:
        taken = await conn.scalar(text("SELECT pg_try_advisory_lock(:key)"), params)
        if not taken:
            logger.info(
                "Another instance is migrating this database; waiting for it to finish."
            )
            waited_from = time.monotonic()
            await conn.execute(text("SELECT pg_advisory_lock(:key)"), params)
            logger.info(
                "Migration lock acquired after %.0fs.", time.monotonic() - waited_from
            )
        yield
    finally:
        # Closing the connection is what gives the lock back.
        await conn.close()
        await lock_engine.dispose()


async def run_migrations() -> None:
    config = _get_alembic_config()
    try:
        await asyncio.to_thread(command.upgrade, config, "head")
    except InvalidCatalogNameError as exc:
        raise _missing_database_error() from exc
