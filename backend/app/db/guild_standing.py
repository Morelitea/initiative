"""A reader's standing in one community, computed once per request.

Every initiative-scoped table's policies defer to three functions —
``initiative_access`` (membership), ``initiative_role_permits`` (the reader's
role in the initiative) and ``resource_access`` (sharing) — plus an inline
sub-select for the tool switch. Each of those contains a sub-select, so
Postgres never inlines it: one executor start per call, per row, per nesting
level. Everything they compute except the ``resource_grants`` probe is the
same for every row of a request: who the reader is, which initiatives they are
in, what their role there permits, whether the community's sign-in policy is
satisfied, the admin fact and the grant flags.

Gate 1 already worked the other way: ``SET ROLE guild_<id>`` once per request.
This module is the rest of the reader's standing, written the same way — in
one statement, after the routing, by the database, from its own rows.

**One statement, no binds.** :data:`STANDING_SQL` is a single ``SELECT`` of
``set_config`` calls whose values are sub-selects. It binds no user and no
community: every sub-select reads them back from ``app.current_user_id`` and
``app.current_guild_id``, which the routing statement has just written, so
there is one source and no way to compute a standing that disagrees with the
session it lands on. ``set_config`` returns what it wrote, so the row the
statement returns is what the policies will read, and :class:`GuildContext` is
built from that row rather than from what Python believed.

**Bound to its community.** A standing means nothing outside the community it
was computed in — initiative 5 in ``guild_7`` and initiative 5 in ``guild_9``
are different rows. Two things keep one from answering under another's
routing. The routing statement writes ``''`` into every key here, so between
routing and standing the standing is empty and an empty standing answers no on
every membership leg. And the standing records the community it was computed
for (``app.standing_guild_id``) — a member's routed community, or the one a
grantee's grant names — which every gate that reads it compares against the
routed one.

**Where it lives.** In ``session.info`` as part of the stored routing
parameters, so the ``after_begin`` replay hook re-applies the routing and the
standing together from one entry: a replayed transaction cannot carry the
routing of one community and the standing of another.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, Optional, Sequence

from app.core.tools import Tool
from app.db.authorization import sql_values
from app.models.platform.access_grant import AccessGrantPurpose, AccessLevel
from app.models.platform.app_service_registration import registration_live_sql
from app.models.platform.guild import (
    GUILD_LADDER,
    LIVE_STATUS_VALUES,
    GuildRole,
    GuildStatus,
)
from app.models.platform.identity_ref import (
    REF_GRACE_PERIOD,
    REF_MAX_LENGTH,
    IdentityEntity,
    IdentityPurpose,
    ref_prefix,
)
from app.models.platform.user import UserStatus
from app.models.tenant.app_member_consent import ConsentAccess
from app.models.tenant.initiative import DEFAULT_PERMISSION_VALUES, PermissionKey

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.models.platform.access_grant import AccessGrant
    from app.models.platform.guild import Guild, GuildMembership, GuildRole

__all__ = [
    "ActorContext",
    "GuildContext",
    "INSTALL_STANDING_SQL",
    "InstallContext",
    "STANDING_GUCS",
    "STANDING_SQL",
    "compute_guild_standing",
    "compute_install_standing",
    "empty_standing",
    "named_ref_candidates",
    "standing_bind_params",
]


# --- The request context the statement reads back -----------------------------
# NULLIF-guarded throughout: an unset value leaves nothing to cast, and a bare
# ''::int raises and faults the whole statement (CLAUDE.md §6).
_UID = "NULLIF(current_setting('app.current_user_id', true), '')::int"
_GID = "NULLIF(current_setting('app.current_guild_id', true), '')::int"
#: The community a content grant reaches, which a grantee carries instead of
#: ``_GID``.
_PAM_GID = "NULLIF(current_setting('app.pam_guild_id', true), '')::int"
#: The community a settings grant reaches, which a grantee holding only one
#: carries instead of either.
_SETTINGS_GID = "NULLIF(current_setting('app.settings_guild_id', true), '')::int"
#: Whichever of the three names the community this session is routed into.
_ROUTED_GID = f"COALESCE({_GID}, {_PAM_GID}, {_SETTINGS_GID})"

#: A grant that is in force right now — approved, unexpired, still standing.
#: One definition, used by the statement below and by the ``access_grants``
#: policies alike.
LIVE_GRANT = "g.status = 'approved' AND g.expires_at > now()"


def _live_grant(purpose: str, extra: str = "") -> str:
    return (
        "FROM public.access_grants g"
        f" WHERE g.guild_id = {_ROUTED_GID}"
        f" AND g.user_id = {_UID}"
        f" AND g.purpose = '{purpose}'"
        f" AND {LIVE_GRANT}"
        f"{extra}"
    )


#: The rungs that administer a community, as the ladder orders them — the
#: one spelling the admin fact and the settings rung are read off.
_ADMIN_RUNGS: tuple[GuildRole, ...] = tuple(
    rung for rung in GUILD_LADDER if rung.reaches(GuildRole.admin)
)
_ADMIN_RUNGS_SQL = sql_values(rung.value for rung in _ADMIN_RUNGS)
#: The highest rung held wins, so the ladder is walked from the top.
_SETTINGS_RUNG_CASE = "\n".join(
    f"               WHEN bool_or(rung = '{rung.value}') THEN '{rung.value}'"
    for rung in reversed(_ADMIN_RUNGS)
)


def _tool_switch_values() -> str:
    """The per-initiative tool switches as a ``VALUES`` list.

    Rendered from the ``Tool`` enum, the way the switch column names already
    are, so a new tool reaches the standing the moment it reaches the enum.
    """
    return ", ".join(f"('{tool.value}', i.{tool.plural}_enabled)" for tool in Tool)


#: The keys the standing writes, in the order the statement writes them. The
#: routing statement writes ``''`` into every one of them.
STANDING_GUCS: tuple[str, ...] = (
    "app.standing_guild_id",
    "app.guild_admin",
    "app.guild_seat",
    "app.settings_rung",
    "app.pam_read",
    "app.pam_write",
    "app.member_initiatives",
    "app.manager_initiatives",
    "app.member_role_ids",
    "app.role_grants",
    "app.role_denies",
    "app.enabled_tools",
    "app.override_initiatives",
    "app.guild_auth_ok",
    "app.install_read",
    "app.install_write",
)


#: The one statement. Runs as the routed role, after ``SET ROLE``, so the
#: sub-selects on the shared tables are read under those tables' own policies
#: and the routed role's grants (``app_guild_base`` holds ``SELECT`` on
#: ``guild_memberships`` and ``access_grants``, and the read-only floor is
#: derived from it), and the ones on ``initiative_members`` resolve in the
#: community's own schema.
STANDING_SQL = f"""
SELECT
  set_config('app.standing_guild_id',
    COALESCE(
      NULLIF(current_setting('app.current_guild_id', true), ''),
      NULLIF(current_setting('app.pam_guild_id', true), ''),
      NULLIF(current_setting('app.settings_guild_id', true), ''),
      ''), true) AS standing_guild_id,
  set_config('app.guild_admin', COALESCE((
      SELECT (m.role IN ({_ADMIN_RUNGS_SQL}))::text
      FROM public.guild_memberships m
      WHERE m.guild_id = {_GID} AND m.user_id = {_UID}
    ), 'false'), true) AS guild_admin,
  set_config('app.guild_seat', COALESCE((
      SELECT public.guild_superadmin({_ROUTED_GID}, {_UID})::text
    ), 'false'), true) AS guild_seat,
  set_config('app.settings_rung', COALESCE((
      SELECT CASE
{_SETTINGS_RUNG_CASE}
             END
      FROM (
        SELECT m.role::text AS rung
        FROM public.guild_memberships m
        WHERE m.guild_id = {_GID} AND m.user_id = {_UID}
          AND m.role IN ({_ADMIN_RUNGS_SQL})
        UNION ALL
        SELECT g.access_level::text {_live_grant(AccessGrantPurpose.settings.value)}
      ) AS rungs
    ), ''), true) AS settings_rung,
  set_config('app.pam_read', (
      SELECT EXISTS (SELECT 1 {_live_grant(AccessGrantPurpose.content.value)})::text
    ), true) AS pam_read,
  set_config('app.pam_write', (
      SELECT EXISTS (
        SELECT 1 {_live_grant(AccessGrantPurpose.content.value, f" AND g.access_level = '{AccessLevel.read_write.value}'")}
      )::text
    ), true) AS pam_write,
  set_config('app.member_initiatives', COALESCE((
      SELECT string_agg(DISTINCT im.initiative_id::text, ',')
      FROM initiative_members im
      WHERE im.user_id = {_UID}
    ), ''), true) AS member_initiatives,
  set_config('app.manager_initiatives', COALESCE((
      SELECT string_agg(DISTINCT im.initiative_id::text, ',')
      FROM initiative_members im
      JOIN initiative_roles r ON r.id = im.role_id
      WHERE im.user_id = {_UID} AND r.is_manager
    ), ''), true) AS manager_initiatives,
  set_config('app.member_role_ids', COALESCE((
      SELECT string_agg(DISTINCT im.role_id::text, ',')
      FROM initiative_members im
      WHERE im.user_id = {_UID} AND im.role_id IS NOT NULL
    ), ''), true) AS member_role_ids,
  set_config('app.role_grants', COALESCE((
      SELECT string_agg(DISTINCT im.initiative_id || ':' || rp.permission_key, ',')
      FROM initiative_members im
      JOIN initiative_role_permissions rp ON rp.initiative_role_id = im.role_id
      WHERE im.user_id = {_UID} AND rp.enabled
    ), ''), true) AS role_grants,
  set_config('app.role_denies', COALESCE((
      SELECT string_agg(DISTINCT im.initiative_id || ':' || rp.permission_key, ',')
      FROM initiative_members im
      JOIN initiative_role_permissions rp ON rp.initiative_role_id = im.role_id
      WHERE im.user_id = {_UID} AND NOT rp.enabled
    ), ''), true) AS role_denies,
  set_config('app.enabled_tools', COALESCE((
      SELECT string_agg(DISTINCT i.id || ':' || t.tool, ',')
      FROM initiatives i
      JOIN initiative_members im
        ON im.initiative_id = i.id AND im.user_id = {_UID}
      CROSS JOIN LATERAL (VALUES {_tool_switch_values()}) AS t(tool, enabled)
      WHERE t.enabled
    ), ''), true) AS enabled_tools,
  set_config('app.override_initiatives', COALESCE((
      SELECT string_agg(DISTINCT im.initiative_id::text, ',')
      FROM initiative_members im
      JOIN initiative_roles r ON r.id = im.role_id
      WHERE im.user_id = {_UID} AND r.override_share_restrictions
    ), ''), true) AS override_initiatives,
  set_config('app.guild_auth_ok',
    (SELECT public.guild_auth_satisfied()::text), true) AS guild_auth_ok
