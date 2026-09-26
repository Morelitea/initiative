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
from app.core.app_scopes import AppScopeResource, tool_resource
from app.core.tools import Tool
from app.models.platform.access_grant import AccessGrantPurpose, SettingsLevel
from app.models.platform.guild import GuildRole
from app.models.platform.user import UserRole
from app.models.tenant.initiative import DEFAULT_PERMISSION_VALUES, PermissionKey
from app.models.tenant.resource_grant import (
    RESOURCE_LEVEL_LADDER,
    WRITE_LEVELS,
    ResourceAccessLevel,
)

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
    "CURRENT_STANDING",
    "GUILD_AUTHORIZATION_FUNCTIONS",
    "IN_BODY",
    "IN_POLICY",
    "Legs",
    "STANDING",
    "STANDING_FIELDS",
    "GUILD_FUNCTION_SIGNATURES",
    "RETIRED_GUILD_FUNCTION_SIGNATURES",
    "GUILD_SUPERADMIN",
    "DropReport",
    "app_narrowed",
    "app_refused",
    "app_scope",
    "apply_authorization_functions",
    "authorization_functions_digest",
    "drop_public_copies",
    "ensure_authorization_functions",
    "ensure_public_copies_dropped",
    "render_guild_authorization_functions",
    "in_body",
    "standing_arg",
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


#: The community this request is in, however it was reached: as a member, on a
#: content grant, or on a settings grant. The gate asks its question of that
#: community, so the rule binds a grantee as it binds a member.
_ROUTED_GUILD_ID = """COALESCE(
                    NULLIF(current_setting('app.current_guild_id', true), ''),
                    NULLIF(current_setting('app.pam_guild_id', true), ''),
                    NULLIF(current_setting('app.settings_guild_id', true), '')
                  )::int"""

