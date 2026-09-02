"""Publish the public projection of ``public.users`` as a view.

A profile is public — the handle, the face, the status, the look, the join
date — and the rest of the row is not. ``public.users`` is own-row for a
platform-tier session, so the row cannot be read whole on the request path,
which left the choice of *which columns are public* to be made in Python.

It is made in the catalog instead:

* ``app_profile_reader`` is a NOLOGIN role holding **column-scoped** SELECT on
  ``public.users`` — the eight public columns and no others — plus an all-rows
  SELECT policy, because a profile is everyone's to read.
* ``public.user_profiles`` is a view over those columns, owned by that role.
  A view runs with its owner's privileges (``security_invoker`` is off by
  default), so reading it yields those columns for any account and nothing
  else. No role involved holds BYPASSRLS.
* The request path is granted SELECT on the view and nothing more. The schema's
  default privileges cover views as well as tables, so the write verbs they
  would otherwise confer are wound back first.

The endpoint then runs on an ordinary RLS-enforced platform-tier session.

Revision ID: 20260902_0214
Revises: 20260902_0213
Create Date: 2026-09-02
"""

from alembic import op

from app.core.config import settings

revision = "20260902_0214"
down_revision = "20260902_0213"
branch_labels = None
depends_on = None

#: The reader role. Unprefixed, like the other cluster-wide base roles
#: (``app_user``, ``app_admin``, ``app_guild_base``).
READER = "app_profile_reader"

#: What is public about an account. The view's column list and the reader's
#: column grant are the same list, and it is the only place it is written.
PUBLIC_COLUMNS = (
    "id",
    "username",
    "discriminator",
    "avatar_url",
    "status",
    "custom_status",
    "profile_decorations",
    "created_at",
)


def _platform_base() -> str:
    return f"{settings.PLATFORM_ROLE_PREFIX}platform_base"


def upgrade() -> None:
    columns = ", ".join(PUBLIC_COLUMNS)
    base = _platform_base()
    statements = [
        f"""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{READER}') THEN
                CREATE ROLE "{READER}" NOLOGIN;
            END IF;
        END $$;
        """,
        # Handing an object to a role means being able to become it, and then
        # acting as it to set the object's own grants. A CREATEROLE role gets
        # ADMIN on a role it creates but neither SET nor INHERIT, so
        # ``app_provisioner`` is given both explicitly — migrations run as that
        # role, not as a superuser. (Postgres 16+ syntax; this project runs 17.)
        f'GRANT "{READER}" TO CURRENT_USER WITH INHERIT TRUE, SET TRUE',
        # The reader sees these columns of every row, and nothing else of any.
        f"GRANT USAGE ON SCHEMA public TO {READER}",
        f"GRANT SELECT ({columns}) ON TABLE public.users TO {READER}",
        "DROP POLICY IF EXISTS users_profile_read ON public.users",
        f"CREATE POLICY users_profile_read ON public.users "
        f"AS PERMISSIVE FOR SELECT TO {READER} USING (true)",
        f"CREATE OR REPLACE VIEW public.user_profiles AS "
        f"SELECT {columns} FROM public.users",
        # Ownership can only be handed to a role that may create in the schema.
        # Given for the assignment and taken straight back: the reader creates
        # nothing, it only reads.
        f"GRANT CREATE ON SCHEMA public TO {READER}",
        f"ALTER VIEW public.user_profiles OWNER TO {READER}",
        f"REVOKE CREATE ON SCHEMA public FROM {READER}",
        # Default privileges in this schema cover views too, so the write verbs
        # they grant are taken back before the read is given.
        f'REVOKE ALL ON public.user_profiles FROM app_guild_base, "{base}", app_user',
        f'GRANT SELECT ON public.user_profiles TO "{base}"',
    ]
    for statement in statements:
        op.execute(statement)


def downgrade() -> None:
    statements = [
        "DROP VIEW IF EXISTS public.user_profiles",
        "DROP POLICY IF EXISTS users_profile_read ON public.users",
        f"REVOKE ALL ON TABLE public.users FROM {READER}",
        f"REVOKE USAGE ON SCHEMA public FROM {READER}",
        # The revokes above are this database's whole dependence on the role.
        # The role itself is cluster-global, so another database may still
        # grant to it — a second checkout's dev database, or the sibling
        # databases a parallel test run owns — and DROP ROLE refuses while any
        # of them does. That is somebody else's grant to give up, not this
        # downgrade's to force, so the drop is best-effort.
        f"""
        DO $$
        BEGIN
            DROP ROLE IF EXISTS "{READER}";
        EXCEPTION WHEN dependent_objects_still_exist THEN
            NULL;
        END
        $$
        """,
    ]
    for statement in statements:
        op.execute(statement)
