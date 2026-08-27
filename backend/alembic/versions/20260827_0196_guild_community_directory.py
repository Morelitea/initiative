"""add the community-directory columns to guilds

A guild that opts in is listed in the signed-in community directory and can be
joined without an invite. The opt-in, its subject tags, and its 18+ declaration
are guild identity — the guild's own admins set them from their settings page —
so they live on ``public.guilds`` beside name/description/icon rather than on
the operator-owned ``guild_administration`` row, and the column-scoped UPDATE
grant added in 0138 is widened to cover them.

``categories`` is a ``text[]`` with a CHECK that every element is a known
category, mirroring how ``status`` is a CHECK-constrained string rather than a
Postgres enum: adding a category later is an ordinary migration.

Two more CHECKs make the listing rules database invariants rather than app
rules, so no path can publish a guild that breaks them:

* a listed guild is on at least one shelf, and
* a listed guild has declared itself free of adult content. ``IS FALSE`` is
  false for NULL as well as for true, so the unanswered default is refused by
  the same predicate that refuses an 18+ guild.

The third rule — a guild whose seat cap is 1 can never take a joiner, so it is
never listed — cannot be a CHECK here: the cap lives on ``guild_administration``
and an operator can lower it after the fact. That one is enforced when the
listing is set and again when the directory is read.
"""

import sqlalchemy as sa
from alembic import op

revision = "20260827_0196"
down_revision = "20260826_0195"
branch_labels = None
depends_on = None

# Spelled out rather than read from ``GuildCategory``: a revision must state
# what it writes, so that adding a category later changes the next migration
# rather than reaching back and changing what this one does.
_CATEGORY_LITERALS = ", ".join(
    f"'{value}'"
    for value in (
        "art",
        "gaming",
        "ttrpg",
        "music",
        "writing",
        "education",
        "technology",
        "sports",
        "business",
        "health",
        "social",
        "other",
    )
)

# Widened from 0138: the three directory columns join the identity columns a
# guild's own admin edits through PATCH /guilds/{guild_id}.
_GUILD_ADMIN_COLUMNS = (
    "name, description, icon_base64, is_community, categories, "
    "has_adult_content, updated_at"
)


def upgrade() -> None:
    op.add_column(
        "guilds",
        sa.Column(
            "is_community",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "guilds",
        sa.Column(
            "categories",
            sa.ARRAY(sa.String(length=32)),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
    )
    # Nullable with no default: unanswered is the normal state for a guild that
    # never lists itself, and is distinct from an answer of "no".
    op.add_column(
        "guilds",
        sa.Column("has_adult_content", sa.Boolean(), nullable=True),
    )
    op.create_check_constraint(
        "ck_guilds_categories",
        "guilds",
        f"categories <@ ARRAY[{_CATEGORY_LITERALS}]::varchar[]",
    )
    op.create_check_constraint(
        "ck_guilds_community_categories",
        "guilds",
        "NOT is_community OR cardinality(categories) > 0",
    )
    op.create_check_constraint(
        "ck_guilds_community_adult_content",
        "guilds",
        "NOT is_community OR has_adult_content IS FALSE",
    )
    # The directory's only query shape: listed guilds, optionally narrowed to
    # one category. Partial on the opt-in so it stays the size of the directory
    # rather than the size of the deployment.
    op.execute(
        "CREATE INDEX ix_guilds_community_categories ON public.guilds "
        "USING gin (categories) WHERE is_community"
    )
    op.execute("REVOKE UPDATE ON TABLE public.guilds FROM app_guild_base")
    op.execute(
        f"GRANT UPDATE ({_GUILD_ADMIN_COLUMNS}) ON TABLE public.guilds "
        "TO app_guild_base"
    )


def downgrade() -> None:
    op.execute("REVOKE UPDATE ON TABLE public.guilds FROM app_guild_base")
    op.execute(
        "GRANT UPDATE (name, description, icon_base64, updated_at) "
        "ON TABLE public.guilds TO app_guild_base"
    )
    op.execute("DROP INDEX IF EXISTS public.ix_guilds_community_categories")
    op.drop_constraint("ck_guilds_community_adult_content", "guilds", type_="check")
    op.drop_constraint("ck_guilds_community_categories", "guilds", type_="check")
    op.drop_constraint("ck_guilds_categories", "guilds", type_="check")
    op.drop_column("guilds", "has_adult_content")
    op.drop_column("guilds", "categories")
    op.drop_column("guilds", "is_community")
