"""The authorization functions the guild policies defer to.

Every initiative-scoped table in every ``guild_<id>`` schema carries policies
that call into one of these. They come in two kinds. The four in
:data:`GUILD_AUTHORIZATION_FUNCTIONS` read only guild tables and are rendered
into each guild schema beside the policies that call them (``guild_ddl``), so
a community's access rules live inside its own boundary and a change rolls
out schema by schema with the provisioning stamp. The six in
:data:`AUTHORIZATION_FUNCTIONS` read shared tables and live in ``public``,
applied once at boot. Both kinds name the tables they read unqualified, so the
routed ``search_path`` binds ``initiative_members`` to the caller's own schema
(see ``search_path_pinning_test``). Each runs as its caller.

The guild four used to live in ``public`` too, one definition for every
community. The migrations that created them there are frozen, so the copies
they left are retired by :func:`drop_public_copies` on boot, after the guild
back-fill has re-rendered every schema's policies against its local copy:
Postgres refuses the drop while any policy still binds a public one, and the
step reads that refusal as "not yet" and tries again next boot.

**Why they are here and not only in a migration.** They used to exist solely
inside the migrations that created them, carried forward by ``CREATE OR
REPLACE`` and copied again into each downgrade. That left the rules the whole
access model rests on with no file to read, nothing to diff against, and no
repair for a deployment whose migration only half-applied. Every other
DB-enforced rule in this codebase is already rendered from app code and
re-applied on boot — the RLS policies from ``initiative_rls``, the frozen
guards from ``frozen``, the search triggers from ``search_index``,
``search_tsmatch`` from ``bootstrap``. These were the exception.

So: this module is the source, :func:`apply_authorization_functions` runs on
every boot, and ``authorization_test`` fails if the database and this file
disagree. Migrations still create them for the upgrade path, importing from
here rather than holding a copy.

**Editing one.** Change the text here and ship it; boot applies it. A change
that alters *behaviour* still wants a migration, so the deployment converges
before it serves rather than at its next restart. That migration states the
new body in full and keeps the one it replaces for its downgrade: a revision
is a record of one moment, and a body read from this module would change what
a past revision does every time this file is edited. ``CREATE OR REPLACE``
keeps the OID, so every policy deferring to the function picks the new body up
unrewritten.

A guild copy is created with the guild schema first on the ``search_path``,
so the tables its body names are resolved and checked at creation. Resolution
at call time is still the caller's route, which is the same schema.
"""

from __future__ import annotations
from collections.abc import Iterable
from app.models.platform.access_grant import AccessGrantPurpose, SettingsLevel
from app.models.platform.guild import GuildRole
from app.models.platform.user import UserRole
from app.models.tenant.resource_grant import WRITE_LEVELS

import hashlib
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

#: SQLSTATE 2BP01: Postgres refusing a DROP because something still depends
#: on the object.
DEPENDENT_OBJECTS_STILL_EXIST_SQLSTATE = "2BP01"

__all__ = [
    "AUTHORIZATION_FUNCTIONS",
    "GUILD_AUTHORIZATION_FUNCTIONS",
    "GUILD_FUNCTION_SIGNATURES",
    "RETIRED_GUILD_FUNCTION_SIGNATURES",
    "GUILD_SUPERADMIN",
    "DropReport",
    "apply_authorization_functions",
    "authorization_functions_digest",
    "drop_public_copies",
    "ensure_authorization_functions",
    "ensure_public_copies_dropped",
    "render_guild_authorization_functions",
]

