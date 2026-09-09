"""let a read be narrowed to one initiative

A guild-scoped surface asks a guild-scoped question. Dashboards are an
initiative's tool, so a widget on one has to get its own initiative's answer
rather than every initiative its reader happens to belong to.

The narrowing is one leg on the function every initiative-scoped policy already
defers to, so it reaches every such table from the one declaration — including
the ones added after this. It only ever removes rows: unset, the leg is true and
nothing changes; set, rows belonging to another initiative are not part of the
answer. Guild-level rows, which belong to no initiative, stay in scope.

Revision ID: 20260909_0242
Revises: 20260909_0241
Create Date: 2026-09-09
"""

from alembic import op

revision = "20260909_0242"
down_revision = "20260909_0241"
branch_labels = None
depends_on = None


#: The read scope, NULLIF-guarded so an unset context yields NULL rather than
#: faulting the cast for every row on the table.
_SCOPE = (
    "NULLIF(current_setting('app.scope_initiative_id'::text, true), ''::text)::integer"
)

#: The access rule, with the narrowing leg. Everything else is unchanged from
#: the prior definition (20260812_0165).
INITIATIVE_ACCESS_FN = f"""
CREATE OR REPLACE FUNCTION public.initiative_access(
    p_initiative_id integer, p_user_id integer, p_need_write boolean DEFAULT false
) RETURNS boolean
    LANGUAGE sql STABLE
    AS $$
    SELECT
        public.guild_auth_satisfied()
        AND (
            -- The read's own scope, when the surface asking has one. A row of
            -- another initiative is not the answer to the question, whatever
            -- else the context allows. Guild-level rows belong to no
            -- initiative and stay in scope.
            p_initiative_id IS NULL
            OR {_SCOPE} IS NULL
            OR p_initiative_id = {_SCOPE}
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
$$;
"""

#: The definition this replaces, restored on downgrade (20260812_0165).
INITIATIVE_ACCESS_FN_PRIOR = """
CREATE OR REPLACE FUNCTION public.initiative_access(
    p_initiative_id integer, p_user_id integer, p_need_write boolean DEFAULT false
) RETURNS boolean
    LANGUAGE sql STABLE
    AS $$
    SELECT
        public.guild_auth_satisfied()
        AND (
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
$$;
"""


def upgrade() -> None:
    # One function in ``public``, replaced once. The policies that call it are
    # unchanged, so no guild schema needs re-rendering. The body names
    # ``initiative_members`` unqualified because it resolves per call through
    # the routed search_path; at migration time no guild schema is on the path,
    # so body validation is deferred (as in 20260812_0165).
    op.execute("SET LOCAL check_function_bodies = false")
    op.execute(INITIATIVE_ACCESS_FN)


def downgrade() -> None:
    op.execute("SET LOCAL check_function_bodies = false")
    op.execute(INITIATIVE_ACCESS_FN_PRIOR)