#: Gate 0: the guild's sign-in policy, satisfied by this session.
GUILD_AUTH_SATISFIED = f"""\
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
            WHERE p.guild_id = {_ROUTED_GUILD_ID}
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
            WHERE g.id = {_ROUTED_GUILD_ID}
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

#: This request holds the community's seat: the membership row's superadmin,
#: or a live superadmin settings grant, as the standing statement read it
#: through ``guild_superadmin()``.
GUILD_SEAT = (
    f"({STANDING_IS_THIS_GUILD}"
    " AND current_setting('app.guild_seat'::text, true) = 'true'::text)"
)

#: A live grant covers this request, at whichever level the command asks for.
#: A live content grant, read one level at a time: the level a grant confers
#: is the one its standing value names.
PAM_READ = "current_setting('app.pam_read'::text, true) = 'true'::text"
PAM_WRITE = "current_setting('app.pam_write'::text, true) = 'true'::text"
PAM_AT_LEVEL = (
    f"(CASE WHEN p_need_write THEN {PAM_WRITE} ELSE {PAM_READ} OR {PAM_WRITE} END)"
)

#: A live grant at either level, where the question is what the community has
#: switched on rather than what one person may reach.
PAM_ANY = f"{PAM_READ} OR {PAM_WRITE}"


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


# --- The standing, read once per statement ----------------------------------
#
# The legs above read settings, and a gate asked once per row reads them once
# per row: the system leg's catalog lookup, and each comma list parsed into an
# array again. None of it depends on the row. ``current_standing()`` reads all
# of it once and returns it as one value of type ``public.standing``. A policy
# hands that value to each gate as a sub-select naming no row, which the
# planner evaluates once for the statement, and a gate reads its fields. The
# type is shared; the function is rendered into each guild schema with the
# gates, so a schema's policies still call only that schema's functions.

#: ``public.standing``'s attributes, in order: the name a gate reads, its type,
#: and the leg it is read from. The type is created by a migration, and
#: ``authorization_test`` holds the live type to this list.
STANDING_FIELDS: tuple[tuple[str, str, str], ...] = (
    ("system_session", "boolean", SYSTEM_SESSION),
    ("this_guild", "boolean", STANDING_IS_THIS_GUILD),
    ("guild_admin", "boolean", GUILD_ADMIN),
    (
        "guild_auth_ok",
        "boolean",
        "current_setting('app.guild_auth_ok'::text, true) = 'true'::text",
    ),
    (
        "scope_initiative_id",
        "integer",
        "NULLIF(current_setting('app.scope_initiative_id'::text, true), ''::text)::integer",
    ),
    ("pam_read", "boolean", PAM_READ),
    ("pam_write", "boolean", PAM_WRITE),
    ("member_initiatives", "integer[]", standing_ids("app.member_initiatives")),
    ("manager_initiatives", "integer[]", standing_ids("app.manager_initiatives")),
    ("override_initiatives", "integer[]", standing_ids("app.override_initiatives")),
    ("member_role_ids", "integer[]", standing_ids("app.member_role_ids")),
    ("role_grants", "text[]", standing_pairs("app.role_grants")),
    ("role_denies", "text[]", standing_pairs("app.role_denies")),
    ("enabled_tools", "text[]", standing_pairs("app.enabled_tools")),
    (
        "via_dashboard_id",
        "integer",
        "NULLIF(current_setting('app.via_dashboard_id'::text, true), ''::text)::integer",
    ),
    # An installed app acting in the community: which install, and the
    # resources its scopes let it read and write. Unset on every request a
    # person makes.
    (
        "install_id",
        "integer",
        "NULLIF(current_setting('app.current_install_id'::text, true), ''::text)::integer",
    ),
    ("install_read", "text[]", standing_pairs("app.install_read")),
    ("install_write", "text[]", standing_pairs("app.install_write")),
    # The community's content is on hold (``read_only``) for this reader: no
    # change to any of it, whatever their rung. A grant is not held.
    (
        "content_hold",
        "boolean",
        "current_setting('app.content_hold'::text, true) = 'true'::text",
    ),
)
_STANDING_NAMES = frozenset(name for name, _type, _expr in STANDING_FIELDS)

#: What a policy passes a gate: this statement's standing. A sub-select that
#: names no row, so the planner evaluates it once per statement.
STANDING = "(SELECT current_standing())"

_STANDING_ROW = ",\n        ".join(expr for _name, _type, expr in STANDING_FIELDS)

#: The standing, read once. ``plpgsql`` like the gates, so its plan is kept.
CURRENT_STANDING = f"""\
CREATE OR REPLACE FUNCTION current_standing()
 RETURNS standing
 LANGUAGE plpgsql
 STABLE
AS $function$
BEGIN
    RETURN ROW(
        {_STANDING_ROW}
    )::public.standing;
END
$function$