#: Gate 0a: the rule itself — does an authentication satisfy one of a
#: community's connections?
#:
#: Takes the facts rather than reading them, so the request path can ask the
#: same question before a session's context exists. ``p_providers`` is what
#: the credential proved; ``p_claims`` is what those providers asserted,
#: ``{"12": {"hd": ["acme.com"]}}``.
GUILD_CONNECTION_ADMITS = """\
CREATE OR REPLACE FUNCTION public.guild_connection_admits(p_guild_id integer, p_providers integer[], p_claims jsonb, p_provider_id integer DEFAULT NULL::integer)
 RETURNS boolean
 LANGUAGE sql
 STABLE
AS $function$
    WITH effective AS (
        -- What this community said, and the deployment's own answer for a
        -- provider it has said nothing about. One row shadows one row: a
        -- community's own connection replaces the default outright, including
        -- one it wrote with `enabled` off to decline it.
        SELECT c.provider_id, c.enabled, c.claim, c.claim_values
        FROM public.guild_provider_connections c
        WHERE c.guild_id = p_guild_id
        UNION ALL
        SELECT d.provider_id, d.enabled, d.claim, d.claim_values
        FROM public.platform_provider_defaults d
        WHERE NOT EXISTS (
            SELECT 1
            FROM public.guild_provider_connections own
            WHERE own.guild_id = p_guild_id
              AND own.provider_id = d.provider_id
        )
    )
    SELECT EXISTS (
        SELECT 1
        FROM effective c
        WHERE c.enabled
          AND (p_provider_id IS NULL OR c.provider_id = p_provider_id)
          AND c.provider_id = ANY(COALESCE(p_providers, ARRAY[]::integer[]))
          -- A connection names a claim and the values that count, or it
          -- admits nobody. An arrangement that says who belongs by saying
          -- nothing is not one this reads as everybody.
          AND c.claim IS NOT NULL
          AND c.claim_values IS NOT NULL
          AND (
              EXISTS (
                  SELECT 1
                  FROM jsonb_array_elements_text(
                      CASE
                          WHEN jsonb_typeof(
                                   COALESCE(p_claims, '{}'::jsonb)
                                       -> c.provider_id::text -> c.claim
                               ) = 'array'
                          THEN COALESCE(p_claims, '{}'::jsonb)
                                   -> c.provider_id::text -> c.claim
                          ELSE '[]'::jsonb
                      END
                  ) AS asserted(value)
                  WHERE lower(asserted.value) = ANY (
                      SELECT lower(counted) FROM unnest(c.claim_values) AS counted
                  )
              )
          )
    )
$function$

"""


#: Gate 0b: the same question for the current request, off the GUCs the
#: session context sets. This is what the policy legs call.
GUILD_CONNECTION_SATISFIED = """\
CREATE OR REPLACE FUNCTION public.guild_connection_satisfied(p_guild_id integer, p_provider_id integer DEFAULT NULL::integer)
 RETURNS boolean
 LANGUAGE sql
 STABLE
AS $function$
    SELECT public.guild_connection_admits(
        p_guild_id,
        -- NULLIF twice: an unset value and the system sentinel both leave
        -- nothing to cast, and a bare ''::int[] would fault every policy on
        -- the table.
        COALESCE(
            string_to_array(
                NULLIF(
                    NULLIF(current_setting('app.satisfied_providers', true), ''),
                    'system'
                ),
                ','
            )::integer[],
            ARRAY[]::integer[]
        ),
        COALESCE(
            NULLIF(current_setting('app.satisfied_claims', true), '')::jsonb,
            '{}'::jsonb
        ),
        p_provider_id
    )
$function$

"""


#: What this session recorded about how it was opened, as an array.
#:
#: ``app.session_amr`` holds the markers narrowed to the closed vocabulary in
#: ``app.services.auth.assurance`` — ``mfa`` where a code was presented,
#: ``hwk``/``swk`` where a key answered — comma-joined and sorted. One reader
#: rather than the parse repeated in each leg, and one place for the COALESCE:
#: ``string_to_array`` of an unset setting is NULL, and the empty array is what
#: the legs below are written against, so an absent setting reads as a session
#: that recorded nothing.
SESSION_AMR = """\
CREATE OR REPLACE FUNCTION public.session_amr()
 RETURNS text[]
 LANGUAGE sql
 STABLE
AS $function$
    SELECT COALESCE(
        string_to_array(
            NULLIF(current_setting('app.session_amr', true), ''),
            ','
        ),
        ARRAY[]::text[]
    )
$function$

"""


