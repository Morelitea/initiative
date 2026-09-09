"""``resource_access`` answers for a dashboard's own fetch

One leg, guarded by ``app.via_dashboard_id``. A grant whose grantee is a
dashboard (0246) answers only while the request is drawing that dashboard: the
setting is written by the path that runs a placed widget's stored statement,
after that dashboard's own four gates have admitted the reader.

Two bounds are in the leg itself rather than in the caller:

* ``NOT p_need_write`` — a dashboard reads and never writes, so this can never
  satisfy a write even if a row were somehow written at another level.
* the setting is compared to the grant's own ``dashboard_id``, so a grant made
  for one dashboard says nothing while another is being drawn.

Everything else is unchanged, including the order of the legs.

Revision ID: 20260909_0247
Revises: 20260909_0246
Create Date: 2026-09-09
"""

from alembic import op

revision = "20260909_0247"
down_revision = "20260909_0246"
branch_labels = None
depends_on = None

#: NULLIF-guarded, like every other setting a policy reads: unset is empty, and
#: a bare ''::int would raise for every row of every query on the table.
_VIA_DASHBOARD = "NULLIF(current_setting('app.via_dashboard_id'::text, true), '')::int"

_DASHBOARD_LEG = f"""
                OR (NOT p_need_write
                    AND g.dashboard_id IS NOT NULL
                    AND g.dashboard_id = {_VIA_DASHBOARD})"""


def _fn(*, through_dashboard: bool) -> str:
    """The function body, with and without the published-view leg."""
    dashboard_leg = _DASHBOARD_LEG if through_dashboard else ""
    return f"""
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
                            ))){dashboard_leg}
              )
        )
$$;
"""


def upgrade() -> None:
    # The body names guild-schema tables, which no schema on this search_path
    # has — it resolves them through the caller's at run time, as
    # public.initiative_access does.
    op.execute("SET LOCAL check_function_bodies = false")
    op.execute(_fn(through_dashboard=True))


def downgrade() -> None:
    op.execute("SET LOCAL check_function_bodies = false")
    op.execute(_fn(through_dashboard=False))
