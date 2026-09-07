"""The privileged database bootstrap, in one place.

Two things have to exist in the cluster before the app can run as its own
least-privilege logins, and neither can be created *by* those logins:

* **The three login roles** — the provisioning role that owns the app's objects
  and runs migrations, the RLS-enforced request login, and the system-engine
  login — plus the database grants and ``public`` ownership they need.
* **The guild-search match operator** — a ``LEAKPROOF`` function, an operator
  over it, and a GIN operator class. Postgres accepts ``LEAKPROOF`` only from a
  superuser (``only superuser can define a leakproof function``), so this stays
  a privileged step no matter how the roles are arranged.

Both are declared here and applied from a connection opened with
``DATABASE_URL_BOOTSTRAP``, which is disposed before the app serves anything —
the request path keeps running on the three logins above. Every statement is
idempotent and re-applied on each boot, so rotating a role password, upgrading
into a release that adds a privileged object, and restoring a dump that carried
no role attributes all converge without hand-run SQL.

When ``DATABASE_URL_BOOTSTRAP`` is unset the same invariants are *verified*
instead: a deployment that provisions its database out of band (managed
Postgres, a Kubernetes operator, a DBA) boots normally when they hold, and
stops with the exact SQL when they do not. ``--print-sql`` emits that SQL.

Run standalone with ``python -m app.db.bootstrap``.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass
from urllib.parse import unquote, urlparse

from sqlalchemy import make_url, text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.db.system_grants import GRANTABLE_SHARED_TABLES

logger = logging.getLogger(__name__)

#: Serializes the bootstrap across processes. Role DDL writes shared catalogs,
#: so two starts at once can collide there.
#:
#: An advisory lock's key space is per-database, which is enough for replicas of
#: one deployment (they share a database) but not for two deployments on one
#: cluster. So the lock is taken on the cluster's maintenance database when that
#: is reachable, and on the app's own database otherwise — the latter still
#: covers the replica case, which is the one a deployment creates for itself.
#:
#: Two deployments sharing a cluster should not share login-role names; the
#: names come from the connection URLs precisely so they need not.
_BOOTSTRAP_LOCK_KEY = 0x1417B007

#: Tried in order for the cluster-wide lock. Both are conventionally present;
#: a provider that exposes neither falls back to the per-database lock.
_MAINTENANCE_DATABASES = ("postgres", "template1")

#: The canonical login names, used when a URL does not name one. Each is paired
#: with the setting whose URL supplies its name and password.
_PROVISIONER = ("DATABASE_URL", "app_provisioner")
_APP_USER = ("DATABASE_URL_APP", "app_user")
_SYSTEM_ENGINE = ("DATABASE_URL_ADMIN", "app_admin")

#: Roles the provisioner administers but does not create: the shared floors and
#: the platform ladder come from the baseline migration, and per-guild roles
#: from guild provisioning. Granting them ``WITH ADMIN OPTION`` where they
#: already exist is what lets the provisioner maintain them afterwards.
_ADMINISTERED_ROLE_PATTERN = (
    "rolname IN ('app_guild_base', 'platform_base', 'platform_member', "
    "'platform_support', 'platform_moderator', 'platform_operator', "
    "'platform_owner') OR rolname ~ '^guild_[0-9]+(_ro|_support)?$'"
)


@dataclass(frozen=True)
class LoginRole:
    """One login the bootstrap maintains, as named by its connection URL."""

    name: str
    password: str | None
    attributes: str


@dataclass(frozen=True)
class BootstrapResult:
    applied: bool
    roles: tuple[str, ...]
    search_operator_installed: bool
    notes: tuple[str, ...] = ()


def _url_parts(setting_name: str, default_role: str) -> tuple[str, str | None]:
    """The (role name, password) a connection URL carries.

    Deployments are free to name their logins something other than the
    canonical names; the bootstrap maintains whatever the URLs actually
    connect as, the same way the system-engine check reads ``current_user``.
    """
    url = getattr(settings, setting_name, None)
    if not url:
        return default_role, None
    try:
        parsed = urlparse(url)
    except ValueError:
        return default_role, None
    name = unquote(parsed.username) if parsed.username else default_role
    password = unquote(parsed.password) if parsed.password else None
    return name, password


def login_roles() -> tuple[LoginRole, LoginRole, LoginRole]:
    """The three logins to maintain, read from the connection URLs."""
    provisioner_name, provisioner_pw = _url_parts(*_PROVISIONER)
    app_name, app_pw = _url_parts(*_APP_USER)
    system_name, system_pw = _url_parts(*_SYSTEM_ENGINE)
    return (
        LoginRole(
            provisioner_name,
            provisioner_pw,
            "LOGIN CREATEROLE NOSUPERUSER NOBYPASSRLS",
        ),
        LoginRole(app_name, app_pw, "LOGIN NOINHERIT"),
        LoginRole(system_name, system_pw, "LOGIN BYPASSRLS"),
    )


# --- Role and database statements ------------------------------------------
#
# Role DDL takes no bind parameters, so the name and password travel as
# transaction-local GUCs and are quoted server-side with format(%I) / format(%L)
# — the same shape the baseline migration's role DDL uses.

_ENSURE_ROLE = """
DO $$
DECLARE
    role_name text := current_setting('app._bootstrap_role');
    role_attrs text := current_setting('app._bootstrap_attrs');
    role_pw text := nullif(current_setting('app._bootstrap_pw'), '');
    verb text;