#: Gate 0, first half: the deployment's own second-factor rule.
#:
#: The level is read from the settings row rather than from a GUC — what the
#: deployment asks is a fact it holds, and the singleton is readable under
#: every routed role, the SELECT-only guild floor included. Which rung the
#: session holds arrives as ``app.platform_role``, because ``public.users`` is
#: not on a guild request's path, and whether the account answers the rule
#: arrives as ``app.platform_factor`` — the second factor it holds, or one
#: this session presented. Both are written with the rest of the request's
#: context.
#:
#: Unset reads as fail-closed: no rung recorded is not ``member``, and no
#: standing recorded is not answered.
PLATFORM_FACTOR_SATISFIED = f"""\
CREATE OR REPLACE FUNCTION public.platform_factor_satisfied()
 RETURNS boolean
 LANGUAGE sql
 STABLE
AS $function$
    SELECT NOT EXISTS (
        SELECT 1 FROM public.app_settings s
        WHERE s.id = 1
          AND s.second_factor_requirement <> 'nobody'
          AND (
              s.second_factor_requirement = 'everyone'
              OR COALESCE(current_setting('app.platform_role', true), '') <> '{UserRole.member.value}'
          )
          AND COALESCE(
                current_setting('app.platform_factor', true), 'false'
              ) <> 'true'
    )
$function$

"""


#: Gate 0: the guild's sign-in policy, satisfied by this session.
GUILD_AUTH_SATISFIED = """\
CREATE OR REPLACE FUNCTION public.guild_auth_satisfied()
 RETURNS boolean
 LANGUAGE sql
 STABLE
AS $function$
    SELECT
        -- Pure system routing (no user context) and the explicit sentinel a
        -- user-attributed job sets are not sessions to gate.
        NULLIF(current_setting('app.current_user_id', true), '') IS NULL
        OR current_setting('app.satisfied_providers', true) = 'system'
        OR (
        -- What the deployment asks of the account, before what the community
        -- asks of the session. Both have to hold.
        public.platform_factor_satisfied()
        AND NOT EXISTS (
            SELECT 1 FROM public.guild_auth_policies p
            WHERE p.guild_id = NULLIF(
                    current_setting('app.current_guild_id', true), ''
                  )::int
              AND p.policy <> 'open'
              AND (
                  -- The provider this guild names, if it names one: the
                  -- session came through it, and this community counts the
                  -- arrival as one of its own.
                  (
                      p.provider_id IS NOT NULL
                      AND NOT public.guild_connection_satisfied(
                            p.guild_id, p.provider_id
                          )
                  )
                  -- Or the account's own second factor, where the community
                  -- asks for one. The session records it when a code is
                  -- presented and the request carries that here.
                  OR (
                      'totp' = ANY(p.require_methods)
                      AND NOT ('mfa' = ANY(public.session_amr()))
                  )
                  -- Or a passkey, where the community asks for one. Its own
                  -- leg rather than the factor's: an assertion records the
                  -- second factor too, so the two are asked for separately.
                  -- Either kind of key answers, which is what the overlap says.
                  OR (
                      'passkey' = ANY(p.require_methods)
                      AND NOT (public.session_amr() && ARRAY['hwk', 'swk'])
                  )
                  -- Or any of its own, whichever provider served it. Named
                  -- rather than counted, so a list holding some other method
                  -- is not read as this one.
                  OR (
                      'sso' = ANY(p.require_methods)
                      AND NOT public.guild_connection_satisfied(p.guild_id)
                  )
              )
        )
        AND NOT EXISTS (
            -- Asked of everybody reaching this community, whatever it says
            -- about how they arrive. Its own row rather than the policy's,
            -- because a community that asks nothing about arrival holds no
            -- policy row and still asks this. Unsatisfied is what this finds,
            -- like the leg above it.
            SELECT 1
            FROM public.guilds g
            WHERE g.id = NULLIF(
                    current_setting('app.current_guild_id', true), ''
                  )::int
              AND g.require_second_factor
              AND NOT ('mfa' = ANY(public.session_amr()))
        ))
$function$

"""

