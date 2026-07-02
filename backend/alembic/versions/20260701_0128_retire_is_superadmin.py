"""Retire the ``app.is_superadmin`` GUC: strip its dead policy legs.

The GUC was retired from the request path long ago (Phase 3 of the platform
roles work) and since then has only ever been set on the BYPASSRLS admin
engine — where policies don't apply at all. Every ``OR is_superadmin`` leg
below is therefore provably dead: no live, policy-bound session ever sets the
GUC true. This migration recreates the 14 shared-table policies that still
carry the leg, without it — a strictly-tightening, no-behavior-change edit —
so the superadmin concept can be deleted from the codebase entirely.

(The frozen legacy public copies of guild-content tables on pre-squash
deployments keep their inert legs; they are dropped with those tables in the
future drop release.)

Revision ID: 20260701_0128
Revises: 20260701_0127
Create Date: 2026-07-01
"""

from alembic import op
from sqlalchemy import text

revision = "20260701_0128"
down_revision = "20260701_0127"
branch_labels = None
depends_on = None

# NULLIF-guarded session-variable forms (see CLAUDE.md): an unset/empty GUC
# must compare as NULL, never raise mid-policy.
_GUILD_ID = "(NULLIF(current_setting('app.current_guild_id', true), ''))::integer"
_USER_ID = "(NULLIF(current_setting('app.current_user_id', true), ''))::integer"
_GUILD_ADMIN = "current_setting('app.current_guild_role', true) = 'admin'"
_SUPERADMIN_LEG = "current_setting('app.is_superadmin', true) = 'true'"

_INVITE_MEMBER = (
    "EXISTS (SELECT 1 FROM public.guild_memberships "
    "WHERE guild_memberships.guild_id = guild_invites.guild_id "
    f"AND guild_memberships.user_id = {_USER_ID})"
)
_GUILD_MEMBER = (
    "EXISTS (SELECT 1 FROM public.guild_memberships "
    "WHERE guild_memberships.guild_id = guilds.id "
    f"AND guild_memberships.user_id = {_USER_ID})"
)

# (table, policy, FOR clause, USING predicate | None, WITH CHECK predicate | None)
# — the predicates are the existing ones minus the dead superadmin leg.
_POLICIES: list[tuple[str, str, str, str | None, str | None]] = [
    ("guild_invites", "guild_select", "FOR SELECT", _INVITE_MEMBER, None),
    (
        "guild_invites",
        "guild_insert",
        "FOR INSERT",
        None,
        f"guild_id = {_GUILD_ID}",
    ),
    (
        "guild_invites",
        "guild_update",
        "FOR UPDATE",
        f"guild_id = {_GUILD_ID}",
        f"guild_id = {_GUILD_ID}",
    ),
    ("guild_invites", "guild_delete", "FOR DELETE", f"guild_id = {_GUILD_ID}", None),
    (
        "guilds",
        "guild_select",
        "FOR SELECT",
        f"id = {_GUILD_ID} OR {_GUILD_MEMBER}",
        None,
    ),
    ("guilds", "guild_insert", "FOR INSERT", None, f"{_USER_ID} IS NOT NULL"),
    (
        "guilds",
        "guild_update",
        "FOR UPDATE",
        f"id = {_GUILD_ID} AND {_GUILD_ADMIN}",
        f"id = {_GUILD_ID} AND {_GUILD_ADMIN}",
    ),
    (
        "guilds",
        "guild_delete",
        "FOR DELETE",
        f"id = {_GUILD_ID} AND {_GUILD_ADMIN}",
        None,
    ),
    (
        "oidc_claim_mappings",
        "guild_isolation",
        "",
        f"guild_id = {_GUILD_ID}",
        f"guild_id = {_GUILD_ID}",
    ),
    (
        "guild_memberships",
        "guild_memberships_select",
        "FOR SELECT",
        f"guild_id = {_GUILD_ID} OR user_id = {_USER_ID}",
        None,
    ),
    (
        "guild_memberships",
        "guild_memberships_insert",
        "FOR INSERT",
        None,
        f"guild_id = {_GUILD_ID}",
    ),
    (
        "guild_memberships",
        "guild_memberships_update",
        "FOR UPDATE",
        f"guild_id = {_GUILD_ID}",
        f"guild_id = {_GUILD_ID}",
    ),
    (
        "guild_memberships",
        "guild_memberships_delete",
        "FOR DELETE",
        f"guild_id = {_GUILD_ID}",
        None,
    ),
    (
        "user_view_preferences",
        "user_view_preferences_self_scope",
        "",
        f"user_id = {_USER_ID}",
        f"user_id = {_USER_ID}",
    ),
]


def _recreate(conn, superadmin_leg: bool) -> None:
    for table, policy, cmd, using, check in _POLICIES:
        conn.execute(text(f'DROP POLICY IF EXISTS "{policy}" ON public."{table}"'))
        parts = [f'CREATE POLICY "{policy}" ON public."{table}" {cmd}'.rstrip()]
        if using is not None:
            leg = f" OR ({_SUPERADMIN_LEG})" if superadmin_leg else ""
            parts.append(f"USING (({using}){leg})")
        if check is not None:
            leg = f" OR ({_SUPERADMIN_LEG})" if superadmin_leg else ""
            parts.append(f"WITH CHECK (({check}){leg})")
        conn.execute(text(" ".join(parts)))


def upgrade() -> None:
    _recreate(op.get_bind(), superadmin_leg=False)


def downgrade() -> None:
    _recreate(op.get_bind(), superadmin_leg=True)
