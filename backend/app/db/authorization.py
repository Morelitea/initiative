"""The authorization functions the guild policies defer to.

Every initiative-scoped table in every ``guild_<id>`` schema carries policies
that call into one of these. They live in ``public`` and name guild tables
**unqualified**, so one definition serves every guild: the routed
``search_path`` is what binds ``initiative_members`` to the caller's own schema
(see ``search_path_pinning_test``). Each runs as its caller.

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
before it serves rather than at its next restart — the migration should
``op.execute`` the constant from this module, never a copy of it.

The bodies name guild-local tables that are not on the ``search_path`` at
creation time, so applying them needs ``check_function_bodies = false``. That
is a statement about when names are resolved, not a relaxation of anything:
resolution happens per call, against the caller's route.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.ext.asyncio import AsyncConnection

__all__ = [
    "AUTHORIZATION_FUNCTIONS",
    "GUILD_SUPERADMIN",
    "apply_authorization_functions",
    "authorization_functions_digest",
    "ensure_authorization_functions",
]

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
        OR NOT EXISTS (
            SELECT 1 FROM public.guild_auth_policies p
            WHERE p.guild_id = NULLIF(
                    current_setting('app.current_guild_id', true), ''
                  )::int
              AND p.policy <> 'open'
              AND (
                  -- The provider this guild names, if it names one.
                  (
                      p.provider_id IS NOT NULL
                      AND NOT COALESCE(
                            p.provider_id = ANY(
                                string_to_array(
                                    NULLIF(
                                        current_setting(
                                            'app.satisfied_providers', true
                                        ), ''
                                    ),
                                    ','
                                )::int[]
                            ),
                            false
                          )
                  )
                  -- Or the account's own second factor, where the community
                  -- asks for one. The session records it when a code is
                  -- presented and the request carries that here.
                  OR (
                      'totp' = ANY(p.require_methods)
                      AND COALESCE(
                            current_setting('app.session_mfa', true), 'false'
                          ) <> 'true'
                  )
                  -- Or its own single sign-on, whichever of its providers
                  -- served it. The session records each community whose sign-in
                  -- it completed, so this is answered without reading the
                  -- provider registry. Named rather than counted, so a list
                  -- holding some other method is not read as this one.
                  OR (
                      'sso' = ANY(p.require_methods)
                      AND NOT COALESCE(
                            p.guild_id = ANY(
                                string_to_array(
                                    NULLIF(
                                        current_setting('app.sso_guilds', true), ''
                                    ),
                                    ','
                                )::int[]
                            ),
                            false
                          )
                  )
              )
        )
$function$

"""

#: Gate 2: the hard isolation boundary. Every initiative-scoped table's
#: policies defer to this one function.
INITIATIVE_ACCESS = """\
CREATE OR REPLACE FUNCTION public.initiative_access(p_initiative_id integer, p_user_id integer, p_need_write boolean DEFAULT false)
 RETURNS boolean
 LANGUAGE sql
 STABLE
AS $function$
    SELECT
        public.guild_auth_satisfied()
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
            OR current_setting('app.current_guild_role'::text, true) = 'admin'::text
            OR (CASE
                  WHEN p_need_write
                    THEN current_setting('app.pam_write'::text, true) = 'true'::text
                  ELSE current_setting('app.pam_read'::text, true) = 'true'::text
                       OR current_setting('app.pam_write'::text, true) = 'true'::text
                END)
            OR EXISTS (
                SELECT 1 FROM initiative_members im
                WHERE im.initiative_id = p_initiative_id
                  AND im.user_id = p_user_id
            )
        )
$function$

"""

#: Gate 2, narrowed: full standing in the initiative rather than membership.
INITIATIVE_FULL_ACCESS = """\
CREATE OR REPLACE FUNCTION public.initiative_full_access(p_initiative_id integer, p_need_write boolean DEFAULT false)
 RETURNS boolean
 LANGUAGE sql
 STABLE
AS $function$
    SELECT
        public.guild_auth_satisfied()
        AND (
            current_setting('app.current_guild_role'::text, true) = 'admin'::text
            OR (CASE
                  WHEN p_need_write
                    THEN current_setting('app.pam_write'::text, true) = 'true'::text
                  ELSE current_setting('app.pam_read'::text, true) = 'true'::text
                       OR current_setting('app.pam_write'::text, true) = 'true'::text
                END)
            OR p_initiative_id = ANY(
                string_to_array(
                    NULLIF(current_setting('app.override_initiatives'::text, true), ''),
                    ','
                )::integer[]
            )
        )
$function$

"""

#: Gate 3: what a member's role in the initiative permits.
INITIATIVE_ROLE_PERMITS = """\
CREATE OR REPLACE FUNCTION public.initiative_role_permits(p_initiative_id integer, p_user_id integer, p_key text, p_default boolean)
 RETURNS boolean
 LANGUAGE sql
 STABLE
AS $function$
    SELECT
        -- A row belonging to no initiative has no initiative role to answer to.
        p_initiative_id IS NULL
        OR current_setting('app.current_guild_role'::text, true) = 'admin'::text
        OR current_setting('app.pam_read'::text, true) = 'true'::text
        OR current_setting('app.pam_write'::text, true) = 'true'::text
        OR COALESCE(
             (SELECT CASE
                       -- A manager role holds every key, stored or not.
                       WHEN r.is_manager THEN true
                       ELSE COALESCE(rp.enabled, p_default)
                     END
                FROM initiative_members im
                JOIN initiative_roles r ON r.id = im.role_id
                LEFT JOIN initiative_role_permissions rp
                       ON rp.initiative_role_id = r.id
                      AND rp.permission_key = p_key
               WHERE im.initiative_id = p_initiative_id
                 AND im.user_id = p_user_id),
             -- No membership at all: gate 2 has already refused, and the
             -- application's resolver answers false for the same case.
             false)
$function$

"""