# --- The legs every gate below shares ---------------------------------------
#
# Each is a SQL fragment, written once and substituted into the bodies. They
# read the request's standing — what the establishment seam computed for this
# reader in this community, once, in one statement (``app.db.guild_standing``)
# — rather than walking a table per row.
#
# The four gates that carry them are ``plpgsql`` rather than ``LANGUAGE sql``.
# Each holds a sub-select (the system leg's catalog lookup, and in
# ``resource_access`` the grants probe), which is what stops Postgres inlining
# a SQL function; a SQL function that is not inlined is planned again on every
# query execution that first calls it, and inside another function every call
# is one. A plpgsql function keeps its plan for the session.

#: Trusted system maintenance, admitted by the connection's own login rather
#: than by anything a statement can write. A sweep assumes a community's role
#: for its schema, which drops the login's bypass, and this is what says the
#: login was the system engine's. ``session_user`` is the connection's, not the
#: assumed role's; the sub-select names no row variable, so the planner
#: evaluates it once per statement.
SYSTEM_SESSION = (
    "EXISTS (SELECT 1 FROM pg_roles r"
    " WHERE r.rolname = session_user AND r.rolbypassrls)"
)

#: The community this session reads: a member routes with
#: ``app.current_guild_id``, a content grantee with ``app.pam_guild_id`` and a
#: settings grantee with ``app.settings_guild_id``. Whichever names one is the
#: one community the session is in.
ROUTED_COMMUNITY = (
    "COALESCE("
    "NULLIF(current_setting('app.current_guild_id'::text, true), ''::text),"
    " NULLIF(current_setting('app.pam_guild_id'::text, true), ''::text),"
    " NULLIF(current_setting('app.settings_guild_id'::text, true), ''::text))"
)

#: The standing on this session was computed for the community it is routed
#: into. A standing means nothing outside the community it came from —
#: initiative 5 is a different row in every schema — so every leg that reads
#: one says which community it belongs to first.
STANDING_IS_THIS_GUILD = (
    "NULLIF(current_setting('app.standing_guild_id'::text, true), ''::text)"
    f" IS NOT DISTINCT FROM {ROUTED_COMMUNITY}"
)

#: The reader administers this community: the membership row's own answer, as
#: the standing statement read it, written where a policy can read it.
GUILD_ADMIN = (
    f"({STANDING_IS_THIS_GUILD}"
    " AND current_setting('app.guild_admin'::text, true) = 'true'::text)"
)

#: This request administers the community's configuration: a live settings
#: grant, at either rung, as the standing statement read it from the rows.
#: Its own axis — what a grant reaches of the community's settings — beside
#: :data:`GUILD_ADMIN`, which only a membership row answers.
SETTINGS_ADMIN = (
    f"({STANDING_IS_THIS_GUILD}"
    " AND current_setting('app.settings_rung'::text, true) <> ''::text)"
)

#: A live grant covers this request, at whichever level the command asks for.
PAM_AT_LEVEL = (
    "(CASE"
    " WHEN p_need_write"
    " THEN current_setting('app.pam_write'::text, true) = 'true'::text"
    " ELSE current_setting('app.pam_read'::text, true) = 'true'::text"
    " OR current_setting('app.pam_write'::text, true) = 'true'::text"
    " END)"
)

#: A live grant at either level, where the question is what the community has
#: switched on rather than what one person may reach.
PAM_ANY = (
    "current_setting('app.pam_read'::text, true) = 'true'::text"
    " OR current_setting('app.pam_write'::text, true) = 'true'::text"
)