BEGIN
    SELECT CASE WHEN EXISTS (SELECT 1 FROM pg_roles WHERE rolname = role_name)
                THEN 'ALTER' ELSE 'CREATE' END INTO verb;
    IF role_pw IS NULL THEN
        EXECUTE format('%s ROLE %I WITH %s', verb, role_name, role_attrs);
    ELSE
        EXECUTE format('%s ROLE %I WITH %s PASSWORD %L',
                       verb, role_name, role_attrs, role_pw);
    END IF;
EXCEPTION WHEN duplicate_object THEN
    -- Another process created it between the check and the CREATE; ALTER to
    -- the same shape instead.
    IF role_pw IS NULL THEN
        EXECUTE format('ALTER ROLE %I WITH %s', role_name, role_attrs);
    ELSE
        EXECUTE format('ALTER ROLE %I WITH %s PASSWORD %L',
                       role_name, role_attrs, role_pw);
    END IF;
END
$$;
"""

_GRANT_DATABASE = """
DO $$ BEGIN
    EXECUTE format('GRANT CREATE, CONNECT ON DATABASE %I TO %I',
                   current_database(), current_setting('app._bootstrap_role'));
END $$;
"""

# The app creates no temporary objects, so it does not use the TEMPORARY grant
# PUBLIC carries by default on a new database.
_REVOKE_TEMPORARY = """
DO $$ BEGIN
    EXECUTE format('REVOKE TEMPORARY ON DATABASE %I FROM PUBLIC',
                   current_database());
END $$;
"""

# Only a database's owner can change its ACL; a REVOKE from any other role
# reports success and changes nothing, so read the ACL back rather than trust
# the command's exit.
_VERIFY_TEMPORARY_REVOKED = """
DO $$
DECLARE db_owner text;
BEGIN
    IF EXISTS (
        SELECT 1
        FROM pg_database d,
             aclexplode(coalesce(d.datacl, acldefault('d', d.datdba))) a
        WHERE d.datname = current_database()
          AND a.grantee = 0
          AND a.privilege_type = 'TEMPORARY'
    ) THEN
        SELECT pg_get_userbyid(datdba) INTO db_owner
          FROM pg_database WHERE datname = current_database();
        RAISE EXCEPTION
            'REVOKE TEMPORARY did not take effect on database %. The '
            'bootstrap connection must be its owner (%).',
            current_database(), db_owner;
    END IF;
END
$$;
"""

# Postgres 15+ made CREATE on the public schema owner-only, and the baseline
# migration builds the shared schema there as the provisioning role.
_OWN_PUBLIC_SCHEMA = """
DO $$ BEGIN
    EXECUTE format('ALTER SCHEMA public OWNER TO %I',
                   current_setting('app._bootstrap_role'));
END $$;
"""

# Roles the provisioner creates from now on carry implicit ADMIN (PG16+
# CREATEROLE); ones that already exist are granted here.
_ADMINISTER_EXISTING_ROLES = f"""
DO $$
DECLARE
    provisioner text := current_setting('app._bootstrap_role');
    r record;
