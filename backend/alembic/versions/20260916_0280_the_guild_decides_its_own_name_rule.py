"""The guild projection reads the name rule off the guild.

``public.guild_member_profiles`` (0243) answers with ``full_name`` only where
the guild renders real names. It learned that from
``app.guild_shows_member_names`` — a boolean the request handed in beside the
guild id, which meant two values describing one guild and nothing holding them
together.

The view reads ``public.guilds.show_member_names`` for the guild the request is
routed into, so the answer comes from the row that owns it.

The view runs with its owner's privileges, so the owner needs to be able to
read that column: ``app_profile_reader`` gains SELECT on exactly
``guilds(id, show_member_names)`` and a SELECT policy for those rows. It gains
nothing else, holds no write verb anywhere, and cannot log in — the same shape
it has had on ``public.users`` since 0214.

Revision ID: 20260916_0280
Revises: 20260916_0279
Create Date: 2026-09-16
"""

from alembic import op

revision = "20260916_0280"
down_revision = "20260916_0279"
branch_labels = None
depends_on = None

#: The reader role that owns the projection. Created in 0214.
READER = "app_profile_reader"

VIEW = "public.guild_member_profiles"

#: Retired by this revision. Named so the downgrade can put it back.
SETTING = "app.guild_shows_member_names"

#: The guild the request is routed into.
CURRENT_GUILD_ID = "NULLIF(current_setting('app.current_guild_id', true), '')::int"

#: The columns either side of the name, in the order the view has had since
#: 0220. Written out rather than imported so a replay of this revision builds
#: the view this revision built.
BEFORE = ("id", "username", "discriminator")
AFTER = (
    "avatar_url",
    "status",
    "custom_status",
    "profile_decorations",
    "created_at",
)

#: Uncorrelated — it depends on the request's guild, not on the row being
#: projected — so it is evaluated once per statement rather than per member.
NAME_FROM_THE_GUILD = f"""CASE WHEN (
    SELECT g.show_member_names FROM public.guilds g WHERE g.id = {CURRENT_GUILD_ID}
) THEN full_name END AS full_name"""

NAME_FROM_THE_SETTING = f"CASE WHEN current_setting('{SETTING}', true) = 'true' THEN full_name END AS full_name"

POLICY = "profile_reader_reads_the_name_rule"


def _view(name_expression: str) -> str:
    columns = ", ".join((*BEFORE, name_expression, *AFTER))
    return f"CREATE OR REPLACE VIEW {VIEW} AS SELECT {columns} FROM public.users"


def upgrade() -> None:
    op.execute(f'GRANT "{READER}" TO CURRENT_USER WITH INHERIT TRUE, SET TRUE')
    # One column, read-only. The id comes with it because the lookup is by id.
    op.execute(f'GRANT SELECT (id, show_member_names) ON public.guilds TO "{READER}"')
    # ``guilds`` carries FORCE ROW LEVEL SECURITY, so a grant alone reads
    # nothing. ``guild_select`` is scoped to the request-path roles and keys on
    # membership, which this role has none of; it gets its own policy instead.
    op.execute(f"DROP POLICY IF EXISTS {POLICY} ON public.guilds")
    op.execute(
        f'CREATE POLICY {POLICY} ON public.guilds FOR SELECT TO "{READER}" USING (true)'
    )
    op.execute(_view(NAME_FROM_THE_GUILD))


def downgrade() -> None:
    op.execute(f'GRANT "{READER}" TO CURRENT_USER WITH INHERIT TRUE, SET TRUE')
    op.execute(_view(NAME_FROM_THE_SETTING))
    op.execute(f"DROP POLICY IF EXISTS {POLICY} ON public.guilds")
    op.execute(
        f'REVOKE SELECT (id, show_member_names) ON public.guilds FROM "{READER}"'
    )