def standing_ids(key: str) -> str:
    """The integer set the standing carries under ``key``.

    Empty rather than NULL when nothing is recorded: ``x = ANY(NULL)`` is NULL,
    and a leg that answers neither yes nor no turns the whole chain around it
    into one, which reads as no in a policy and as nothing at all to anybody
    asking the function directly.
    """
    return (
        "COALESCE(string_to_array("
        f"NULLIF(current_setting('{key}'::text, true), ''::text), ','::text"
        ")::integer[], ARRAY[]::integer[])"
    )


def standing_pairs(key: str) -> str:
    """The ``"<id>:<name>"`` set the standing carries under ``key``."""
    return (
        "COALESCE(string_to_array("
        f"NULLIF(current_setting('{key}'::text, true), ''::text), ','::text"
        "), ARRAY[]::text[])"
    )


def sql_values(values: Iterable[str]) -> str:
    """``'a', 'b'`` — a value list for an ``IN`` clause.

    Rendered from the enum that owns the vocabulary, the way the tool switches
    are rendered from ``Tool``, so the SQL spells a rung the way Python does
    and a rung added to the ladder reaches every policy on the next render.
    """
    return ", ".join(f"'{value}'" for value in values)


#: Gate 2: the hard isolation boundary. Every initiative-scoped table's
#: policies defer to this one function.
INITIATIVE_ACCESS = f"""\
CREATE OR REPLACE FUNCTION initiative_access(p_initiative_id integer, p_user_id integer, p_need_write boolean DEFAULT false)
 RETURNS boolean
 LANGUAGE plpgsql
 STABLE
AS $function$
BEGIN
    RETURN
        current_setting('app.guild_auth_ok'::text, true) = 'true'::text
        AND (
            -- The read's own scope, when the surface asking has one. A row of
            -- another initiative is not the answer to the question, whatever
            -- else the context allows. Guild-level rows belong to no
            -- initiative and stay in scope.
            p_initiative_id IS NULL
            OR NULLIF(current_setting('app.scope_initiative_id'::text, true), ''::text)::integer IS NULL
            OR p_initiative_id = NULLIF(current_setting('app.scope_initiative_id'::text, true), ''::text)::integer
        )
        AND (
            -- Guild-level scope: the row belongs to no initiative, so the
            -- initiative gate has nothing to decide. The schema boundary still
            -- confines it to this guild; grants decide who may read or write it.
            p_initiative_id IS NULL
            OR {SYSTEM_SESSION}
            OR {GUILD_ADMIN}
            OR {PAM_AT_LEVEL}
            OR ({STANDING_IS_THIS_GUILD}
                AND p_initiative_id = ANY ({standing_ids("app.member_initiatives")}))
        )
    ;
END
$function$

"""

#: Gate 2, narrowed: full standing in the initiative rather than membership.
INITIATIVE_FULL_ACCESS = f"""\
CREATE OR REPLACE FUNCTION initiative_full_access(p_initiative_id integer, p_need_write boolean DEFAULT false)
 RETURNS boolean
 LANGUAGE plpgsql
 STABLE
AS $function$
BEGIN
    RETURN
        current_setting('app.guild_auth_ok'::text, true) = 'true'::text
        AND (
            {SYSTEM_SESSION}
            OR {GUILD_ADMIN}
            OR {PAM_AT_LEVEL}
            OR ({STANDING_IS_THIS_GUILD}
                AND p_initiative_id = ANY ({standing_ids("app.override_initiatives")}))
        )
    ;
END
$function$

"""