BEGIN
    FOR r IN SELECT rolname FROM pg_roles WHERE {_ADMINISTERED_ROLE_PATTERN}
    LOOP
        EXECUTE format('GRANT %I TO %I WITH ADMIN OPTION', r.rolname, provisioner);
    END LOOP;
END
$$;
"""

_ADMINISTER_LOGIN_ROLE = """
DO $$ BEGIN
    EXECUTE format('GRANT %I TO %I WITH ADMIN OPTION',
                   current_setting('app._bootstrap_grantee'),
                   current_setting('app._bootstrap_role'));
END $$;
"""

# Hand the app's objects to the provisioning role, for a database that has been
# running under another login. Postgres renders each statement so identifiers
# are quoted at the source; the caller executes what comes back and logs it.
#
# Scope is what the app can show is its own: the shared tables named in its own
# registry, the guild schemas and everything in them, and the enums those
# tables use. An object in ``public`` that the registry does not name is left
# where it is. Extension members are never taken.
_TRANSFER_STATEMENTS = """
WITH app_tables AS (
    SELECT unnest(string_to_array(current_setting('app._bootstrap_tables'), ',')) AS name
), target AS (
    SELECT current_setting('app._bootstrap_role') AS role
)
SELECT format('table %I.%I', n.nspname, c.relname) AS label,
       format('ALTER TABLE %I.%I OWNER TO %I', n.nspname, c.relname, target.role) AS stmt
  FROM pg_class c
  JOIN pg_namespace n ON n.oid = c.relnamespace, target
 WHERE c.relkind IN ('r', 'v', 'm', 'p')
   AND c.relowner = current_user::regrole
   AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.objid = c.oid AND d.deptype = 'e')
   AND (n.nspname ~ '^guild_([0-9]+|template)$'
        OR (n.nspname = 'public' AND c.relname IN (SELECT name FROM app_tables)))
UNION ALL
SELECT format('sequence %I.%I', n.nspname, c.relname),
       format('ALTER SEQUENCE %I.%I OWNER TO %I', n.nspname, c.relname, target.role)
  FROM pg_class c
  JOIN pg_namespace n ON n.oid = c.relnamespace, target
 WHERE c.relkind = 'S'
   AND c.relowner = current_user::regrole
   AND n.nspname ~ '^guild_([0-9]+|template)$'
   AND NOT EXISTS (
       SELECT 1 FROM pg_depend d
        WHERE d.objid = c.oid AND d.deptype IN ('a', 'e'))
UNION ALL
SELECT format('type public.%I', t.typname),
       format('ALTER TYPE public.%I OWNER TO %I', t.typname, target.role)
  FROM pg_type t, target
 WHERE t.typnamespace = 'public'::regnamespace
   AND t.typtype = 'e'
   AND t.typowner = current_user::regrole
   AND EXISTS (
       SELECT 1 FROM pg_attribute a
         JOIN pg_class c2 ON c2.oid = a.attrelid
         JOIN pg_namespace n2 ON n2.oid = c2.relnamespace
        WHERE a.atttypid = t.oid AND NOT a.attisdropped
          AND (n2.nspname ~ '^guild_([0-9]+|template)$'
               OR (n2.nspname = 'public'
                   AND c2.relname IN (SELECT name FROM app_tables))))
UNION ALL
SELECT format('function %s', p.oid::regprocedure),
       format('ALTER FUNCTION %s OWNER TO %I', p.oid::regprocedure, target.role)
  FROM pg_proc p, target
 WHERE p.pronamespace = 'public'::regnamespace
   AND p.proowner = current_user::regrole
   AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.objid = p.oid AND d.deptype = 'e')
   AND EXISTS (
       SELECT 1 FROM pg_trigger tg
         JOIN pg_class c3 ON c3.oid = tg.tgrelid
         JOIN pg_namespace n3 ON n3.oid = c3.relnamespace
        WHERE tg.tgfoid = p.oid
          AND (n3.nspname ~ '^guild_([0-9]+|template)$'
               OR (n3.nspname = 'public'
                   AND c3.relname IN (SELECT name FROM app_tables)))
       UNION ALL
       -- The catalog records what a policy actually calls, so this is an
       -- exact dependency rather than a match on the rendered expression.
       SELECT 1 FROM pg_depend dep
         JOIN pg_policy pol ON pol.oid = dep.objid
         JOIN pg_class c4 ON c4.oid = pol.polrelid
         JOIN pg_namespace n4 ON n4.oid = c4.relnamespace
        WHERE dep.classid = 'pg_policy'::regclass
          AND dep.refclassid = 'pg_proc'::regclass
          AND dep.refobjid = p.oid
          AND (n4.nspname ~ '^guild_([0-9]+|template)$'
               OR (n4.nspname = 'public'
                   AND c4.relname IN (SELECT name FROM app_tables))))
