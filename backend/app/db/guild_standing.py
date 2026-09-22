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
for (``app.standing_guild_id``), which every gate that reads it compares
against the routed one.

**Where it lives.** In ``session.info`` as part of the stored routing
parameters, so the ``after_begin`` replay hook re-applies the routing and the
standing together from one entry: a replayed transaction cannot carry the
routing of one community and the standing of another.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, Optional, Sequence

from app.core.tools import Tool

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.models.platform.access_grant import AccessGrant
    from app.models.platform.guild import Guild, GuildMembership, GuildRole

__all__ = [
    "GuildContext",
    "STANDING_GUCS",
    "STANDING_SQL",
    "compute_guild_standing",
    "empty_standing",
    "standing_bind_params",
]


# --- The request context the statement reads back -----------------------------
# NULLIF-guarded throughout: an unset value leaves nothing to cast, and a bare
# ''::int raises and faults the whole statement (CLAUDE.md §6).
_UID = "NULLIF(current_setting('app.current_user_id', true), '')::int"
_GID = "NULLIF(current_setting('app.current_guild_id', true), '')::int"
#: The community a grant reaches, which a grantee carries instead of ``_GID``.
_PAM_GID = "NULLIF(current_setting('app.pam_guild_id', true), '')::int"
#: Whichever of the two names the community this session is routed into.
_ROUTED_GID = f"COALESCE({_GID}, {_PAM_GID})"

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
    COALESCE(current_setting('app.current_guild_id', true), ''), true) AS standing_guild_id,
  set_config('app.guild_admin', COALESCE((
      SELECT (m.role IN ('admin', 'superadmin'))::text
      FROM public.guild_memberships m
      WHERE m.guild_id = {_GID} AND m.user_id = {_UID}
    ), 'false'), true) AS guild_admin,
  set_config('app.guild_seat', COALESCE((
      SELECT public.guild_superadmin({_ROUTED_GID}, {_UID})::text
    ), 'false'), true) AS guild_seat,
  set_config('app.settings_rung', COALESCE((
      SELECT CASE
               WHEN bool_or(rung = 'superadmin') THEN 'superadmin'
               WHEN bool_or(rung = 'admin') THEN 'admin'
             END
      FROM (
        SELECT m.role::text AS rung
        FROM public.guild_memberships m
        WHERE m.guild_id = {_GID} AND m.user_id = {_UID}
          AND m.role IN ('admin', 'superadmin')
        UNION ALL
        SELECT g.access_level::text {_live_grant("settings")}
      ) AS rungs
    ), ''), true) AS settings_rung,
  set_config('app.pam_read', (
      SELECT EXISTS (SELECT 1 {_live_grant("content")})::text
    ), true) AS pam_read,
  set_config('app.pam_write', (
      SELECT EXISTS (
        SELECT 1 {_live_grant("content", " AND g.access_level = 'read_write'")}
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
        from app.models.platform.guild import GuildRole

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
    def is_pam(self) -> bool:
        return self.grant is not None or self.settings_grant is not None

    @property
    def is_settings_only(self) -> bool:
        return self.grant is None and self.settings_grant is not None

    # --- The two grant axes --------------------------------------------------

    @property
    def settings_level(self) -> Optional[str]:
        """The rung a settings grant confers, read off the grant itself."""
        return self.settings_grant_level

    def settings_rung_reaches(self, role: "GuildRole") -> bool:
        """Whether the settings grant includes ``role``'s authority."""
        from app.models.platform.guild import GuildRole

        level = self.settings_level
        if level is None:
            return False
        if level == GuildRole.superadmin.value:
            return role in (GuildRole.admin, GuildRole.superadmin)
        return role is GuildRole.admin

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

    def bypasses_dac(
        self,
        *,
        initiative_id: Optional[int] = None,
        access: str = "read",
        require_owner: bool = False,
    ) -> bool:
        """The single "sees/edits regardless of sharing rows?" answer: a
        satisfying grant, a community admin, or "Full access" in the row's
        initiative. Defined once so a call site cannot apply one leg and drop
        another."""
        if self.grant_satisfies(access=access, require_owner=require_owner):
            return True
        if self.is_admin:
            return True
        return self.overrides_sharing(initiative_id)

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
    }


def standing_bind_params(context: Optional[GuildContext]) -> dict[str, str]:
    """The routing statement's standing binds for ``context``.

    ``None`` — a system route, an unattributed context, the window between the
    routing and the standing — renders :func:`empty_standing`.
    """
    if context is None or context.standing_guild_id is None:
        return empty_standing()
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