#: Gate 3: what a member's role in the initiative permits.
#:
#: The roles' stored rows arrive in the standing as two sets of
#: ``"<initiative>:<key>"`` pairs — the ones the role turns on and the ones it
#: turns off — so the answer is a membership test rather than a three-table
#: join per row. A manager holds every key, stored or not; for everyone else a
#: stored row decides, and the tool's own default decides when there is none.
INITIATIVE_ROLE_PERMITS = f"""\
CREATE OR REPLACE FUNCTION initiative_role_permits(p_initiative_id integer, p_user_id integer, p_key text, p_default boolean)
 RETURNS boolean
 LANGUAGE plpgsql
 STABLE
AS $function$
BEGIN
    RETURN
        -- A row belonging to no initiative has no initiative role to answer to.
        p_initiative_id IS NULL
        OR {SYSTEM_SESSION}
        OR {GUILD_ADMIN}
        OR {PAM_ANY}
        OR ({STANDING_IS_THIS_GUILD} AND (
                p_initiative_id = ANY ({standing_ids("app.manager_initiatives")})
             OR (p_initiative_id::text || ':' || p_key)
                    = ANY ({standing_pairs("app.role_grants")})
             OR (
                 p_default
                 AND p_initiative_id = ANY ({standing_ids("app.member_initiatives")})
                 AND NOT ((p_initiative_id::text || ':' || p_key)
                              = ANY ({standing_pairs("app.role_denies")}))
             )
        ))
    ;
END
$function$

"""

#: Gate 4: per-resource sharing (the ``resource_grants`` table).
#:
#: The one gate that still probes a table, because which readers a resource was
#: shared with is genuinely per resource. What the standing removes is the two
#: reader sub-selects inside it: the roles they hold and the initiatives they
#: are in are the same for every row.
RESOURCE_ACCESS = f"""\
CREATE OR REPLACE FUNCTION resource_access(p_tool text, p_resource_id integer, p_user_id integer, p_initiative_id integer DEFAULT NULL::integer, p_need_write boolean DEFAULT false)
 RETURNS boolean
 LANGUAGE plpgsql
 STABLE
AS $function$
BEGIN
    RETURN
        -- Rows that carry no sharing identity (guild vocabulary) have nothing
        -- for this to decide.
        p_tool IS NULL
        OR {SYSTEM_SESSION}
        OR {GUILD_ADMIN}
        OR {PAM_AT_LEVEL}
        -- Initiatives where the request holds "Full access".
        OR ({STANDING_IS_THIS_GUILD}
            AND p_initiative_id = ANY ({standing_ids("app.override_initiatives")}))
        OR EXISTS (
            SELECT 1 FROM resource_grants g
            WHERE g.resource_type = p_tool
              AND g.resource_id = p_resource_id
              AND (NOT p_need_write OR g.level IN ({sql_values(level.value for level in WRITE_LEVELS)}))
              AND (
                   g.user_id = p_user_id
                OR ({STANDING_IS_THIS_GUILD}
                    AND g.role_id = ANY ({standing_ids("app.member_role_ids")}))
                OR (g.all_initiative_members
                    AND {STANDING_IS_THIS_GUILD}
                    AND (g.initiative_id IS NULL
                         OR g.initiative_id = ANY ({standing_ids("app.member_initiatives")})))
                OR (NOT p_need_write
                    AND g.dashboard_id IS NOT NULL
                    AND g.dashboard_id = NULLIF(current_setting('app.via_dashboard_id'::text, true), '')::int)
              )
        )
    ;
END
$function$

"""


#: Who holds a guild's top seat — its sign-in configuration and its billing.
#:
#: Named ``public.guild_memberships`` in full, unlike its neighbours: this one
#: answers about a shared table rather than a guild-local one, so it resolves
#: the same way from a routed session and an unrouted one.
#:
#: Not ``SECURITY DEFINER``, like everything else here: it runs as its caller
#: and reads what that caller may read. ``guild_memberships_select`` admits a
#: session its own rows and, when routed, the addressed guild's — which covers
#: both questions asked of this: "am I the seat here" on the platform path, and
#: "is the writer the seat" from inside a policy.
#:
#: A live ``superadmin`` settings grant satisfies the same predicate for the
#: duration of its grant.
#:
#: The one definition of the rule. The policies on ``guild_auth_policies`` call
#: it, and so does the app — ``func.guild_superadmin(...)`` where an endpoint
#: has to decide before it writes, the way ``initiative_scope_clause`` already
#: defers to ``initiative_access`` rather than restating it in Python.
GUILD_SUPERADMIN = f"""\
CREATE OR REPLACE FUNCTION public.guild_superadmin(p_guild_id integer, p_user_id integer)
 RETURNS boolean
 LANGUAGE sql
 STABLE
AS $function$
    SELECT EXISTS (
        SELECT 1
        FROM public.guild_memberships m
        WHERE m.guild_id = p_guild_id
          AND m.user_id = p_user_id
          AND m.role = '{GuildRole.superadmin.value}'
    )
    -- A live superadmin settings grant satisfies the same predicate.
    OR EXISTS (
        SELECT 1
        FROM public.access_grants g
        WHERE g.guild_id = p_guild_id
          AND g.user_id = p_user_id
          AND g.purpose = '{AccessGrantPurpose.settings.value}'
          AND g.access_level = '{SettingsLevel.superadmin.value}'
          AND g.status = 'approved'
          AND g.expires_at > now()
    )
$function$

"""