"""


_STANDING_EXPRS = {name: expr for name, _type, expr in STANDING_FIELDS}
_STANDING_TYPES = {name: sqltype for name, sqltype, _expr in STANDING_FIELDS}


@dataclass(frozen=True)
class Legs:
    """Every leg, read off a standing. Two readings of the same fields: a gate
    reads its parameter; a policy reads each field as a sub-select naming no
    row, evaluated once for the statement, and computes only that field."""

    standing: str
    #: Inside a policy, a field is its own once-per-statement sub-select
    #: rather than a field of the whole standing, which would compute every
    #: other field alongside it.
    per_field: bool = False

    def field(self, name: str) -> str:
        if name not in _STANDING_NAMES:
            raise ValueError(f"public.standing has no attribute {name!r}")
        if self.per_field:
            # Cast to the field's type: ``x = ANY ((SELECT a))`` would otherwise
            # read as a comparison against a sub-query's rows, not an array.
            return f"((SELECT {_STANDING_EXPRS[name]})::{_STANDING_TYPES[name]})"
        return f"({self.standing}).{name}"

    @property
    def system(self) -> str:
        return self.field("system_session")

    @property
    def this_guild(self) -> str:
        return self.field("this_guild")

    @property
    def admin(self) -> str:
        return self.field("guild_admin")

    @property
    def auth_ok(self) -> str:
        return self.field("guild_auth_ok")

    @property
    def scope(self) -> str:
        return self.field("scope_initiative_id")

    @property
    def pam_read(self) -> str:
        return self.field("pam_read")

    @property
    def pam_write(self) -> str:
        return self.field("pam_write")

    @property
    def install_id(self) -> str:
        return self.field("install_id")

    @property
    def content_hold(self) -> str:
        return self.field("content_hold")

    @property
    def pam_any(self) -> str:
        return f"({self.pam_read} OR {self.pam_write})"

    def pam_at_level(self, need_write: str) -> str:
        return (
            f"(CASE WHEN {need_write} THEN {self.pam_write}"
            f" ELSE {self.pam_read} OR {self.pam_write} END)"
        )


def standing_arg():
    """This statement's standing, for an app query that asks a gate directly.

    The same once-per-statement sub-select a policy passes, as a SQLAlchemy
    expression.
    """
    from sqlalchemy import func, select

    return select(func.current_standing()).scalar_subquery()


#: Inside a gate's body, the standing is its last parameter.
IN_BODY = Legs("p_st")
#: Inside a policy, the standing is this statement's.
IN_POLICY = Legs(STANDING, per_field=True)


# --- An installed app's scopes ----------------------------------------------
#
# A person's request carries no install, so each of these answers for it with
# its first comparison. Every field is read off the standing, once per
# statement: a sub-select naming no row in a policy, a field of the parameter
# in a gate.


def app_scope(resource: str, write: bool, legs: Legs) -> str:
    """An installed app holds ``resource``'s read scope, or its write scope
    when ``write``. ``resource`` is an ``AppScopeResource`` value."""
    name = AppScopeResource(getattr(resource, "value", resource)).value
    held = legs.field("install_write" if write else "install_read")
    return f"({legs.install_id} IS NULL OR '{name}' = ANY ({held}))"


def app_narrowed(initiative_expr: str, legs: Legs) -> str:
    """A token narrowed to one initiative reaches rows that belong to an
    initiative, and none that belong to the community as a whole.
    ``initiative_access`` already keeps it to the one it names."""
    return (
        f"({legs.install_id} IS NULL OR {legs.scope} IS NULL"
        f" OR {initiative_expr} IS NOT NULL)"
    )


def app_refused(legs: Legs) -> str:
    """No installed app reaches the row."""
    return f"({legs.install_id} IS NULL)"


def in_body(sql: str) -> str:
    """A policy predicate, read inside a gate's body instead.

    ``entity_access`` answers each kind with the predicate that kind's own
    policy renders, and inside the function the standing is its parameter: the
    statement's standing becomes ``p_st``, and each field a policy reads on its
    own becomes a field of ``p_st``. The longest field text first, so one that
    contains another is replaced whole.
    """
    swaps = sorted(
        ((IN_POLICY.field(name), IN_BODY.field(name)) for name in _STANDING_NAMES),
        key=lambda pair: -len(pair[0]),
    )
    for policy_text, body_text in swaps:
        sql = sql.replace(policy_text, body_text)
    return sql.replace(STANDING, IN_BODY.standing)


_B = IN_BODY


#: Gate 2: the hard isolation boundary. Every initiative-scoped table's
#: policies defer to this one function.
INITIATIVE_ACCESS = f"""\
CREATE OR REPLACE FUNCTION initiative_access(p_initiative_id integer, p_user_id integer, p_need_write boolean, p_st standing)
 RETURNS boolean
 LANGUAGE plpgsql
 STABLE
AS $function$
BEGIN
    RETURN
        {_B.auth_ok}
        AND (
            -- The read's own scope, when the surface asking has one. A row of
            -- another initiative is not the answer to the question, whatever
            -- else the context allows. Guild-level rows belong to no
            -- initiative and stay in scope.
            p_initiative_id IS NULL
            OR {_B.scope} IS NULL
            OR p_initiative_id = {_B.scope}
        )
        AND (
            -- Guild-level scope: the row belongs to no initiative, so the
            -- initiative gate has nothing to decide. The schema boundary still
            -- confines it to this guild; grants decide who may read or write it.
            p_initiative_id IS NULL
            OR {_B.system}
            OR {_B.admin}
            OR {_B.pam_at_level("p_need_write")}
            OR ({_B.this_guild}
                AND p_initiative_id = ANY ({_B.field("member_initiatives")}))
        )
    ;
