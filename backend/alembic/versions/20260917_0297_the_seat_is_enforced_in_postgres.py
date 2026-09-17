"""Only the seat writes a community's sign-in requirement, and Postgres says so.

``guild_auth_policies`` was readable by the request path and written on the
system engine. The write moves onto the request path here, where a policy
decides it.

Three things:

* ``public.guild_superadmin(guild_id, user_id)`` — the rule at this revision.
  The live definition remains in ``app.db.authorization`` and is re-applied on
  every boot.
* ``app_guild_base`` gains INSERT/UPDATE/DELETE, so a guild-routed session can
  reach the table at all. It is not granted to ``app_user``: an unrouted
  session stays unable to write one, which is where a request that never
  named a guild belongs.
* One policy per write verb, each requiring the row to belong to the addressed
  guild *and* the writer to hold its seat.

``auth_providers`` and ``auth_provider_secrets`` are untouched: the request
path still reaches neither. A requirement names a provider, and the write that
names it carries a foreign key to that row — which is what keeps the row still
while the write commits, without the request path ever reading the registry.

The SELECT policy is untouched. ``guild_auth_satisfied()`` reads this table on
the guild-access path for every request, and that read is not the seat's.

Revision ID: 20260917_0297
Revises: 20260917_0296
Create Date: 2026-09-17
"""

from alembic import op

revision = "20260917_0297"
down_revision = "20260917_0296"
branch_labels = None
depends_on = None


_GUILD_SUPERADMIN = """\
CREATE OR REPLACE FUNCTION public.guild_superadmin(p_guild_id integer, p_user_id integer)
 RETURNS boolean
 LANGUAGE sql
 STABLE
AS $function$
    SELECT EXISTS (
        SELECT 1
        FROM public.guild_memberships m
        WHERE m.guild_id = p_guild_id
          AND m.user_id = p_user_id
          AND m.role = 'superadmin'
    )
$function$

"""


_GUILD = "guild_id = NULLIF(current_setting('app.current_guild_id', true), '')::int"
_SEAT = (
    "public.guild_superadmin("
    "guild_id, NULLIF(current_setting('app.current_user_id', true), '')::int)"
)
_WRITER = f"({_GUILD} AND {_SEAT})"

_POLICIES = (
    ("guild_auth_policies_seat_insert", "INSERT", f"WITH CHECK {_WRITER}"),
    (
        "guild_auth_policies_seat_update",
        "UPDATE",
        f"USING {_WRITER} WITH CHECK {_WRITER}",
    ),
    ("guild_auth_policies_seat_delete", "DELETE", f"USING {_WRITER}"),
)


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return

    op.execute("SET LOCAL check_function_bodies = false")
    op.execute(_GUILD_SUPERADMIN)

    op.execute(
        "GRANT INSERT, UPDATE, DELETE ON public.guild_auth_policies TO app_guild_base"
    )
    for name, cmd, clause in _POLICIES:
        op.execute(
            f"CREATE POLICY {name} ON public.guild_auth_policies "
            f"FOR {cmd} TO public {clause}"
        )


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return

    for name, _cmd, _clause in _POLICIES:
        op.execute(f"DROP POLICY IF EXISTS {name} ON public.guild_auth_policies")
    op.execute(
        "REVOKE INSERT, UPDATE, DELETE ON public.guild_auth_policies FROM app_guild_base"
    )
    op.execute("DROP FUNCTION IF EXISTS public.guild_superadmin(integer, integer)")
