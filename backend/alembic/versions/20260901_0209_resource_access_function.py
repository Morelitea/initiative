"""add public.resource_access for the sharing gate

The per-resource sharing decision, as a SQL function the policies can call —
the same shape as ``public.initiative_access`` for initiative membership. It
resolves ``resource_grants`` and ``initiative_members`` through the caller's
search_path, so it answers within whichever guild schema the request is routed
to, and it is not SECURITY DEFINER.

Creating it does not change any policy. The rendered RLS picks it up on the
next boot.

Revision ID: 20260901_0209
Revises: 20260901_0208
Create Date: 2026-09-01
"""

from alembic import op

revision = "20260901_0209"
down_revision = "20260901_0208"
branch_labels = None
depends_on = None

RESOURCE_ACCESS_FN = """
CREATE OR REPLACE FUNCTION public.resource_access(
    p_tool          text,
    p_resource_id   integer,
    p_user_id       integer,
    p_initiative_id integer DEFAULT NULL,
    p_need_write    boolean DEFAULT false
) RETURNS boolean
    LANGUAGE sql STABLE
    AS $$
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
              )
        )
$$;
"""


def upgrade() -> None:
    # The body names guild-schema tables, which no schema on this search_path
    # has — it resolves them through the caller's at run time, as
    # public.initiative_access does.
    op.execute("SET LOCAL check_function_bodies = false")
    op.execute(RESOURCE_ACCESS_FN)


def downgrade() -> None:
    op.execute(
        "DROP FUNCTION IF EXISTS public.resource_access("
        "text, integer, integer, integer, boolean)"
    )