#: Gate 4: per-resource sharing (the ``resource_grants`` table).
RESOURCE_ACCESS = """\
CREATE OR REPLACE FUNCTION public.resource_access(p_tool text, p_resource_id integer, p_user_id integer, p_initiative_id integer DEFAULT NULL::integer, p_need_write boolean DEFAULT false)
 RETURNS boolean
 LANGUAGE sql
 STABLE
AS $function$
    SELECT
        -- Rows that carry no sharing identity (guild vocabulary) have nothing
        -- for this to decide.
        p_tool IS NULL
        OR current_setting('app.current_guild_role'::text, true) = 'admin'::text
        OR (CASE
              WHEN p_need_write
                THEN current_setting('app.pam_write'::text, true) = 'true'::text
              ELSE current_setting('app.pam_read'::text, true) = 'true'::text
                   OR current_setting('app.pam_write'::text, true) = 'true'::text
            END)
        -- Initiatives where the request holds "Full access".
        OR p_initiative_id = ANY (
               string_to_array(
                   NULLIF(current_setting('app.override_initiatives'::text, true), ''),
                   ','
               )::integer[]
           )
        OR EXISTS (
            SELECT 1 FROM resource_grants g
            WHERE g.resource_type = p_tool
              AND g.resource_id = p_resource_id
              AND (NOT p_need_write OR g.level IN ('write', 'owner'))
              AND (
                   g.user_id = p_user_id
                OR g.role_id IN (
                       SELECT im.role_id FROM initiative_members im
                       WHERE im.user_id = p_user_id
                   )
                OR (g.all_initiative_members
                    AND (g.initiative_id IS NULL
                         OR g.initiative_id IN (
                                SELECT im.initiative_id FROM initiative_members im
                                WHERE im.user_id = p_user_id
                            )))
                OR (NOT p_need_write
                    AND g.dashboard_id IS NOT NULL
                    AND g.dashboard_id = NULLIF(current_setting('app.via_dashboard_id'::text, true), '')::int)
              )
        )
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
#: A live settings grant at ``superadmin`` answers it too, for its window —
#: which is what lets somebody sent to help with billing or moderation settings
#: reach the surfaces that hold them, without reaching any content.
#:
#: The one definition of the rule. The policies on ``guild_auth_policies`` call
#: it, and so does the app — ``func.guild_superadmin(...)`` where an endpoint
#: has to decide before it writes, the way ``initiative_scope_clause`` already
#: defers to ``initiative_access`` rather than restating it in Python.
GUILD_SUPERADMIN = """\
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
          AND m.role = 'superadmin'
    )
    -- Or a live settings grant at the same rung. A grantee is not a member and
    -- never will be, so the seat they hold for the grant's window is recorded
    -- here rather than in the roster. Read through the caller's own-row policy
    -- on ``access_grants``, which is the only row this is ever asked about.
    OR EXISTS (
        SELECT 1
        FROM public.access_grants g
        WHERE g.guild_id = p_guild_id
          AND g.user_id = p_user_id
          AND g.purpose = 'settings'
          AND g.access_level = 'superadmin'
          AND g.status = 'approved'
          AND g.expires_at > now()
    )
$function$

"""


#: Name -> definition, in dependency order: ``initiative_access`` and
#: ``initiative_full_access`` call ``guild_auth_satisfied``, so it is created
#: first. Applied in this order, a fresh database never sees a dangling call.
AUTHORIZATION_FUNCTIONS: tuple[tuple[str, str], ...] = (
    ("guild_auth_satisfied", GUILD_AUTH_SATISFIED),
    ("initiative_access", INITIATIVE_ACCESS),
    ("initiative_full_access", INITIATIVE_FULL_ACCESS),
    ("initiative_role_permits", INITIATIVE_ROLE_PERMITS),
    ("resource_access", RESOURCE_ACCESS),
    ("guild_superadmin", GUILD_SUPERADMIN),
)


def authorization_functions_digest() -> str:
    """A stable hash of every definition here.

    For a caller that wants to know whether this file changed without diffing
    five function bodies — the same idea as the provisioning stamp, which
    hashes what it renders rather than tracking a version by hand.
    """
    digest = hashlib.sha256()
    for name, sql in AUTHORIZATION_FUNCTIONS:
        digest.update(name.encode())
        digest.update(sql.encode())
    return digest.hexdigest()[:16]


async def apply_authorization_functions(conn: "AsyncConnection") -> None:
    """Create or replace every function in :data:`AUTHORIZATION_FUNCTIONS`.

    Idempotent, and cheap enough to run unconditionally on boot: five
    ``CREATE OR REPLACE`` statements against ``public``. ``CREATE OR REPLACE``
    keeps each function's OID, so the policies that reference it are untouched
    and no guild schema needs re-rendering.

    Runs on the provisioning engine, which owns these objects.
    """
    from sqlalchemy import text

    # The bodies name guild-local tables, which are not on the path here.
    await conn.execute(text("SET LOCAL check_function_bodies = false"))
    for _name, sql in AUTHORIZATION_FUNCTIONS:
        await conn.execute(text(sql))


async def ensure_authorization_functions() -> None:
    """Apply the functions on boot, over the provisioning engine.

    Called after the migrations and before the guild back-fill, so a schema
    rendered in the same boot finds every function its policies name. Five
    ``CREATE OR REPLACE`` statements on a healthy database — the same
    unconditional-and-cheap shape as the grant heals either side of it.
    """
    from app.db import session as db_session

    async with db_session.provisioning_engine.begin() as conn:
        await apply_authorization_functions(conn)