UNION ALL
SELECT format('schema %I', n.nspname),
       format('ALTER SCHEMA %I OWNER TO %I', n.nspname, target.role)
  FROM pg_namespace n, target
 WHERE n.nspname ~ '^guild_([0-9]+|template)$'
   AND n.nspowner = current_user::regrole
"""


# A login role must hold no default privilege: a new shared table gives it
# nothing until a migration grants it from the audited registry. Revoked rather
# than merely not granted, so a database that was handed over by an earlier
# build converges instead of keeping what that build set.
_REVOKE_LOGIN_DEFAULT_PRIVILEGES = """
DO $$
DECLARE
    provisioner text := current_setting('app._bootstrap_role');
    grantee text := current_setting('app._bootstrap_grantee');
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = grantee) THEN
        RETURN;
    END IF;
    EXECUTE format(
        'ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA public '
        'REVOKE ALL ON TABLES FROM %I', provisioner, grantee);
    EXECUTE format(
        'ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA public '
        'REVOKE ALL ON SEQUENCES FROM %I', provisioner, grantee);
END
$$;
"""

# Tables created by future provisioner-run migrations reach the routed roles
# through the two shared floors. The login roles are deliberately absent: a new
# shared table grants them nothing until a migration decides, from the audited
# registry in app.db.system_grants. Skipped until the floors exist — the
# baseline migration creates them, and the next start asserts this.
_DEFAULT_PRIVILEGES = """
DO $$
DECLARE
    provisioner text := current_setting('app._bootstrap_role');
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_guild_base')
       OR NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'platform_base') THEN
        RETURN;
    END IF;
    EXECUTE format(
        'ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA public '
        'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES '
        'TO app_guild_base, platform_base',
        provisioner);
    EXECUTE format(
        'ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA public '
        'GRANT SELECT, USAGE ON SEQUENCES TO app_guild_base, platform_base',
        provisioner);
END
$$;
"""


# --- Search operator --------------------------------------------------------
#
# Guild search matches a tsvector against a tsquery. These objects give it its
# own match operator and GIN operator class so its index can serve that match.
# The stock `@@` operator is left exactly as Postgres ships it.

# PL/pgSQL rather than SQL on purpose: a SQL body is inlined into the calling
# query, which discards the attributes declared here.
_SEARCH_MATCH_FUNCTION = """
CREATE OR REPLACE FUNCTION public.search_tsmatch(tsvector, tsquery)
    RETURNS boolean
    LANGUAGE plpgsql
    IMMUTABLE STRICT PARALLEL SAFE LEAKPROOF
    AS $fn$ BEGIN RETURN $1 OPERATOR(pg_catalog.@@) $2; END $fn$;
"""

_SEARCH_FUNCTION_COMMENT = """
COMMENT ON FUNCTION public.search_tsmatch(tsvector, tsquery) IS
    'Guild search text match, behind the public.@@@ operator. Body is PL/pgSQL '
    'so the attributes declared here survive planning.';
"""

# Selectivity estimators are the stock full-text ones, so the planner costs
# this exactly as it costs `@@`.
_SEARCH_OPERATOR = """
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_operator o
        JOIN pg_namespace n ON n.oid = o.oprnamespace
        WHERE n.nspname = 'public' AND o.oprname = '@@@'
          AND o.oprleft = 'tsvector'::regtype AND o.oprright = 'tsquery'::regtype
    ) THEN
        CREATE OPERATOR public.@@@ (
            LEFTARG   = tsvector,
            RIGHTARG  = tsquery,
            PROCEDURE = public.search_tsmatch,
            RESTRICT  = tsmatchsel,
            JOIN      = tsmatchjoinsel
        );
    END IF;
