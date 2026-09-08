"""add public.initiative_role_permits for the initiative-role gate

Gate 3, as a SQL function the policies can call — the same shape as
``public.initiative_access`` for membership and ``public.resource_access`` for
sharing. It resolves ``initiative_members`` and ``initiative_role_permissions``
through the caller's search_path, so it answers within whichever guild schema
the request is routed to, and it is not SECURITY DEFINER.

The fallback is the part that matters, and it is two rules rather than one: a
manager role holds every key whether or not a row says so, and any other role
with no row for a key takes the default the application uses
(``DEFAULT_PERMISSION_VALUES`` — viewing a core tool is allowed, viewing an
opt-in tool is not, and creating anything is not). The caller passes that
default, because it is a property of the tool rather than of the role. Both
rules are ``rls._role_grants`` read in SQL.

Creating it does not change any policy. The rendered RLS picks it up on the
next boot.

Revision ID: 20260908_0238
Revises: 20260907_0237
Create Date: 2026-09-08
"""

from alembic import op

revision = "20260908_0238"
down_revision = "20260907_0237"
branch_labels = None
depends_on = None

ROLE_PERMITS_FN = """
CREATE OR REPLACE FUNCTION public.initiative_role_permits(
    p_initiative_id integer,
    p_user_id       integer,
    p_key           text,
    p_default       boolean
) RETURNS boolean
    LANGUAGE sql STABLE
    AS $$
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
$$;
"""


def upgrade() -> None:
    # The body names guild-schema tables, which no schema on this search_path
    # has — it resolves them through the caller's at run time, as
    # public.initiative_access does.
    op.execute("SET LOCAL check_function_bodies = false")
    op.execute(ROLE_PERMITS_FN)


#: What the function answers once the gate is rolled back. Every guild schema's
#: policies call it by then, and PostgreSQL will not drop a function they depend
#: on — so the downgrade replaces the body rather than removing the object. The
#: answer becomes the one the policies gave before this revision, and the next
#: boot, rendering from the reverted registry, stops calling it at all.
ROLE_PERMITS_FN_OPEN = """
CREATE OR REPLACE FUNCTION public.initiative_role_permits(
    p_initiative_id integer,
    p_user_id       integer,
    p_key           text,
    p_default       boolean
) RETURNS boolean
    LANGUAGE sql IMMUTABLE
    AS $$ SELECT true $$;
"""


def downgrade() -> None:
    op.execute(ROLE_PERMITS_FN_OPEN)
