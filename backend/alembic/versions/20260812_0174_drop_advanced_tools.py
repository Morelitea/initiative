"""drop the advanced tool

The automation service now stores the graph an automation IS alongside the
schedule that fires it, so it owns both halves and there is no remote row for
us to hold. With the storage goes the whole surface: the tables, the role
permissions and master switch that gated it, the ``embed`` app kind that
existed for its one target, and its catalog listing.

Nothing replaces it here. When the automation service registers as an ordinary
app it will arrive through the app platform — a registration supplying the URL
and the key, embeds resolved from its manifest — which is a general mechanism
rather than a slot shaped like one integration.

Two kinds of DML need forcing lifted first: the polymorphic
``resource_grants`` rows that shared an advanced tool, and the stored role
permissions. Both tables FORCE row-level security, so the migration role owns
them and is still policy-bound, and the request GUCs the policies read are
unset here — a naive DELETE would match nothing and say so silently.

Revision ID: 20260812_0174
Revises: 20260812_0173
Create Date: 2026-08-12
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20260812_0174"
down_revision = "20260812_0173"
branch_labels = None
depends_on = None


#: The listing's stable uid, from the manifest this migration also removes.
_LISTING_UID = "T9PZ3KVD6BWRSN"

_PERMISSION_KEYS = ("advanced_tools_enabled", "create_advanced_tools")

#: Permission keys the CHECK accepts afterwards — every tool's pair, and
#: nothing else. Spelled out rather than derived: a migration states the shape
#: of the database at its own revision, which must not move when the enum does.
_REMAINING_PERMISSION_KEYS = (
    "calendars_enabled",
    "counter_groups_enabled",
    "create_calendars",
    "create_counter_groups",
    "create_dashboards",
    "create_documents",
    "create_projects",
    "create_queues",
    "dashboards_enabled",
    "documents_enabled",
    "projects_enabled",
    "queues_enabled",
)

_CHECK_NAME = "ck_initiative_role_permissions_permission_key"


def _permission_check(keys: tuple[str, ...]) -> str:
    values = ", ".join(f"'{key}'" for key in sorted(keys))
    return (
        f"ALTER TABLE initiative_role_permissions ADD CONSTRAINT {_CHECK_NAME} "
        f"CHECK (permission_key IN ({values}))"
    )


def _delete_with_count(statement: str, remaining: str, what: str) -> None:
    op.execute(sa.text(statement))
    left = op.get_bind().execute(sa.text(remaining)).scalar()
    if left:
        raise RuntimeError(f"{left} {what} survived the delete — it was policy-bound")


def upgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_upgrade)

    # Public schema: the catalog row and its versions. Deleted rather than
    # marked unavailable — the kind it declares no longer exists, so there is
    # nothing an install of it could mount.
    op.execute(
        sa.text(
            "DELETE FROM marketplace_listing_versions WHERE listing_id IN "
            "(SELECT id FROM marketplace_listings WHERE uid = :uid)"
        ).bindparams(uid=_LISTING_UID)
    )
    op.execute(
        sa.text("DELETE FROM marketplace_listings WHERE uid = :uid").bindparams(
            uid=_LISTING_UID
        )
    )


def _apply_upgrade() -> None:
    # Installs of the listing, and anything else left on the retired kind.
    op.execute(sa.text("DELETE FROM guild_apps WHERE app_kind = 'embed'"))

    op.execute("ALTER TABLE resource_grants NO FORCE ROW LEVEL SECURITY")
    try:
        _delete_with_count(
            "DELETE FROM resource_grants WHERE resource_type = 'advanced_tool'",
            "SELECT count(*) FROM resource_grants WHERE resource_type = 'advanced_tool'",
            "advanced_tool grants",
        )
    finally:
        op.execute("ALTER TABLE resource_grants FORCE ROW LEVEL SECURITY")

    op.drop_table("advanced_tool_tags")
    op.drop_table("advanced_tools")

    # The role permissions and the master switch that gated the surface.
    keys = ", ".join(f"'{key}'" for key in _PERMISSION_KEYS)
    op.execute("ALTER TABLE initiative_role_permissions NO FORCE ROW LEVEL SECURITY")
    try:
        _delete_with_count(
            f"DELETE FROM initiative_role_permissions WHERE permission_key IN ({keys})",
            "SELECT count(*) FROM initiative_role_permissions WHERE "
            f"permission_key IN ({keys})",
            "advanced tool permissions",
        )
    finally:
        op.execute("ALTER TABLE initiative_role_permissions FORCE ROW LEVEL SECURITY")

    op.execute(f"ALTER TABLE initiative_role_permissions DROP CONSTRAINT {_CHECK_NAME}")
    op.execute(_permission_check(_REMAINING_PERMISSION_KEYS))

    with op.batch_alter_table("initiatives", schema=None) as batch_op:
        batch_op.drop_column("advanced_tools_enabled")


def downgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_downgrade)


def _apply_downgrade() -> None:
    # Structure only. The rows are gone and the automation service holds the
    # definitions now, so what comes back is an empty surface: no grants, no
    # permissions granted to anyone, no installs, no listing. RLS is enabled
    # and forced immediately so the tables are fail-closed until the
    # provisioning stamp backfill re-renders the initiative_member_* policies
    # from INITIATIVE_PATHS on the next boot — the same contract every
    # guild-schema migration relies on.
    with op.batch_alter_table("initiatives", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "advanced_tools_enabled",
                sa.Boolean(),
                server_default="false",
                nullable=False,
            )
        )

    op.execute(f"ALTER TABLE initiative_role_permissions DROP CONSTRAINT {_CHECK_NAME}")
    op.execute(_permission_check(_REMAINING_PERMISSION_KEYS + _PERMISSION_KEYS))

    op.create_table(
        "advanced_tools",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("guild_id", sa.Integer(), nullable=False),
        sa.Column("initiative_id", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column(
            "data",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column("created_by_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by", sa.Integer(), nullable=True),
        sa.Column("purge_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["guild_id"], ["guilds.id"]),
        sa.ForeignKeyConstraint(
            ["initiative_id"], ["initiatives.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("advanced_tools", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_advanced_tools_guild_id"), ["guild_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_advanced_tools_initiative_id"),
            ["initiative_id"],
            unique=False,
        )

    op.create_table(
        "advanced_tool_tags",
        sa.Column("advanced_tool_id", sa.Integer(), nullable=False),
        sa.Column("tag_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["advanced_tool_id"], ["advanced_tools.id"]),
        sa.ForeignKeyConstraint(["tag_id"], ["tags.id"]),
        sa.PrimaryKeyConstraint("advanced_tool_id", "tag_id"),
    )
    with op.batch_alter_table("advanced_tool_tags", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_advanced_tool_tags_tag_id"), ["tag_id"], unique=False
        )

    for table in ("advanced_tools", "advanced_tool_tags"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