END
$$;
"""

# Support functions are the stock ones — only the operator differs, so an index
# built on this behaves like any tsvector GIN index.
_SEARCH_OPERATOR_CLASS = """
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_opclass c
        JOIN pg_namespace n ON n.oid = c.opcnamespace
        WHERE n.nspname = 'public' AND c.opcname = 'tsvector_search_ops'
    ) THEN
        CREATE OPERATOR CLASS public.tsvector_search_ops
            FOR TYPE tsvector USING gin AS
            OPERATOR 1 public.@@@ (tsvector, tsquery),
            FUNCTION 1 pg_catalog.gin_cmp_tslexeme(text, text),
            FUNCTION 2 pg_catalog.gin_extract_tsvector(tsvector, internal, internal),
            FUNCTION 3 pg_catalog.gin_extract_tsquery(tsvector, internal, smallint,
                           internal, internal, internal, internal),
            FUNCTION 4 pg_catalog.gin_tsquery_consistent(internal, smallint, tsvector,
                           integer, internal, internal, internal, internal),
            FUNCTION 5 pg_catalog.gin_cmp_prefix(text, text, smallint, internal),
            FUNCTION 6 pg_catalog.gin_tsquery_triconsistent(internal, smallint, tsvector,
                           integer, internal, internal, internal),
            STORAGE text;
    END IF;