"""


# --- An installed app's standing ---------------------------------------------
#: What the install routing names, read back the way the person statement reads
#: the user and the community.
_IID = "NULLIF(current_setting('app.current_install_id', true), '')::int"
_CLIENT_ID = "NULLIF(current_setting('app.token_client_id', true), '')"
_TOKEN_SCOPES = (
    "COALESCE(string_to_array("
    "NULLIF(current_setting('app.token_scopes', true), ''), ','), ARRAY[]::text[])"
)
_SCOPE_INITIATIVE = "NULLIF(current_setting('app.scope_initiative_id', true), '')::int"
#: The purpose a member token's consent names; unset for app-wide consent, and
#: for an installation token.
_TOKEN_PURPOSE = "NULLIF(current_setting('app.token_purpose', true), '')"

#: The community statuses whose content is in use, as the person seam reads
#: them.
_LIVE_STATUSES_SQL = sql_values(sorted(LIVE_STATUS_VALUES))

#: A reference row in this install's own sector: the app purpose, the routed
#: community and the routed install. The same predicate the ``identity_refs``
#: policies for the install floor hold every read and insert to
#: (``app.db.public_rls``).
_IN_INSTALL_SECTOR = (
    f"r.purpose = '{IdentityPurpose.app.value}'"
    f" AND r.sector_guild_id = {_GID}"
    f" AND r.sector_id = {_IID}"
)
#: How long a replaced reference keeps resolving, as an interval.
_GRACE_INTERVAL = f"interval '{int(REF_GRACE_PERIOD.total_seconds())} seconds'"


def _tool_permission_values() -> str:
    """Each tool's two role keys as a ``VALUES`` list of ``(resource, key,
    for_write)``: viewing it answers to the tool's read scope, creating it to
    its write scope. Rendered from the ``Tool`` enum, as the switches are."""
    return ", ".join(
        f"('{tool.plural}', '{key}', {str(for_write).lower()})"
        for tool in Tool
        for key, for_write in (
            (tool.view_permission, False),
            (tool.create_permission, True),
        )
    )


def _permission_key_values() -> str:
    """Every initiative role key, as a one-column ``VALUES`` list."""
    return ", ".join(f"('{key.value}')" for key in PermissionKey)


def _permission_default_values() -> str:
    """Every initiative role key with the answer it gets where a role has no
    row for it, as a ``VALUES`` list of ``(key, is_default)``: the defaults
    the content policies hand ``initiative_role_permits``."""
    return ", ".join(
        f"('{key.value}', {str(DEFAULT_PERMISSION_VALUES.get(key, False)).lower()})"
        for key in PermissionKey
    )


#: An installed app's standing, in one statement. Runs as ``guild_<id>_app``
#: after the install routing. The community, the install, the client the token
#: was issued to, the token's scopes, the narrowed initiative and, for a member
#: token, the member and the purpose are read back from that routing; the one
#: bind, ``:named_refs``, is the references the request names (below).
#:
#: ``install`` is the install when it may act at all: the community's status is
#: one its members use, the install is on, and the operator's registration for
#: its listing is live (on, its publisher on, and holding a key set) and the
#: client the token names. Every value below is computed from it, so an install
#: that may not act has an empty standing. ``live`` says which, and
#: ``read_only`` is the community's status.
#:
#: An install is a member of the initiatives it is placed in (narrowed to one
#: when the token names it), and its initiative role is exactly what its scopes
#: allow there: a tool's view key for a read scope on it, its create key for a
#: write scope, and every other key denied, so no member default answers for
#: it. It administers nothing, manages nothing, holds no initiative role a
#: share could name, and carries no grant. The community's sign-in rules
#: govern people signing in; an install's admission is the seat's consent, so
#: that value is what ``live`` says.
#:
#: A **member token** names a member (``app.current_user_id``) and the purpose
#: they consented to (``app.token_purpose``). ``install`` then also asks that
#: the member still belongs to the community, their account is active, and
#: their consent for this install and purpose is granted and not revoked (and,
#: when it is bound to an initiative, that the token is narrowed to it). What it
#: reaches is the member's own within the install's: the initiatives the member
#: is in and the install is placed in; there, the keys the member's role
#: permits (a manager role, a stored yes, or a default no stored row turns off)
#: that the scopes also allow, and every other key denied; the member's roles
#: and "Full access" within those initiatives; and writes only when the
#: consent is ``read_write``. It is never an admin, the seat, a grantee or a
#: manager. The consent was given from a session that met the community's
#: sign-in rules, so that value too is what ``live`` says.
#:
#: Two more columns carry what the install calls things, both read only in its
#: own sector (``purpose = 'app'``, the routed community and the routed
#: install): ``guild_ref``, its live reference for the community, and
#: ``named_refs``, the references in ``:named_refs`` that name somebody there,
#: as ``{ref: [entity_type, entity_id]}``. A replaced reference still resolves
#: for its grace window, as ``identity_refs.resolve_ref`` has it. The array
#: chooses which rows are looked up; the sector is the routing's.
INSTALL_STANDING_SQL = f"""
WITH consent AS (
  SELECT c.initiative_id,
         c.granted_access = '{ConsentAccess.read_write.value}' AS writes
  FROM app_member_consents c
  WHERE {_UID} IS NOT NULL
    AND c.install_id = {_IID}
    AND c.user_id = {_UID}
    AND c.purpose IS NOT DISTINCT FROM {_TOKEN_PURPOSE}
    AND c.granted_access IS NOT NULL
    AND c.revoked_at IS NULL
    AND (c.initiative_id IS NULL OR c.initiative_id = {_SCOPE_INITIATIVE})
),
install AS (
  SELECT a.id, a.granted_scopes, g.status = '{GuildStatus.read_only.value}' AS read_only
  FROM guild_apps a
  JOIN public.guilds g ON g.id = {_GID}
  WHERE a.id = {_IID}
    AND a.enabled
    AND g.status IN ({_LIVE_STATUSES_SQL})
    AND EXISTS (
      SELECT 1
      FROM public.app_service_registrations r
      JOIN public.publishers p ON p.id = r.publisher_id
      WHERE r.listing_uid = a.listing_uid
        AND r.public_id = {_CLIENT_ID}
        AND {registration_live_sql("r", "p")}
    )
    AND ({_UID} IS NULL OR (
      EXISTS (SELECT 1 FROM consent)
      AND EXISTS (
        SELECT 1
        FROM public.guild_memberships m
        WHERE m.guild_id = {_GID} AND m.user_id = {_UID}
      )
      AND EXISTS (
        SELECT 1
        FROM public.users u
        WHERE u.id = {_UID} AND u.status = '{UserStatus.active.value}'
      )
    ))
),
granted_scope AS (
  SELECT split_part(s.scope, ':', 1) AS resource,
         bool_or(split_part(s.scope, ':', 2) = 'write') AS writes
  FROM install i
  CROSS JOIN LATERAL unnest(i.granted_scopes) AS s(scope)
  GROUP BY 1
),
token_scope AS (
  SELECT split_part(t.scope, ':', 1) AS resource,
         bool_or(split_part(t.scope, ':', 2) = 'write') AS writes
  FROM unnest({_TOKEN_SCOPES}) AS t(scope)
  GROUP BY 1
),
held AS (
  SELECT g.resource,
         g.writes AND t.writes AND NOT i.read_only
           AND ({_UID} IS NULL OR EXISTS (SELECT 1 FROM consent c WHERE c.writes))
           AS writes
  FROM granted_scope g
  JOIN token_scope t ON t.resource = g.resource
  CROSS JOIN install i
),
member_role AS (
  SELECT im.initiative_id, im.role_id,
         COALESCE(r.is_manager, false) AS is_manager,
         COALESCE(r.override_share_restrictions, false) AS overrides
  FROM initiative_members im
  LEFT JOIN initiative_roles r ON r.id = im.role_id
  WHERE {_UID} IS NOT NULL AND im.user_id = {_UID}
),
placed AS (
  SELECT DISTINCT p.initiative_id
  FROM app_placements p
  JOIN install i ON i.id = p.install_id
  WHERE ({_SCOPE_INITIATIVE} IS NULL OR p.initiative_id = {_SCOPE_INITIATIVE})
    AND ({_UID} IS NULL OR (
      p.initiative_id IN (SELECT mr.initiative_id FROM member_role mr)
      AND NOT EXISTS (
        SELECT 1 FROM consent c WHERE c.initiative_id <> p.initiative_id
      )
    ))
),
permitted AS (
  SELECT p.initiative_id, k.key
  FROM placed p
  JOIN member_role mr ON mr.initiative_id = p.initiative_id
  CROSS JOIN (VALUES {_permission_default_values()}) AS k(key, is_default)
  WHERE mr.is_manager
     OR EXISTS (
       SELECT 1 FROM initiative_role_permissions rp
       WHERE rp.initiative_role_id = mr.role_id
         AND rp.permission_key = k.key
         AND rp.enabled
     )
     OR (k.is_default AND NOT EXISTS (
       SELECT 1 FROM initiative_role_permissions rp
       WHERE rp.initiative_role_id = mr.role_id
         AND rp.permission_key = k.key
         AND NOT rp.enabled
     ))
),
granted AS (
  SELECT DISTINCT p.initiative_id || ':' || k.key AS pair
  FROM placed p
  CROSS JOIN (VALUES {_tool_permission_values()}) AS k(resource, key, for_write)
  JOIN held h ON h.resource = k.resource AND (h.writes OR NOT k.for_write)
  WHERE {_UID} IS NULL OR EXISTS (
    SELECT 1 FROM permitted pm
    WHERE pm.initiative_id = p.initiative_id AND pm.key = k.key
  )
),
denied AS (
  SELECT DISTINCT p.initiative_id || ':' || k.key AS pair
  FROM placed p
  CROSS JOIN (VALUES {_permission_key_values()}) AS k(key)
  WHERE NOT EXISTS (
    SELECT 1 FROM granted gr WHERE gr.pair = p.initiative_id || ':' || k.key
  )
)
SELECT
  (SELECT EXISTS (SELECT 1 FROM install)) AS live,
  COALESCE((
      SELECT g.status = '{GuildStatus.read_only.value}'
      FROM public.guilds g
      WHERE g.id = {_GID}
    ), false) AS read_only,
  set_config('app.standing_guild_id',
    COALESCE(NULLIF(current_setting('app.current_guild_id', true), ''), ''),
    true) AS standing_guild_id,
  set_config('app.guild_admin', 'false', true) AS guild_admin,
  set_config('app.guild_seat', 'false', true) AS guild_seat,
  set_config('app.settings_rung', '', true) AS settings_rung,
  set_config('app.pam_guild_id', '', true) AS pam_guild_id,
  set_config('app.pam_read', 'false', true) AS pam_read,
  set_config('app.pam_write', 'false', true) AS pam_write,
  set_config('app.member_initiatives', COALESCE((
      SELECT string_agg(p.initiative_id::text, ',' ORDER BY p.initiative_id)
      FROM placed p
    ), ''), true) AS member_initiatives,
  set_config('app.manager_initiatives', '', true) AS manager_initiatives,
  set_config('app.member_role_ids', COALESCE((
      SELECT string_agg(DISTINCT mr.role_id::text, ',')
      FROM member_role mr
      JOIN placed p ON p.initiative_id = mr.initiative_id
      WHERE mr.role_id IS NOT NULL
    ), ''), true) AS member_role_ids,
  set_config('app.role_grants', COALESCE((
      SELECT string_agg(gr.pair, ',' ORDER BY gr.pair) FROM granted gr
    ), ''), true) AS role_grants,
  set_config('app.role_denies', COALESCE((
      SELECT string_agg(d.pair, ',' ORDER BY d.pair) FROM denied d
    ), ''), true) AS role_denies,
  set_config('app.enabled_tools', COALESCE((
      SELECT string_agg(DISTINCT i.id || ':' || t.tool, ',')
      FROM initiatives i
      JOIN placed p ON p.initiative_id = i.id
      CROSS JOIN LATERAL (VALUES {_tool_switch_values()}) AS t(tool, enabled)
      WHERE t.enabled
    ), ''), true) AS enabled_tools,
  set_config('app.override_initiatives', COALESCE((
      SELECT string_agg(DISTINCT mr.initiative_id::text, ',')
      FROM member_role mr
      JOIN placed p ON p.initiative_id = mr.initiative_id
      WHERE mr.overrides
    ), ''), true) AS override_initiatives,
  set_config('app.install_read', COALESCE((
      SELECT string_agg(DISTINCT h.resource, ',') FROM held h
    ), ''), true) AS install_read,
  set_config('app.install_write', COALESCE((
      SELECT string_agg(DISTINCT h.resource, ',') FROM held h WHERE h.writes
    ), ''), true) AS install_write,
  set_config('app.guild_auth_ok',
    (SELECT EXISTS (SELECT 1 FROM install))::text, true) AS guild_auth_ok,
  (
    SELECT r.ref
    FROM public.identity_refs r
    WHERE {_IN_INSTALL_SECTOR}
      AND r.entity_type = '{IdentityEntity.guild.value}'
      AND r.entity_id = {_GID}
      AND r.retired_at IS NULL
      AND EXISTS (SELECT 1 FROM install)
  ) AS guild_ref,
  COALESCE((
      SELECT jsonb_object_agg(r.ref, jsonb_build_array(r.entity_type, r.entity_id))
      FROM public.identity_refs r
      WHERE r.ref = ANY(CAST(:named_refs AS text[]))
        AND {_IN_INSTALL_SECTOR}
        AND (r.retired_at IS NULL OR r.retired_at > now() - {_GRACE_INTERVAL})
        AND EXISTS (SELECT 1 FROM install)
    ), '{{}}'::jsonb) AS named_refs