#: Name -> definition, in dependency order: ``guild_connection_satisfied``
#: calls ``guild_connection_admits``, ``guild_auth_satisfied`` calls
#: ``guild_connection_satisfied``, ``session_amr`` and
#: ``platform_factor_satisfied``, and
#: ``initiative_access`` and ``initiative_full_access`` call
#: ``guild_auth_satisfied``. Applied in this order, a fresh database never
#: sees a dangling call.
AUTHORIZATION_FUNCTIONS: tuple[tuple[str, str], ...] = (
    ("guild_connection_admits", GUILD_CONNECTION_ADMITS),
    ("guild_connection_satisfied", GUILD_CONNECTION_SATISFIED),
    ("session_amr", SESSION_AMR),
    ("platform_factor_satisfied", PLATFORM_FACTOR_SATISFIED),
    ("guild_auth_satisfied", GUILD_AUTH_SATISFIED),
    ("guild_superadmin", GUILD_SUPERADMIN),
)

#: The four that read only guild tables. Rendered into every guild schema by
#: ``guild_ddl.render_guild_rls_ddl`` ahead of the policies that call them,
#: in this order: the SQL bodies are checked at creation, and each names only
#: tables and the ``public`` functions above.
GUILD_AUTHORIZATION_FUNCTIONS: tuple[tuple[str, str], ...] = (
    ("initiative_access", INITIATIVE_ACCESS),
    ("initiative_full_access", INITIATIVE_FULL_ACCESS),
    ("initiative_role_permits", INITIATIVE_ROLE_PERMITS),
    ("resource_access", RESOURCE_ACCESS),
)

#: Argument types of every function that lives in a guild schema — the four
#: above plus the three ``frozen`` and ``initiative_rls`` render there. What
#: ``DROP FUNCTION`` and ``pg_get_functiondef`` need to name one.
GUILD_FUNCTION_SIGNATURES: dict[str, str] = {
    "initiative_access": "(integer, integer, boolean)",
    "initiative_full_access": "(integer, boolean)",
    "initiative_role_permits": "(integer, integer, text, boolean)",
    "resource_access": "(text, integer, integer, integer, boolean)",
    "resource_frozen": "(text, bigint, boolean)",
    "resource_frozen_for_grant": "(text, bigint, boolean)",
    "entity_access": "(text, integer, boolean, boolean)",
}

#: Functions an earlier render put in a guild schema under a name or
#: signature this one no longer produces. The RLS render drops them last,
#: the template strip drops them with the rest, and the boot step that
#: retires ``public`` copies tries these names too.
RETIRED_GUILD_FUNCTION_SIGNATURES: dict[str, str] = {
    "relationship_endpoint_access": "(text, integer, boolean)",
}


def render_guild_authorization_functions() -> str:
    """The four guild functions as schema-relative DDL, for the RLS render.

    Each text is one statement; the render is a script, so each is
    terminated here.
    """
    return "\n".join(sql.rstrip() + ";" for _name, sql in GUILD_AUTHORIZATION_FUNCTIONS)


