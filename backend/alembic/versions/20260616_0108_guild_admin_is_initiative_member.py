"""Guild admins count as a member of every initiative in their guild (RLS).

``is_initiative_member`` backs every initiative-scoped RESTRICTIVE policy
(SELECT / INSERT / UPDATE / DELETE on ``tasks`` and its children). A guild ADMIN
has full authority over their guild's content, so rather than bolt a guild-admin
clause onto each policy, admit guild admins in the ONE function: a session routed
into its own guild as admin (``app.current_guild_role = 'admin'``) is treated as a
member of every initiative there — uniformly for read AND write AND delete.

This is the load-bearing change behind running the trash hard-purge as the
routed guild-admin role instead of a standing-BYPASSRLS ``app_admin`` connection:
the guild admin now clears the initiative-member RESTRICTIVE DELETE policy.

Guild-admin status is derived from the canonical roster (``guild_memberships``)
joined through ``initiatives`` to the initiative's guild — NOT from an app-set
GUC like ``app.current_guild_role``. RLS decisions read the source-of-truth data
(the same place membership and PAM already resolve), keeping the rule centralized
and self-consistent rather than trusting a per-request session variable.

Revision ID: 20260616_0108
Revises: 20260616_0107
Create Date: 2026-06-16
"""

from alembic import op

revision = "20260616_0108"
down_revision = "20260616_0107"
branch_labels = None
depends_on = None

# Existing membership + PAM-read lookups (verbatim from migration 0093).
_MEMBER_AND_PAM = """
    SELECT EXISTS (
        SELECT 1 FROM initiative_members
        WHERE initiative_id = p_initiative_id AND user_id = p_user_id
    )
    OR (
        current_setting('app.pam_read', true) = 'true'
        AND EXISTS (
            SELECT 1 FROM initiatives i
            WHERE i.id = p_initiative_id
            AND i.guild_id = NULLIF(current_setting('app.pam_guild_id', true), '')::int
        )
    )
"""

# Guild admins are members of every initiative in their guild — derived from the
# canonical guild_memberships roster (same tables the membership/PAM checks read),
# not an app-set session GUC.
_GUILD_ADMIN_CLAUSE = """
    OR EXISTS (
        SELECT 1
        FROM initiatives i
        JOIN guild_memberships gm ON gm.guild_id = i.guild_id
        WHERE i.id = p_initiative_id
          AND gm.user_id = p_user_id
          AND gm.role = 'admin'
    )
"""


def _define(body: str) -> str:
    return f"""
        CREATE OR REPLACE FUNCTION public.is_initiative_member(
            p_initiative_id integer, p_user_id integer
        )
        RETURNS boolean
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path TO 'public'
        AS $function$ {body} $function$
    """


def upgrade() -> None:
    op.execute(_define(_MEMBER_AND_PAM + _GUILD_ADMIN_CLAUSE))


def downgrade() -> None:
    op.execute(_define(_MEMBER_AND_PAM))