"""


def _ids(csv: str | None) -> tuple[int, ...]:
    return tuple(int(part) for part in (csv or "").split(",") if part)


def _pairs(csv: str | None) -> tuple[str, ...]:
    return tuple(part for part in (csv or "").split(",") if part)


@dataclass(frozen=True)
class GuildContext:
    """A reader's standing in one community, for one request.

    Built only by the establishment seam (``app.api.deps``): the lookup decides
    the route, the standing statement computes the facts, and this is what it
    returned. Stored on the session beside the routing parameters — it *is*
    part of them — and replayed per transaction with them.

    The rows come from the lookup (which is what decided there was any access
    at all); every scalar below the row fields came back from the standing
    statement, so what Python believes and what the policies read are the same
    values.
    """

    guild: "Guild"
    user_id: int
    #: The community, as a number. Held rather than read off ``guild``: a
    #: cross-guild gather clears the session's identity map between
    #: communities, and which one a standing is for cannot depend on an
    #: object still being attached to a session.
    guild_id: int
    #: The membership row, when there is one. ``None`` for a grantee.
    membership: Optional["GuildMembership"] = None
    #: That row's role, as a value. Held rather than read off the row for the
    #: reason ``guild_id`` is: what somebody is in a community must not depend
    #: on an object still being attached to a session.
    guild_role: Optional[str] = None
    #: The live content grant, when access is by one rather than by membership.
    grant: Optional["AccessGrant"] = None
    #: The live settings grant, independent of content access, and the rung it
    #: confers.
    settings_grant: Optional["AccessGrant"] = None
    settings_grant_level: Optional[str] = None
    #: True when the community is in ``read_only`` status and access is by real
    #: membership: the session is routed into the SELECT-only ``guild_<id>_ro``
    #: role, so content writes are refused by Postgres. Never set on the grant
    #: branch — a grant carries its own read/write level.
    content_read_only: bool = False

    # --- What the standing statement returned --------------------------------
    #: The community the standing was computed for; ``None`` until it has been.
    standing_guild_id: Optional[int] = None
    #: The membership row's role is ``admin`` or ``superadmin``. Computed from
    #: that row by the database; no grant sets it.
    admin: bool = False
    #: ``public.guild_superadmin(guild, user)`` — the membership row's seat, or
    #: a live ``superadmin`` settings grant.
    seat: bool = False
    #: The rung this request administers the community at, or ``None``.
    settings_rung: Optional[str] = None
    #: A live content grant covers this request, at read / read_write.
    pam_read: bool = False
    pam_write: bool = False
    member_initiatives: tuple[int, ...] = ()
    manager_initiatives: tuple[int, ...] = ()
    member_role_ids: tuple[int, ...] = ()
    #: ``"<initiative_id>:<permission_key>"`` where the role's row says yes.
    role_grants: tuple[str, ...] = ()
    #: The same, where it says no.
    role_denies: tuple[str, ...] = ()
    #: ``"<initiative_id>:<tool>"`` where the initiative's switch is on.
    enabled_tools: tuple[str, ...] = ()
    #: Initiatives where the reader's role holds "Full access".
    override_initiatives: tuple[int, ...] = ()
    #: The community's sign-in policy is satisfied by this session.
    guild_auth_ok: bool = False

    # --- Identity ------------------------------------------------------------

    @property
    def role(self) -> "GuildRole":
        """The seat this request holds in the community.

        A grantee holds ``support`` — a first-class identity for granted access
        rather than a member masquerade. It clears no guard of its own: what of
        the community's configuration a grant reaches is its settings rung,
        read separately.
        """
        if self.guild_role is None:
            return GuildRole.support
        return GuildRole(self.guild_role)

    @property
    def is_admin(self) -> bool:
        """Whether this request carries a community admin's authority.

        The membership row's own fact, as the database computed it. A grant
        never answers yes here: what a grant reaches is its own two axes.
        """
        return self.admin

    @property
    def rung(self) -> "GuildRole":
        """The rung this request administers the community at.

        The membership row's, or the one a live settings grant lends for its
        window. Where :attr:`role` names who somebody *is* here — and answers
        ``support`` for granted access — this names what they may run, which
        is what a decision about the roster or the seat asks.
        """
        if self.membership is None and self.settings_rung is not None:
            return GuildRole(self.settings_rung)
        return self.role

    def reaches(self, rung: "GuildRole", *, settings: bool = False) -> bool:
        """Whether this request carries what ``rung`` carries, by the standing.

        The community's ladder asked of a request rather than of a row: the
        seat is what ``guild_superadmin()`` computed, the admin rung is the
        membership row's fact, and the member rung is a membership row.
        ``support`` is below every rung — granted access is its own identity —
        so every request reaches it.

        ``settings`` asks on the community's configuration surface, where a
        settings grant also answers at the rung it lends. Everywhere else the
        rungs above member are the membership row's alone.
        """
        if rung is GuildRole.superadmin:
            return self.seat and (settings or self.admin)
        if rung is GuildRole.admin:
            return self.admin or (settings and self.settings_rung is not None)
        if rung is GuildRole.member:
            return self.guild_role is not None and GuildRole(self.guild_role).reaches(
                GuildRole.member
            )
        return True

    @property
    def reaches_seat(self) -> bool:
        """Whether the community's top seat is within this request's reach.

        Read from what the lookup found — the membership row's role, or the
        rung of a live settings grant — because the routing has to be chosen
        before the standing statement runs. :attr:`seat` is the same question
        answered by ``public.guild_superadmin()`` from the same rows, and is
        what a guard checks once the standing is in.
        """
        return (
            self.guild_role == GuildRole.superadmin.value
            or self.settings_grant_level == GuildRole.superadmin.value
        )

    @property
    def is_pam(self) -> bool:
        return self.grant is not None or self.settings_grant is not None

    @property
    def is_settings_only(self) -> bool:
        return self.grant is None and self.settings_grant is not None

    @property
    def grant_writes(self) -> bool:
        """Whether what reaches the community here may change something: a
        membership row, or a grant beside a live ``read_write`` content grant.
        """
        return not self.is_pam or self.pam_write

    @property
    def writes_settings(self) -> bool:
        """Whether this request may change the community configuration it
        reaches: the rung that reaches it, and a membership row or a
        ``read_write`` content grant beside that rung."""
        return self.reaches(GuildRole.admin, settings=True) and self.grant_writes

    # --- The two grant axes --------------------------------------------------

    @property
    def settings_level(self) -> Optional[str]:
        """The rung a settings grant confers, read off the grant itself."""
        return self.settings_grant_level

    @property
    def grant_content(self) -> Optional[str]:
        """The content grant's level as the database found it: ``read``,
        ``read_write``, or ``None`` when no live grant covers this request."""
        if self.pam_write:
            return "read_write"
        return "read" if self.pam_read else None

    def grant_satisfies(
        self, *, access: str = "read", require_owner: bool = False
    ) -> bool:
        """Whether a live content grant covers this request at ``access``.

        A grant never confers ownership — owner-only operations stay on real
        permissions. A read grant satisfies reads; a read_write grant satisfies
        reads and writes.
        """
        if require_owner:
            return False
        if access == "write":
            return self.pam_write
        return self.pam_read or self.pam_write

    def overrides_sharing(self, initiative_id: Optional[int]) -> bool:
        """Whether this request holds "Full access" in ``initiative_id`` — the
        initiative-scoped sibling of the admin leg."""
        if initiative_id is None:
            return False
        return initiative_id in self.override_initiatives

    def membership_only(self) -> "GuildContext":
        """This standing with what a grant reaches taken off.

        For a decision that has to rest on somebody's own place in the
        community rather than on a window somebody opened for them.
        """
        return replace(
            self,
            grant=None,
            settings_grant=None,
            settings_grant_level=None,
            settings_rung=None,
            pam_read=False,
            pam_write=False,
        )

    # --- The standing --------------------------------------------------------

    def with_standing(self, row: dict[str, Any]) -> "GuildContext":
        """This context completed with what the standing statement returned."""
        return replace(
            self,
            standing_guild_id=int(row["standing_guild_id"])
            if row.get("standing_guild_id")
            else None,
            admin=row.get("guild_admin") == "true",
            seat=row.get("guild_seat") == "true",
            settings_rung=row.get("settings_rung") or None,
            pam_read=row.get("pam_read") == "true",
            pam_write=row.get("pam_write") == "true",
            member_initiatives=_ids(row.get("member_initiatives")),
            manager_initiatives=_ids(row.get("manager_initiatives")),
            member_role_ids=_ids(row.get("member_role_ids")),
            role_grants=_pairs(row.get("role_grants")),
            role_denies=_pairs(row.get("role_denies")),
            enabled_tools=_pairs(row.get("enabled_tools")),
            override_initiatives=_ids(row.get("override_initiatives")),
            guild_auth_ok=row.get("guild_auth_ok") == "true",
        )


@dataclass(frozen=True)
class InstallContext:
    """An installed app's standing in its community, for one request.

    Built only by the establishment seam (``app.api.deps``) from a verified
    install: the routing names the community, the install, the client and the
    token's scopes, and the install standing statement computes the rest from
    rows. Stored on the session as part of the routing parameters, and
    replayed per transaction with them, like :class:`GuildContext`.
    """

    guild_id: int
    install_id: int
    #: The registration's ``public_id`` the token was issued to.
    client_id: str
    #: The scopes the token carries. What the install may use is these and
    #: the seat's grant together, which the standing computes.
    token_scopes: frozenset[str]
    #: The one initiative the token is narrowed to, when it is.
    scope_initiative_id: Optional[int] = None
    #: The member a member token acts for, and the purpose they consented to
    #: (``None`` for app-wide consent). ``None`` for the install itself. A write
    #: that names its author, such as the owner grant on something created,
    #: names this member.
    member_user_id: Optional[int] = None
    purpose: Optional[str] = None

    # --- What the install standing statement returned -------------------------
    #: The community the standing was computed for; ``None`` until it has been.
    standing_guild_id: Optional[int] = None
    #: The community is in use, the install is on, and its registration is
    #: live and the client the token names.
    live: bool = False
    #: The community is in ``read_only`` status.
    read_only: bool = False
    #: The initiatives the install is placed in, narrowed to one when asked.
    member_initiatives: tuple[int, ...] = ()
    #: ``"<initiative_id>:<permission_key>"`` its scopes allow there.
    role_grants: tuple[str, ...] = ()
    #: Every other key, in the same initiatives.
    role_denies: tuple[str, ...] = ()
    #: ``"<initiative_id>:<tool>"`` where the initiative's switch is on.
    enabled_tools: tuple[str, ...] = ()
    #: For a member token, the member's initiative roles, and the initiatives
    #: where their role holds "Full access", within ``member_initiatives``.
    #: Empty for the install itself.
    member_role_ids: tuple[int, ...] = ()
    override_initiatives: tuple[int, ...] = ()
    #: The resources its scopes let it read, and write.
    install_read: tuple[str, ...] = ()
    install_write: tuple[str, ...] = ()
    #: What this install calls its community, when it has been named to it.
    guild_ref: Optional[str] = None
    #: The references this request named that resolve in the install's own
    #: sector, as ``(ref, entity_type, entity_id)``. For this request only:
    #: the replay writes the standing, and names nobody.
    named_refs: tuple[tuple[str, str, int], ...] = ()

    @property
    def guild_auth_ok(self) -> bool:
        """What the standing wrote for the community's sign-in gate: an install
        that may act answers it."""
        return self.live

    @property
    def is_member_token(self) -> bool:
        """Whether this request acts for a member rather than as the install."""
        return self.member_user_id is not None

    def overrides_sharing(self, initiative_id: Optional[int]) -> bool:
        """Whether the member a member token acts for holds "Full access" in
        ``initiative_id``. Never, for the install itself."""
        return initiative_id is not None and initiative_id in self.override_initiatives

    # --- A person's standing, as an install answers it -----------------------
    # A route that serves both actors reads these off whichever context it was
    # handed. Each is what the install standing statement wrote for the key a
    # person's standing sets: an install is never an admin, a grantee or a
    # manager, and it is nobody. A member token names its member in
    # ``member_user_id``; what that member's writes own is written by the
    # tool table's trigger, as for the install.

    @property
    def user_id(self) -> None:
        """An install is not a person, even when it acts for one."""
        return None

    @property
    def is_admin(self) -> bool:
        return False

    @property
    def content_read_only(self) -> bool:
        """The community is in ``read_only`` status. The standing leaves the
        install no write scope there; this reports the same hold."""
        return self.read_only

    @property
    def is_pam(self) -> bool:
        return False

    @property
    def pam_read(self) -> bool:
        return False

    @property
    def pam_write(self) -> bool:
        return False

    @property
    def grant_content(self) -> Optional[str]:
        return None

    def grant_satisfies(
        self, *, access: str = "read", require_owner: bool = False
    ) -> bool:
        return False

    @property
    def manager_initiatives(self) -> tuple[int, ...]:
        return ()

    def holds(self, scope: str) -> bool:
        """Whether the standing lets this install use ``scope``: its resource
        among what the token and the seat's grant hold together (write implies
        read), writing only where the standing writes."""
        resource, _, access = scope.partition(":")
        return resource in (
            self.install_write if access == "write" else self.install_read
        )

    def with_standing(self, row: dict[str, Any]) -> "InstallContext":
        """This context completed with what the install standing statement
        returned."""
        return replace(
            self,
            standing_guild_id=int(row["standing_guild_id"])
            if row.get("standing_guild_id")
            else None,
            live=bool(row.get("live")),
            read_only=bool(row.get("read_only")),
            member_initiatives=_ids(row.get("member_initiatives")),
            role_grants=_pairs(row.get("role_grants")),
            role_denies=_pairs(row.get("role_denies")),
            enabled_tools=_pairs(row.get("enabled_tools")),
            member_role_ids=_ids(row.get("member_role_ids")),
            override_initiatives=_ids(row.get("override_initiatives")),
            install_read=_pairs(row.get("install_read")),
            install_write=_pairs(row.get("install_write")),
            guild_ref=row.get("guild_ref") or None,
            named_refs=_named_refs(row.get("named_refs")),
        )


#: Who a request that names an app scope is serving: a person's standing in the
#: community, or an installed app's.
ActorContext = GuildContext | InstallContext


def _named_refs(value: Any) -> tuple[tuple[str, str, int], ...]:
    """The statement's ``named_refs`` column as sorted triples. The driver hands
    a ``jsonb`` column read through ``text()`` back as its text."""
    if not value:
        return ()
    mapping = json.loads(value) if isinstance(value, (str, bytes)) else value
    return tuple(
        sorted(
            (str(ref), str(entity_type), int(entity_id))
            for ref, (entity_type, entity_id) in mapping.items()
        )
    )


def _csv(values: Sequence[Any]) -> str:
    return ",".join(str(v) for v in values)


def empty_standing() -> dict[str, str]:
    """What the routing statement writes: nothing.

    Every membership, role and switch leg reads no from it, which is what a
    session that has been routed but not yet stood up should answer.
    """
    return {
        "standing_guild_id": "",
        "guild_admin": "false",
        "guild_seat": "false",
        "settings_rung": "",
        "member_initiatives": "",
        "manager_initiatives": "",
        "member_role_ids": "",
        "role_grants": "",
        "role_denies": "",
        "enabled_tools": "",
        "override_initiatives": "",
        "install_read": "",
        "install_write": "",
    }


def standing_bind_params(
    context: "GuildContext | InstallContext | None",
) -> dict[str, str]:
    """The routing statement's standing binds for ``context``.

    ``None`` — a system route, an unattributed context, the window between the
    routing and the standing — renders :func:`empty_standing`.
    """
    if context is None or context.standing_guild_id is None:
        return empty_standing()
    if isinstance(context, InstallContext):
        return {
            **empty_standing(),
            "standing_guild_id": str(context.standing_guild_id),
            "member_initiatives": _csv(context.member_initiatives),
            "role_grants": _csv(context.role_grants),
            "role_denies": _csv(context.role_denies),
            "enabled_tools": _csv(context.enabled_tools),
            "member_role_ids": _csv(context.member_role_ids),
            "override_initiatives": _csv(context.override_initiatives),
            "install_read": _csv(context.install_read),
            "install_write": _csv(context.install_write),
        }
    return {
        "standing_guild_id": str(context.standing_guild_id),
        "guild_admin": "true" if context.admin else "false",
        "guild_seat": "true" if context.seat else "false",
        "settings_rung": context.settings_rung or "",
        "member_initiatives": _csv(context.member_initiatives),
        "manager_initiatives": _csv(context.manager_initiatives),
        "member_role_ids": _csv(context.member_role_ids),
        "role_grants": _csv(context.role_grants),
        "role_denies": _csv(context.role_denies),
        "enabled_tools": _csv(context.enabled_tools),
        "override_initiatives": _csv(context.override_initiatives),
        "install_read": "",
        "install_write": "",
    }


async def compute_guild_standing(session: "AsyncSession") -> dict[str, Any]:
    """Run :data:`STANDING_SQL` and return the row it wrote.

    The routed session has just had every standing key cleared, so what this
    writes is the whole of it. It binds nothing: the user and the community are
    read back from the context the routing statement wrote.
    """
    from sqlalchemy import text

    row = (await session.exec(text(STANDING_SQL))).one()
    return dict(row._mapping)


def named_ref_candidates(values: Sequence[str]) -> list[str]:
    """The strings among ``values`` shaped like a reference an install holds,
    once each: its ``app`` prefix for a person or a community, and no longer
    than a reference can be. What the install standing statement is asked to
    look up."""
    prefixes = tuple(
        f"{ref_prefix(entity, IdentityPurpose.app)}_" for entity in IdentityEntity
    )
    return sorted(
        {
            value
            for value in values
            if len(value) <= REF_MAX_LENGTH and value.startswith(prefixes)
        }
    )


async def compute_install_standing(
    session: "AsyncSession", named_refs: Sequence[str] = ()
) -> dict[str, Any]:
    """Run :data:`INSTALL_STANDING_SQL` and return the row it wrote.

    The install and its community are read back from the routing, as
    :func:`compute_guild_standing` reads the person back. ``named_refs`` is
    the one bind: the references the request names, resolved in the same
    statement, in the install's own sector.
    """
    from sqlalchemy import text

    row = (
        await session.exec(
            text(INSTALL_STANDING_SQL).bindparams(
                named_refs=named_ref_candidates(named_refs)
            )
        )
    ).one()
    return dict(row._mapping)