END
$function$

"""

#: Gate 2, narrowed: full standing in the initiative rather than membership.
INITIATIVE_FULL_ACCESS = f"""\
CREATE OR REPLACE FUNCTION initiative_full_access(p_initiative_id integer, p_need_write boolean, p_st standing)
 RETURNS boolean
 LANGUAGE plpgsql
 STABLE
AS $function$
BEGIN
    RETURN
        {_B.auth_ok}
        AND (
            {_B.system}
            OR {_B.admin}
            OR {_B.pam_at_level("p_need_write")}
            OR ({_B.this_guild}
                AND p_initiative_id = ANY ({_B.field("override_initiatives")}))
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
CREATE OR REPLACE FUNCTION initiative_role_permits(p_initiative_id integer, p_user_id integer, p_key text, p_default boolean, p_st standing)
 RETURNS boolean
 LANGUAGE plpgsql
 STABLE
AS $function$
BEGIN
    RETURN
        -- A row belonging to no initiative has no initiative role to answer to.
        p_initiative_id IS NULL
        OR {_B.system}
        OR {_B.admin}
        OR {_B.pam_any}
        OR ({_B.this_guild} AND (
                p_initiative_id = ANY ({_B.field("manager_initiatives")})
             OR (p_initiative_id::text || ':' || p_key)
                    = ANY ({_B.field("role_grants")})
             OR (
                 p_default
                 AND p_initiative_id = ANY ({_B.field("member_initiatives")})
                 AND NOT ((p_initiative_id::text || ':' || p_key)
                              = ANY ({_B.field("role_denies")}))
             )
        ))
    ;
END
$function$

"""

#: Gate 4: per-resource sharing (the ``resource_grants`` table).
#:
#: Two functions answer it, from one spelling of every leg. ``resource_level``
#: says which rung of the sharing ladder the request holds on a row — what a
#: serializer reports and a route compares against. ``resource_access`` says
#: whether it holds the rung a command needs — what every content policy asks,
#: once per row, and so kept to an existence test rather than a reduction over
#: the matched grants. ``resource_level_test`` holds the two to each other.
#:
#: The one gate that still probes a table, because which readers a resource was
#: shared with is genuinely per resource. What the standing removes is the two
#: reader sub-selects inside it: the roles they hold and the initiatives they
#: are in are the same for every row.

#: The legs that answer the whole question before sharing is consulted. A row
#: that carries no sharing identity (guild vocabulary) has nothing to decide;
#: the system engine, the community's admin and a reader holding "Full access"
#: in the row's initiative reach it whatever its grants say.
FULL_ACCESS = f"""\
p_tool IS NULL
        OR {_B.system}
        OR {_B.admin}
        OR ({_B.this_guild}
            AND p_initiative_id = ANY ({_B.field("override_initiatives")}))"""

#: The grant rows on ``(p_tool, p_resource_id)`` that reach this reader: one
#: naming them, one on an initiative role they hold, one shared with every
#: member of an initiative they are in (or of the community, on a row that
#: belongs to no initiative), the dashboard a published view is read through,
#: or one naming the installed app the request is for. Written over the row
#: alias ``g``.
GRANT_REACHES_READER = f"""\
g.resource_type = p_tool
              AND g.resource_id = p_resource_id
              AND (
                   g.user_id = p_user_id
                OR ({_B.this_guild}
                    AND g.role_id = ANY ({_B.field("member_role_ids")}))
                OR (g.all_initiative_members
                    AND {_B.this_guild}
                    AND (g.initiative_id IS NULL
                         OR g.initiative_id = ANY ({_B.field("member_initiatives")})))
                OR (g.dashboard_id IS NOT NULL
                    AND g.dashboard_id = {_B.field("via_dashboard_id")})
                OR (g.app_install_id IS NOT NULL
                    AND g.app_install_id = {_B.install_id})
              )"""


def _highest_rung_case() -> str:
    """The highest rung among the matched grant rows, spelled from the ladder:
    one arm per rung above the lowest, and the lowest for any match at all."""
    lowest, *higher = RESOURCE_LEVEL_LADDER
    arms = [
        f"WHEN bool_or(g.level = '{level.value}') THEN '{level.value}'"
        for level in reversed(higher)
    ]
    arms.append(f"WHEN count(*) > 0 THEN '{lowest.value}'")
    return "\n             ".join(arms)


#: The rung the request holds on one row, or NULL for none. A content grant
#: lends its own rung beside whatever the grant rows give, and never owner.
RESOURCE_LEVEL = f"""\
CREATE OR REPLACE FUNCTION resource_level(p_tool text, p_resource_id integer, p_user_id integer, p_initiative_id integer, p_st standing)
 RETURNS text
 LANGUAGE plpgsql
 STABLE
AS $function$
DECLARE
    v_level text;
BEGIN
    IF {FULL_ACCESS}
    THEN
        RETURN '{ResourceAccessLevel.owner.value}';
    END IF;
    SELECT CASE
             {_highest_rung_case()}
           END
      INTO v_level
      FROM resource_grants g
     WHERE {GRANT_REACHES_READER};
    IF {_B.pam_write}
       AND v_level IS DISTINCT FROM '{ResourceAccessLevel.owner.value}' THEN
        RETURN '{ResourceAccessLevel.write.value}';
    END IF;
    IF {_B.pam_read} AND v_level IS NULL THEN
        RETURN '{ResourceAccessLevel.read.value}';
    END IF;
    RETURN v_level;
END
$function$

"""

#: Whether the request holds the rung a command needs on one row. A dashboard's
#: grant is ``read`` by constraint, so the level filter answers the write
#: question for it too.
RESOURCE_ACCESS = f"""\
CREATE OR REPLACE FUNCTION resource_access(p_tool text, p_resource_id integer, p_user_id integer, p_initiative_id integer, p_need_write boolean, p_st standing)
 RETURNS boolean
 LANGUAGE plpgsql
 STABLE
AS $function$
BEGIN
    RETURN
        {FULL_ACCESS}
        OR {_B.pam_at_level("p_need_write")}
        OR EXISTS (
            SELECT 1 FROM resource_grants g
            WHERE {GRANT_REACHES_READER}
              AND (NOT p_need_write OR g.level IN ({sql_values(level.value for level in WRITE_LEVELS)}))
        )
    ;
END
$function$

"""

_WRITE_RUNGS = sql_values(level.value for level in WRITE_LEVELS)
_OWNER = ResourceAccessLevel.owner.value

#: Whether a change may be made to a row the request holds ``v_level`` on:
#: the row is live (neither archived nor in the trash — a tool's row carries
#: its initiative's state, which both lifecycles cascade onto it) and the
#: community's content is not on hold.
_MAY_CHANGE = f"""(p_archived_at IS NULL AND p_deleted_at IS NULL
        AND NOT {_B.content_hold})"""

#: What changing who a resource is shared with asks beyond its being live: the
#: owner's rung, held by the request itself rather than lent by a content
#: grant, and — for an installed app — ``sharing:write`` beside the tool's own
#: write scope.
_SHARES = f"""(v_level = '{_OWNER}'
        AND NOT {_B.pam_any}
        AND ({_B.install_id} IS NULL
             OR ('{AppScopeResource.sharing.value}' = ANY ({_B.field("install_write")})
                 AND COALESCE((CASE p_tool
                   {" ".join(f"WHEN '{t.value}' THEN '{tool_resource(t).value}'" for t in Tool)}
                   END) = ANY ({_B.field("install_write")}), false))))"""

#: What the request may do to one of a tool's rows, beyond reading it: the
#: row's ``can``, and the check each route that does the thing makes. One
#: function, so the flag a client reads and the refusal a route gives are one
#: answer.
#:
#: - ``edit``: write or owner, on a live row.
#: - ``delete``, ``share``, ``configure``: the owner's, on a live row; sharing
#:   is never lent by a content grant, and configuring a project is also its
#:   initiative's managers'.
#: - ``export``: the owner's, archived or not — an export changes nothing.
#: - ``unarchive``: write on a row archived on its own occasion; one archived
#:   along with its initiative comes back with it.
RESOURCE_ACTIONS = f"""\
CREATE OR REPLACE FUNCTION resource_actions(p_tool text, p_resource_id integer, p_user_id integer, p_initiative_id integer, p_archived_at timestamptz, p_deleted_at timestamptz, p_st standing)
 RETURNS text[]
 LANGUAGE plpgsql
 STABLE
AS $function$
DECLARE
    v_level text := resource_level(p_tool, p_resource_id, p_user_id, p_initiative_id, p_st);
    v_actions text[] := ARRAY[]::text[];
BEGIN
    IF v_level IS NULL THEN
        RETURN v_actions;
    END IF;
    IF v_level = '{_OWNER}' THEN
        v_actions := v_actions || 'export'::text;
    END IF;
    IF {_MAY_CHANGE} THEN
        IF v_level IN ({_WRITE_RUNGS}) THEN
            v_actions := v_actions || 'edit'::text;
        END IF;
        IF v_level = '{_OWNER}' THEN
            v_actions := v_actions || 'delete'::text;
        END IF;
        IF {_SHARES} THEN
            v_actions := v_actions || 'share'::text;
        END IF;
        IF v_level = '{_OWNER}'
           OR ({_B.this_guild}
               AND p_initiative_id = ANY ({_B.field("manager_initiatives")})) THEN
            v_actions := v_actions || 'configure'::text;
        END IF;
    ELSIF p_archived_at IS NOT NULL
          AND NOT {_B.content_hold}
          AND v_level IN ({_WRITE_RUNGS})
          AND (p_initiative_id IS NULL
               OR NOT resource_frozen('initiatives', p_initiative_id)) THEN
        v_actions := v_actions || 'unarchive'::text;
    END IF;
    RETURN v_actions;
END
$function$

"""

#: Whether the request may change who one resource is shared with — the
#: ``share`` of :data:`RESOURCE_ACTIONS`, asked by the policies on
#: ``resource_grants``. Whether the resource is live is the freeze's to say
#: there (``app.db.frozen``), so this asks only the rest.
RESOURCE_SHARES = f"""\
CREATE OR REPLACE FUNCTION resource_shares(p_tool text, p_resource_id integer, p_user_id integer, p_initiative_id integer, p_st standing)
 RETURNS boolean
 LANGUAGE plpgsql
 STABLE
AS $function$
DECLARE
    v_level text := resource_level(p_tool, p_resource_id, p_user_id, p_initiative_id, p_st);
BEGIN
    RETURN NOT {_B.content_hold} AND {_SHARES};
END
$function$

"""


def _author_arms() -> str:
    return "\n".join(
        f"      WHEN '{tool.value}' THEN\n"
        f"        SELECT created_by INTO v_author FROM {tool.plural} WHERE id = p_resource_id;"
        for tool in Tool
    )


#: Whether ``p_user_id`` wrote a resource that nobody owns — the one owner row
#: anybody but its sharer may write: handing unowned content back to its
#: author.
RESOURCE_RECLAIMABLE = f"""\
CREATE OR REPLACE FUNCTION resource_reclaimable(p_tool text, p_resource_id integer, p_user_id integer)
 RETURNS boolean
 LANGUAGE plpgsql
 STABLE
AS $function$
DECLARE
    v_author integer;
BEGIN
    CASE p_tool
{_author_arms()}
      ELSE
        RETURN false;
    END CASE;
    RETURN v_author IS NOT NULL
       AND v_author = p_user_id
       AND NOT EXISTS (
           SELECT 1 FROM resource_grants g
           WHERE g.resource_type = p_tool
             AND g.resource_id = p_resource_id
             AND g.level = '{_OWNER}'
       );
END
$function$

"""

#: Who each of ``p_resource_ids`` is shared with: the people a grant names,
#: holds a role for, or reaches as everyone in the resource's initiative — and
#: only while they are in it, since a grant outlives the membership it was
#: written for. On a resource in no initiative, "everyone" is the community's
#: members (``p_guild_id``). Standing that comes from elsewhere — a community
#: admin, a content grant — is not an audience: nobody asked them to hear
#: about it. Who a notification may name, and who a notice is read by.
RESOURCE_AUDIENCE = """\
CREATE OR REPLACE FUNCTION resource_audience(p_tool text, p_resource_ids integer[], p_guild_id integer)
 RETURNS TABLE(resource_id integer, user_id integer)
 LANGUAGE plpgsql
 STABLE
AS $function$
BEGIN
    RETURN QUERY
    SELECT DISTINCT g.resource_id, im.user_id
      FROM resource_grants g
      JOIN initiative_members im
        ON im.initiative_id = g.initiative_id
       AND (g.user_id = im.user_id
            OR g.role_id = im.role_id
            OR g.all_initiative_members)
     WHERE g.resource_type = p_tool
       AND g.resource_id = ANY (p_resource_ids)
       AND g.initiative_id IS NOT NULL
    UNION
    SELECT DISTINCT g.resource_id, m.user_id
      FROM resource_grants g
      JOIN public.guild_memberships m
        ON m.guild_id = p_guild_id
       AND (g.user_id = m.user_id OR g.all_initiative_members)
     WHERE g.resource_type = p_tool
       AND g.resource_id = ANY (p_resource_ids)
       AND g.initiative_id IS NULL;
END
$function$

"""

#: Whether a grant row reaches the request, and nothing else: no community
#: admin, no "Full access", no content grant. What a list spanning initiatives
#: shows is what was shared with the reader (``permissions.granted_scope_clause``);
#: ``p_need_write`` narrows to a grant that lets them change it.
RESOURCE_GRANTED = f"""\
CREATE OR REPLACE FUNCTION resource_granted(p_tool text, p_resource_id integer, p_user_id integer, p_need_write boolean, p_st standing)
 RETURNS boolean
 LANGUAGE plpgsql
 STABLE
AS $function$
BEGIN
    RETURN EXISTS (
        SELECT 1 FROM resource_grants g
        WHERE {GRANT_REACHES_READER}
          AND (NOT p_need_write OR g.level IN ({_WRITE_RUNGS}))
    );
END
$function$

"""


def _initiative_tool_actions() -> str:
    """One pair of arms per tool: viewing it where the initiative has it on and
    the role permits it, and making one where the role permits that too, the
    content is not on hold, and access is the reader's own rather than a
    content grant's (which edits what exists and authors nothing)."""
    arms = []
    for tool in Tool:
        switch = f"v_initiative.{tool.view_permission}"
        view_default = str(
            DEFAULT_PERMISSION_VALUES[PermissionKey(tool.view_permission)]
        ).lower()
        create_default = str(
            DEFAULT_PERMISSION_VALUES[PermissionKey(tool.create_permission)]
        ).lower()
        arms.append(
            f"""    IF {switch} THEN
        IF initiative_role_permits(p_initiative_id, p_user_id, '{tool.view_permission}', {view_default}, p_st) THEN
            v_actions := v_actions || 'view:{tool.value}'::text;
        END IF;
        IF NOT {_B.content_hold} AND NOT {_B.pam_any}
           AND initiative_role_permits(p_initiative_id, p_user_id, '{tool.create_permission}', {create_default}, p_st) THEN
            v_actions := v_actions || 'create:{tool.value}'::text;
        END IF;
    END IF;"""
        )
    return "\n".join(arms)


#: What the request may do in one initiative: run it (``manage``: the
#: community's admin or one of its managers), act on its moderation reports
#: (``moderate``: :data:`INITIATIVE_FULL_ACCESS` at write), and, per tool,
#: ``view:<tool>`` and ``create:<tool>``.
INITIATIVE_ACTIONS = f"""\
CREATE OR REPLACE FUNCTION initiative_actions(p_initiative_id integer, p_user_id integer, p_st standing)
 RETURNS text[]
 LANGUAGE plpgsql
 STABLE
AS $function$
DECLARE
    v_initiative initiatives%ROWTYPE;
    v_actions text[] := ARRAY[]::text[];
BEGIN
    SELECT * INTO v_initiative FROM initiatives WHERE id = p_initiative_id;
    IF NOT FOUND THEN
        RETURN v_actions;
    END IF;
    IF {_B.system} OR {_B.admin}
       OR ({_B.this_guild}
           AND p_initiative_id = ANY ({_B.field("manager_initiatives")})) THEN
        v_actions := v_actions || 'manage'::text;
    END IF;
    IF initiative_full_access(p_initiative_id, true, p_st) THEN
        v_actions := v_actions || 'moderate'::text;
    END IF;
{_initiative_tool_actions()}
    RETURN v_actions;
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

#: The five that read only guild tables. Rendered into every guild schema by
#: ``guild_ddl.render_guild_rls_ddl`` ahead of the policies that call them,
#: in this order: the SQL bodies are checked at creation, and each names only
#: tables and the ``public`` functions above.
GUILD_AUTHORIZATION_FUNCTIONS: tuple[tuple[str, str], ...] = (
    ("current_standing", CURRENT_STANDING),
    ("initiative_access", INITIATIVE_ACCESS),
    ("initiative_full_access", INITIATIVE_FULL_ACCESS),
    ("initiative_role_permits", INITIATIVE_ROLE_PERMITS),
    ("resource_level", RESOURCE_LEVEL),
    ("resource_access", RESOURCE_ACCESS),
    ("resource_actions", RESOURCE_ACTIONS),
    ("resource_shares", RESOURCE_SHARES),
    ("resource_granted", RESOURCE_GRANTED),
    ("resource_reclaimable", RESOURCE_RECLAIMABLE),
    ("resource_audience", RESOURCE_AUDIENCE),
    ("initiative_actions", INITIATIVE_ACTIONS),
)

#: Argument types of every function that lives in a guild schema — the five
#: above plus the three ``frozen`` and ``initiative_rls`` render there. What
#: ``DROP FUNCTION`` and ``pg_get_functiondef`` need to name one.
GUILD_FUNCTION_SIGNATURES: dict[str, str] = {
    "current_standing": "()",
    "initiative_access": "(integer, integer, boolean, public.standing)",
    "initiative_full_access": "(integer, boolean, public.standing)",
    "initiative_role_permits": "(integer, integer, text, boolean, public.standing)",
    "resource_level": "(text, integer, integer, integer, public.standing)",
    "resource_access": "(text, integer, integer, integer, boolean, public.standing)",
    "resource_actions": "(text, integer, integer, integer, timestamp with time zone, timestamp with time zone, public.standing)",
    "resource_shares": "(text, integer, integer, integer, public.standing)",
    "resource_granted": "(text, integer, integer, boolean, public.standing)",
    "resource_reclaimable": "(text, integer, integer)",
    "resource_audience": "(text, integer[], integer)",
    "initiative_actions": "(integer, integer, public.standing)",
    "resource_frozen": "(text, bigint, boolean)",
    "resource_frozen_for_grant": "(text, bigint, boolean)",
    "entity_access": "(text, integer, boolean, boolean, public.standing)",
}

#: Functions an earlier render put in a guild schema under a name or
#: signature this one no longer produces. The RLS render drops them last,
#: the template strip drops them with the rest, and the boot step that
#: retires ``public`` copies tries these names too.
RETIRED_GUILD_FUNCTION_SIGNATURES: tuple[tuple[str, str], ...] = (
    ("relationship_endpoint_access", "(text, integer, boolean)"),
    # The gates before they took the statement's standing.
    ("initiative_access", "(integer, integer, boolean)"),
    ("initiative_full_access", "(integer, boolean)"),
    ("initiative_role_permits", "(integer, integer, text, boolean)"),
    ("resource_access", "(text, integer, integer, integer, boolean)"),
    ("entity_access", "(text, integer, boolean, boolean)"),
)


def render_guild_authorization_functions() -> str:
    """The guild functions as schema-relative DDL, for the RLS render.

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
    for name, args in (
        *GUILD_FUNCTION_SIGNATURES.items(),
        *RETIRED_GUILD_FUNCTION_SIGNATURES,
    ):
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
