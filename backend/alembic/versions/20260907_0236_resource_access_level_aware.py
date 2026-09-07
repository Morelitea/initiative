"""teach public.resource_access the grant's level

``p_need_write`` steered only the PAM leg: a grant admitted a row whatever level
it was issued at, so the write answer matched the read one. The app layer has
always read the level (``permissions.WRITE_LEVELS``); this brings the function to
the same answer, so a write policy and ``require_access`` decide alike.

Read is unchanged — every grant still admits a row a listing may show.

Same signature, so this is a plain replacement: no policy or default needs
redeclaring, and the rendered RLS picks the new body up immediately.

Revision ID: 20260907_0236
Revises: 20260907_0233
Create Date: 2026-09-07
"""

from alembic import op

revision = "20260907_0236"
down_revision = "20260907_0233"
branch_labels = None
depends_on = None


def _fn(*, level_aware: bool) -> str:
    """The function body, with and without the grant-level leg."""
    level_leg = (
        "AND (NOT p_need_write OR g.level IN ('write', 'owner'))"
        if level_aware
        else ""
    )
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
              {level_leg}
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
    op.execute(_fn(level_aware=True))


def downgrade() -> None:
    op.execute("SET LOCAL check_function_bodies = false")
    op.execute(_fn(level_aware=False))
