"""Guilds show real names by default, and their own admin can say otherwise.

Two halves of the same setting, both missing from 0203:

* The write path. 0138 pinned the guild-admin grant on ``public.guilds`` to a
  literal column list, so every column added since names itself — 0196 did it
  for the directory columns, 0200 for the banner.
* The default. Names on is what a private workspace expects; a guild listed in
  the community directory is still handles-only, which
  ``ck_guilds_community_member_names`` keeps structural.
"""

import sqlalchemy as sa
from alembic import op

revision = "20260830_0206"
down_revision = "20260829_0205"
branch_labels = None
depends_on = None


def _set_default(value: str) -> None:
    # Default only. The column is NOT NULL from 0203 and stays that way —
    # ``existing_nullable`` says so rather than leaving it to be inferred.
    op.alter_column(
        "guilds",
        "show_member_names",
        existing_type=sa.Boolean(),
        existing_nullable=False,
        server_default=sa.text(value),
    )


def upgrade() -> None:
    op.execute(
        "GRANT UPDATE (show_member_names) ON TABLE public.guilds TO app_guild_base"
    )
    _set_default("true")
    # Every guild that existed before this revision took the old default, and
    # none of them was ever asked. Listed guilds keep handles — the CHECK
    # constraint says so, and this write agrees with it rather than testing it.
    #
    # The write is set up the way the other ``public.guilds`` backfills in this
    # directory are (see 0196, 0200).
    conn = op.get_bind()
    op.execute("ALTER TABLE public.guilds NO FORCE ROW LEVEL SECURITY")
    try:
        result = conn.execute(
            sa.text(
                "UPDATE public.guilds SET show_member_names = true "
                "WHERE is_community = false AND show_member_names = false"
            )
        )
    finally:
        op.execute("ALTER TABLE public.guilds FORCE ROW LEVEL SECURITY")
    print(f"  show_member_names turned on for {result.rowcount} guild(s)")


def downgrade() -> None:
    _set_default("false")
    op.execute(
        "REVOKE UPDATE (show_member_names) ON TABLE public.guilds FROM app_guild_base"
    )
