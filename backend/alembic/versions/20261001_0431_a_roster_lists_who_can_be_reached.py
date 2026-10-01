"""A roster lists who can be reached

The sidebar's people roster leaves out anyone whose direct message policy is
``private``. That policy is the account holder's own row, which no guild role
reads, so this adds a function that answers the one question the roster asks:
which members of the routed guild are not private.

Owned by ``app_dm_reader``, which already reads ``guild_memberships`` and
``user_dm_settings``, so nothing new is granted to it. Which guild is not a
parameter: it is the one the request is routed into, read the way
``current_guild_members`` (0244) reads it. Unset, it matches nothing.

Callable by the two guild floors and nothing else.

Revision ID: 20261001_0431
Revises: 20261001_0430
Create Date: 2026-10-01
"""

from alembic import op

revision = "20261001_0431"
down_revision = "20261001_0430"
branch_labels = None
depends_on = None

READER = "app_dm_reader"

FUNCTION = "public.roster_listed_members()"

#: The floors every guild role reads shared relations through.
FLOORS = ("app_guild_base", "app_guild_base_ro")

#: The guild this request is in. A grantee routes by the grant instead, and
#: NULLIF-guards the cast so an unset context yields NULL rather than faulting.
_GUILD = (
    "COALESCE("
    "NULLIF(current_setting('app.current_guild_id', true), '')::integer, "
    "NULLIF(current_setting('app.pam_guild_id', true), '')::integer)"
)


def upgrade() -> None:
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION {FUNCTION}
        RETURNS SETOF int
        LANGUAGE sql STABLE PARALLEL SAFE SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $fn$
          SELECT m.user_id
          FROM public.guild_memberships m
          JOIN public.user_dm_settings s ON s.user_id = m.user_id
          WHERE m.guild_id = {_GUILD}
            AND s.dm_policy <> 'private'
        $fn$
        """
    )
    # Ownership can only be handed to a role that may create in the schema.
    # Given for the assignment and taken straight back: the reader creates
    # nothing, it only reads.
    op.execute(f'GRANT CREATE ON SCHEMA public TO "{READER}"')
    op.execute(f'ALTER FUNCTION {FUNCTION} OWNER TO "{READER}"')
    op.execute(f'REVOKE CREATE ON SCHEMA public FROM "{READER}"')
    op.execute(f"REVOKE ALL ON FUNCTION {FUNCTION} FROM PUBLIC")
    for floor in FLOORS:
        op.execute(f'GRANT EXECUTE ON FUNCTION {FUNCTION} TO "{floor}"')


def downgrade() -> None:
    op.execute(f"DROP FUNCTION IF EXISTS {FUNCTION}")
