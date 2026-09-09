"""Give the guild projection a name only where the guild asked for one.

``public.guild_member_profiles`` (0220) is what a guild-routed session reads a
person from. It carried ``full_name`` for every guild, and which guilds render
a real name was decided afterwards, in Python.

The view reads the decision itself now. ``app.guild_shows_member_names`` is set
with the rest of the request's context (``set_rls_context``) from the guild's
own ``show_member_names`` column, and the projection answers with a name only
where that says so. Unset — anything not routed into a guild — is no name.

The column list, the ownership and the grants are unchanged; only the
expression behind ``full_name`` moves.

Revision ID: 20260909_0243
Revises: 20260909_0242
Create Date: 2026-09-09
"""

from alembic import op

revision = "20260909_0243"
down_revision = "20260909_0242"
branch_labels = None
depends_on = None

#: The reader role that owns the projection. Created in 0214.
READER = "app_profile_reader"

VIEW = "public.guild_member_profiles"

#: Set per transaction beside the rest of the request context.
SETTING = "app.guild_shows_member_names"

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


def _view(name_expression: str) -> str:
    columns = ", ".join((*BEFORE, name_expression, *AFTER))
    return f"CREATE OR REPLACE VIEW {VIEW} AS SELECT {columns} FROM public.users"


def upgrade() -> None:
    # Replacing a view means owning it. 0214 and 0220 granted this already;
    # re-issued so this revision does not depend on their side effects.
    op.execute(f'GRANT "{READER}" TO CURRENT_USER WITH INHERIT TRUE, SET TRUE')
    op.execute(
        _view(
            f"CASE WHEN current_setting('{SETTING}', true) = 'true' "
            "THEN full_name END AS full_name"
        )
    )


def downgrade() -> None:
    op.execute(f'GRANT "{READER}" TO CURRENT_USER WITH INHERIT TRUE, SET TRUE')
    op.execute(_view("full_name"))