def authorization_functions_digest() -> str:
    """A stable hash of every definition here.

    For a caller that wants to know whether this file changed without diffing
    five function bodies — the same idea as the provisioning stamp, which
    hashes what it renders rather than tracking a version by hand.
    """
    digest = hashlib.sha256()
    for name, sql in AUTHORIZATION_FUNCTIONS + GUILD_AUTHORIZATION_FUNCTIONS:
        digest.update(name.encode())
        digest.update(sql.encode())
    return digest.hexdigest()[:16]


async def apply_authorization_functions(conn: "AsyncConnection") -> None:
    """Create or replace every function in :data:`AUTHORIZATION_FUNCTIONS`.

    Idempotent, and cheap enough to run unconditionally on boot: six
    ``CREATE OR REPLACE`` statements against ``public``. ``CREATE OR REPLACE``
    keeps each function's OID, so the policies that reference it are untouched
    and no guild schema needs re-rendering.

    Runs on the provisioning engine, which owns these objects.
    """
    from sqlalchemy import text

    for _name, sql in AUTHORIZATION_FUNCTIONS:
        await conn.execute(text(sql))


async def ensure_authorization_functions() -> None:
    """Apply the functions on boot, over the provisioning engine.

    Called after the migrations and before the guild back-fill, so a schema
    rendered in the same boot finds every ``public`` function its own copies
    call. Six ``CREATE OR REPLACE`` statements on a healthy database — the
    same unconditional-and-cheap shape as the grant heals either side of it.
    """
    from app.db import session as db_session

    async with db_session.provisioning_engine.begin() as conn:
        await apply_authorization_functions(conn)


@dataclass
class DropReport:
    """What :func:`drop_public_copies` did with each of the seven."""

    dropped: list[str] = field(default_factory=list)
    absent: list[str] = field(default_factory=list)
    #: name -> how many policies or triggers still bind the ``public`` copy
    blocked: dict[str, int] = field(default_factory=dict)


_DEPENDENTS_SQL = """
SELECT count(*) FROM pg_depend d
WHERE d.refclassid = 'pg_proc'::regclass
  AND d.refobjid = CAST(:sig AS regprocedure)
  AND d.deptype = 'n'
"""


async def drop_public_copies(engine: "AsyncEngine") -> DropReport:
    """Retire the ``public`` copies of the seven guild functions.

    Runs after the guild back-fill. Each drop is its own transaction: a copy
    still bound by a policy or trigger in a schema the back-fill has not
    re-rendered is refused by Postgres, recorded with its dependent count, and
    left for the next boot; the others are dropped. A copy that is already
    gone is reported as absent. Nothing here touches a guild schema.
    """
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError

    from app.db.errors import dbapi_sqlstate

    report = DropReport()
    for name, args in {
        **GUILD_FUNCTION_SIGNATURES,
        **RETIRED_GUILD_FUNCTION_SIGNATURES,
    }.items():
        sig = f"public.{name}{args}"
        async with engine.connect() as conn:
            exists = (
                await conn.execute(
                    text("SELECT to_regprocedure(CAST(:sig AS text)) IS NOT NULL"),
                    {"sig": sig},
                )
            ).scalar()
        if not exists:
            report.absent.append(name)
            continue
        try:
            async with engine.begin() as conn:
                await conn.execute(text(f"DROP FUNCTION {sig}"))
        except DBAPIError as exc:
            if dbapi_sqlstate(exc) != DEPENDENT_OBJECTS_STILL_EXIST_SQLSTATE:
                raise
            async with engine.connect() as conn:
                count = (
                    await conn.execute(text(_DEPENDENTS_SQL), {"sig": sig})
                ).scalar()
            report.blocked[name] = int(count or 0)
            continue
        report.dropped.append(name)
    return report


async def ensure_public_copies_dropped() -> DropReport:
    """The boot step, over the provisioning engine (the copies' owner)."""
    from app.db import session as db_session

    return await drop_public_copies(db_session.provisioning_engine)
