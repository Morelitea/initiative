"""A member names themselves per community

``guild_memberships.display_name`` is what a person is called in one
community, when they or its administrators choose to set it. NULL is the
usual case, and leaves the handle.

It is the only name a community shows. The projection
``public.guild_member_profiles`` answers with it in its ``full_name`` column in
place of the account's own name, which it no longer reads, and with it the
guild's ``show_member_names`` no longer decides anything there. Every surface
that already reads a person from the projection — a roster, a picker, a
mention, a byline, ``current_guild_members`` and its ``display_name`` — shows
it without asking. The membership row is read for the guild the request is
routed into, under the policy 0244 gave the reader for exactly that guild.

Who writes it:

* the member, for their own row: ``app_guild_base`` gains a column-scoped
  ``UPDATE (display_name)`` beside ``position``, under the own-row update
  policy every request role already has;
* the community's administrators, on the system engine, which already holds
  the table.

The view's body is restated in full; the downgrade restores 0386's.

Revision ID: 20261002_0438
Revises: 20261001_0437
Create Date: 2026-10-02
"""

from alembic import op

revision = "20261002_0438"
down_revision = "20261001_0437"
branch_labels = None
depends_on = None

#: The reader role that owns the projection. Created in 0214.
READER = "app_profile_reader"

PROFILES = "public.guild_member_profiles"

#: The longest name a member may give themselves.
MAX_LENGTH = 64

#: The guild the request is routed into, as 0281 reads it.
ROUTED_GUILD_ID = """COALESCE(
        NULLIF(current_setting('app.current_guild_id', true), '')::int,
        NULLIF(current_setting('app.pam_guild_id', true), '')::int
    )"""

#: Written out rather than imported so a replay of this revision builds the
#: view this revision built.
BEFORE = ("u.id", "u.username", "u.discriminator")
AFTER = (
    "u.avatar_url",
    "u.status",
    "u.custom_status",
    "u.profile_decorations",
    "u.created_at",
)

#: The member's own name in this community, and nothing else.
NAME = "m.display_name::varchar AS full_name"

#: 0386's install rule, unchanged.
INSTALL_READS_ITS_MEMBERS = f"""
    NULLIF(current_setting('app.current_install_id', true), '') IS NULL
    OR u.id IN (
        SELECT gm.user_id FROM public.guild_memberships gm
        WHERE gm.guild_id = {ROUTED_GUILD_ID}
    )"""

#: 0386's view, for the downgrade.
PREVIOUS_VIEW = f"""
CREATE OR REPLACE VIEW {PROFILES} AS
SELECT id, username, discriminator,
    CASE WHEN (
        SELECT g.show_member_names FROM public.guilds g WHERE g.id = {ROUTED_GUILD_ID}
    ) THEN full_name END AS full_name,
    avatar_url, status, custom_status, profile_decorations, created_at
FROM public.users
WHERE NULLIF(current_setting('app.current_install_id', true), '') IS NULL
    OR id IN (
        SELECT m.user_id FROM public.guild_memberships m
        WHERE m.guild_id = {ROUTED_GUILD_ID}
    )"""


def _view() -> str:
    columns = ", ".join((*BEFORE, NAME, *AFTER))
    return f"""
CREATE OR REPLACE VIEW {PROFILES} AS
SELECT {columns}
FROM public.users u
LEFT JOIN public.guild_memberships m
    ON m.user_id = u.id AND m.guild_id = {ROUTED_GUILD_ID}
WHERE {INSTALL_READS_ITS_MEMBERS}"""


def upgrade() -> None:
    op.execute(
        "ALTER TABLE public.guild_memberships "
        f"ADD COLUMN display_name varchar({MAX_LENGTH})"
    )
    op.execute(
        "GRANT UPDATE (display_name) ON TABLE public.guild_memberships "
        "TO app_guild_base"
    )
    op.execute(f'GRANT SELECT (display_name) ON public.guild_memberships TO "{READER}"')
    op.execute(f'GRANT "{READER}" TO CURRENT_USER WITH INHERIT TRUE, SET TRUE')
    op.execute(_view())


def downgrade() -> None:
    op.execute(f'GRANT "{READER}" TO CURRENT_USER WITH INHERIT TRUE, SET TRUE')
    op.execute(PREVIOUS_VIEW)
    op.execute(
        f'REVOKE SELECT (display_name) ON public.guild_memberships FROM "{READER}"'
    )
    op.execute(
        "REVOKE UPDATE (display_name) ON TABLE public.guild_memberships "
        "FROM app_guild_base"
    )
    op.execute("ALTER TABLE public.guild_memberships DROP COLUMN display_name")