END
$$;
"""

_SEARCH_OPERATOR_STEPS = (
    ("search match function", _SEARCH_MATCH_FUNCTION),
    ("search match function comment", _SEARCH_FUNCTION_COMMENT),
    ("search match operator", _SEARCH_OPERATOR),
    ("search operator class", _SEARCH_OPERATOR_CLASS),
)


def search_operator_sql() -> tuple[str, ...]:
    """The statements that install the guild-search match operator, in order."""
    return tuple(statement for _label, statement in _SEARCH_OPERATOR_STEPS)


#: Both objects must be present for guild search to use its index.
_SEARCH_OPERATOR_PRESENT = text(
    "SELECT "
    "  coalesce((SELECT p.proleakproof FROM pg_proc p"
    "            JOIN pg_namespace n ON n.oid = p.pronamespace"
    "            WHERE n.nspname = 'public' AND p.proname = 'search_tsmatch'), false)"
    "  AND EXISTS (SELECT 1 FROM pg_opclass c"
    "              JOIN pg_namespace n ON n.oid = c.opcnamespace"
    "              WHERE n.nspname = 'public' AND c.opcname = 'tsvector_search_ops')"
)

_IS_SUPERUSER = text("SELECT rolsuper FROM pg_roles WHERE rolname = current_user")


async def _set_local(conn, key: str, value: str) -> None:
    await conn.execute(text("SELECT set_config(:k, :v, true)"), {"k": key, "v": value})


async def _apply_roles(conn, roles: tuple[LoginRole, ...]) -> None:
    provisioner = roles[0]
    for role in roles:
        await _set_local(conn, "app._bootstrap_role", role.name)
        await _set_local(conn, "app._bootstrap_attrs", role.attributes)
        await _set_local(conn, "app._bootstrap_pw", role.password or "")
        await conn.execute(text(_ENSURE_ROLE))
    await _set_local(conn, "app._bootstrap_pw", "")

    # Everything below acts for the provisioning role.
    await _set_local(conn, "app._bootstrap_role", provisioner.name)
    await conn.execute(text(_GRANT_DATABASE))
    await conn.execute(text(_REVOKE_TEMPORARY))
    await conn.execute(text(_VERIFY_TEMPORARY_REVOKED))
    await conn.execute(text(_OWN_PUBLIC_SCHEMA))
    for role in roles:
        if role.name == provisioner.name:
            continue
        await _set_local(conn, "app._bootstrap_grantee", role.name)
        await conn.execute(text(_ADMINISTER_LOGIN_ROLE))
        await conn.execute(text(_REVOKE_LOGIN_DEFAULT_PRIVILEGES))
    await conn.execute(text(_ADMINISTER_EXISTING_ROLES))
    await _transfer_ownership(conn)
    await conn.execute(text(_DEFAULT_PRIVILEGES))


@asynccontextmanager
async def _bootstrap_lock(url: str):
    """Hold the bootstrap lock for the block.

    Prefers a session lock on the cluster's maintenance database, so two
    deployments on one cluster serialize too. Falls back to the caller's own
    database, where the lock is still taken per transaction by the caller.
    """
    base = make_url(url)
    for database in _MAINTENANCE_DATABASES:
        engine = create_async_engine(
            base.set(database=database), poolclass=NullPool, echo=False
        )
        try:
            conn = await engine.connect()
        except Exception:
            await engine.dispose()
            continue
        try:
            await conn.execute(
                text("SELECT pg_advisory_lock(:key)"), {"key": _BOOTSTRAP_LOCK_KEY}
            )
            yield
            return
        finally:
            await conn.close()
            await engine.dispose()
    logger.debug(
        "database bootstrap: no maintenance database reachable for the "
        "cluster-wide lock; serializing on the app database only"
    )
    yield


async def _transfer_ownership(conn) -> None:
    """Hand the app's own objects to the provisioning role.

    Nothing to do on a fresh install, where the provisioning role creates them,
    or on any later start. A database that has been running under another login
    moves once, and what moved is logged.
    """
    await _set_local(
        conn, "app._bootstrap_tables", ",".join(sorted(GRANTABLE_SHARED_TABLES))
    )
    rows = (await conn.execute(text(_TRANSFER_STATEMENTS))).all()
    if not rows:
        return
    for label, statement in rows:
        await conn.execute(text(statement))
    logger.info(
        "database bootstrap: took ownership of %d object(s): %s",
        len(rows),
        ", ".join(label for label, _stmt in rows),
    )


async def _apply_search_operator(conn) -> bool:
    """Install the match operator objects. Returns whether they are present
    afterwards — a non-superuser bootstrap connection cannot create them, and
    that is reported rather than raised: search works without them."""
    if not await conn.scalar(_IS_SUPERUSER):
        return bool(await conn.scalar(_SEARCH_OPERATOR_PRESENT))
    for label, statement in _SEARCH_OPERATOR_STEPS:
        try:
            await conn.execute(text(statement))
        except Exception:
            logger.exception("database bootstrap: %s failed", label)
            return False
    return bool(await conn.scalar(_SEARCH_OPERATOR_PRESENT))


def bootstrap_sql() -> str:
    """The whole bootstrap as runnable SQL, for an operator applying it by hand.

    The role name and password GUCs the statements read are emitted as
    ``set_config`` calls ahead of them, so the output runs as-is under ``psql``.
    """
    provisioner, app_login, system = login_roles()
    out: list[str] = [
        "-- Initiative database bootstrap. Run as the database owner",
        "-- (a superuser, for the search operator's LEAKPROOF function).",
        "BEGIN;",
    ]

    def setting(key: str, value: str) -> str:
        return f"SELECT set_config('{key}', {_sql_literal(value)}, true);"

    for role in (provisioner, app_login, system):
        out += [
            "",
            f"-- {role.name}",
            setting("app._bootstrap_role", role.name),
            setting("app._bootstrap_attrs", role.attributes),
            setting("app._bootstrap_pw", role.password or ""),
            _ENSURE_ROLE.strip(),
        ]
    out += [
        "",
        "-- Database, schema ownership and role administration",
        setting("app._bootstrap_pw", ""),
        setting("app._bootstrap_role", provisioner.name),
        _GRANT_DATABASE.strip(),
        _REVOKE_TEMPORARY.strip(),
        _VERIFY_TEMPORARY_REVOKED.strip(),
        _OWN_PUBLIC_SCHEMA.strip(),
    ]
    for role in (app_login, system):
        out += [
            setting("app._bootstrap_grantee", role.name),
            _ADMINISTER_LOGIN_ROLE.strip(),
            _REVOKE_LOGIN_DEFAULT_PRIVILEGES.strip(),
        ]
    out += [
        _ADMINISTER_EXISTING_ROLES.strip(),
        "-- Ownership handover, for a database already running under another",
        "-- login. Each statement is rendered by the query below; run what it",
        "-- returns. Nothing to do on a fresh install.",
        _TRANSFER_STATEMENTS.strip() + ";",
        _DEFAULT_PRIVILEGES.strip(),
        "",
        "-- Guild search match operator",
    ]
    out += [statement.strip() for _label, statement in _SEARCH_OPERATOR_STEPS]
    out += ["", "COMMIT;"]
    return "\n".join(out) + "\n"


def _sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _repair_instructions(missing: list[str]) -> str:
    return (
        "The database is missing prerequisites the app cannot create as its "
        "own roles: " + ", ".join(missing) + ".\n"
        "Either set DATABASE_URL_BOOTSTRAP to a connection URL for the "
        "database owner and restart — the app then applies them itself — or "
        "apply them once by hand:\n"
        "  docker compose exec -T initiative python -m app.db.bootstrap "
        "--print-sql | psql -v ON_ERROR_STOP=1 -U <owner> -d <database>\n"
    )


async def _verify_only() -> BootstrapResult:
    """Check the invariants using the provisioning connection the app already
    has, for deployments that provision their database out of band."""
    from app.db import session as db_session

    provisioner, app_login, system = login_roles()
    missing: list[str] = []
    async with db_session.provisioning_engine.connect() as conn:
        present = {
            row[0]
            for row in (
                await conn.execute(
                    text("SELECT rolname FROM pg_roles WHERE rolname = ANY(:names)"),
                    {"names": [provisioner.name, app_login.name, system.name]},
                )
            ).all()
        }
        for role in (provisioner, app_login, system):
            if role.name not in present:
                missing.append(f"role {role.name}")
        search_ready = bool(await conn.scalar(_SEARCH_OPERATOR_PRESENT))
    if missing:
        raise RuntimeError(_repair_instructions(missing))
    return BootstrapResult(
        applied=False,
        roles=(provisioner.name, app_login.name, system.name),
        search_operator_installed=search_ready,
        notes=("DATABASE_URL_BOOTSTRAP is not set; verified only",),
    )


async def ensure_database_bootstrap(
    bootstrap_url: str | None = None,
) -> BootstrapResult:
    """Apply the privileged prerequisites, or verify them when no bootstrap URL
    is configured. Called once at startup, before migrations.

    ``bootstrap_url`` overrides ``DATABASE_URL_BOOTSTRAP`` for callers that
    already know which connection to use — the test harness sources its own
    superuser and points this at the database under test.
    """
    url = bootstrap_url or settings.DATABASE_URL_BOOTSTRAP
    if not url:
        return await _verify_only()

    roles = login_roles()
    engine = create_async_engine(url, poolclass=NullPool, echo=False)
    try:
        async with _bootstrap_lock(url), engine.begin() as conn:
            await conn.execute(
                text("SELECT pg_advisory_xact_lock(:key)"),
                {"key": _BOOTSTRAP_LOCK_KEY},
            )
            try:
                await _apply_roles(conn, roles)
            except Exception as exc:
                raise RuntimeError(
                    "DATABASE_URL_BOOTSTRAP could not apply the database "
                    "prerequisites. It must connect as the owner of the "
                    f"database (and, for the search operator, a superuser): "
                    f"{exc}"
                ) from exc
            search_ready = await _apply_search_operator(conn)
    finally:
        await engine.dispose()

    result = BootstrapResult(
        applied=True,
        roles=tuple(role.name for role in roles),
        search_operator_installed=search_ready,
    )
    logger.info(
        "database bootstrap applied: roles %s; search operator %s. "
        "DATABASE_URL_BOOTSTRAP is only needed to apply these — remove it and "
        "the app verifies them instead, naming anything missing.",
        ", ".join(result.roles),
        "present" if search_ready else "NOT installed",
    )
    return result


async def _main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    result = await ensure_database_bootstrap()
    print(
        f"roles: {', '.join(result.roles)}\n"
        f"search operator: "
        f"{'present' if result.search_operator_installed else 'missing'}"
    )
    return 0


if __name__ == "__main__":
    import sys

    if "--print-sql" in sys.argv:
        print(bootstrap_sql(), end="")
    else:
        raise SystemExit(asyncio.run(_main()))
