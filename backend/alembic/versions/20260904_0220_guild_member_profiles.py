"""Publish the projection of ``public.users`` a guild-routed request reads.

Migration 0214 made the choice of *which columns are public* a catalog fact for
the cross-guild profile page: ``app_profile_reader`` holds a column-scoped
SELECT on ``public.users``, and ``public.user_profiles`` is a view over those
columns owned by that role. The guild path was left reading the table.

This adds the second view. ``public.guild_member_profiles`` carries the same
columns plus ``full_name``, because a guild is where colleagues are named and
the profile page is not in one. It is owned by the same reader role, so reading
it yields those columns for any account and nothing else, and it is granted to
``app_guild_base`` — what every ``guild_<id>`` and ``guild_<id>_ro`` role
inherits its shared-table access from.

The grants on ``public.users`` itself are not touched here. Repointing the
guild path onto this view comes first; the revoke is its own migration, so
each half can be deployed and rolled back on its own.

Revision ID: 20260904_0220
Revises: 20260904_0219
Create Date: 2026-09-02
"""

from alembic import op

from app.core.config import settings

revision = "20260904_0220"
down_revision = "20260904_0219"
branch_labels = None
depends_on = None

#: The reader role that owns both projections. Created in 0214.
READER = "app_profile_reader"

#: What a guild-routed request may read of somebody: the public profile (0214)
#: plus the real name. Written out here rather than imported so a replay of
#: this revision builds the view this revision built.
GUILD_MEMBER_COLUMNS = (
    "id",
    "username",
    "discriminator",
    "full_name",
    "avatar_url",
    "status",
    "custom_status",
    "profile_decorations",
    "created_at",
)

VIEW = "public.guild_member_profiles"


def _platform_base() -> str:
    return f"{settings.PLATFORM_ROLE_PREFIX}platform_base"


def upgrade() -> None:
    columns = ", ".join(GUILD_MEMBER_COLUMNS)
    base = _platform_base()
    statements = [
        # Migrations run as ``app_provisioner``, not as a superuser, and
        # handing an object to a role means being able to become it. 0214
        # granted this already; re-issued because this revision also assigns
        # ownership and must not depend on that one's side effects.
        f'GRANT "{READER}" TO CURRENT_USER WITH INHERIT TRUE, SET TRUE',
        # The reader's column grant grows by exactly one column.
        f"GRANT SELECT (full_name) ON TABLE public.users TO {READER}",
        f"CREATE OR REPLACE VIEW {VIEW} AS SELECT {columns} FROM public.users",
        # Ownership can only be handed to a role that may create in the schema.
        # Given for the assignment and taken straight back: the reader creates
        # nothing, it only reads.
        f"GRANT CREATE ON SCHEMA public TO {READER}",
        f"ALTER VIEW {VIEW} OWNER TO {READER}",
        f"REVOKE CREATE ON SCHEMA public FROM {READER}",
        # Default privileges in this schema cover views too, so the write verbs
        # they grant are taken back before the read is given. ``platform_base``
        # is left out on purpose: the cross-guild profile page reads
        # ``user_profiles``, which has no name in it.
        f'REVOKE ALL ON {VIEW} FROM app_guild_base, "{base}", app_user',
        f"GRANT SELECT ON {VIEW} TO app_guild_base",
    ]
    for statement in statements:
        op.execute(statement)


def downgrade() -> None:
    statements = [
        f"DROP VIEW IF EXISTS {VIEW}",
        f"REVOKE SELECT (full_name) ON TABLE public.users FROM {READER}",
    ]
    for statement in statements:
        op.execute(statement)
