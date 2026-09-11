"""relationships: one table for how things connect

Creates the guild-content ``relationships`` table and moves the four attachment
junctions into it, then drops them.

Two things are created in ``public`` first, because the table depends on them:

``relationship_kind_code(text)``
    An IMMUTABLE function mapping an endpoint kind to its permanent code. The
    table's generated ``source_node`` / ``target_node`` columns call it, and a
    generated column may only use immutable expressions. It is a FUNCTION rather
    than an inlined CASE so that admitting a new endpoint kind later is a
    ``CREATE OR REPLACE`` — an inlined expression would make every new kind an
    ALTER that rewrites the table in every guild schema. Existing rows stay
    correct across such a replace because a kind's code never changes; that
    permanence rule (``app.core.relationships``) is what makes this safe, and
    ``relationships_test`` is what holds it.

``fn_relationships_set_guild_id()``
    Fills ``guild_id`` from whichever endpoint table the row names. RLS does not
    read that column — the schema is the tenant boundary — but cross-guild reads
    filter on it, so it is derived in the database where no write path can
    forget it. One CASE arm per kind, RAISE otherwise, as
    ``fn_recent_views_set_guild_id`` does.

The copy reads tables that have FORCE ROW LEVEL SECURITY, which binds even the
owner the migration runs as, and the policies key on request GUCs a migration
has no value for. So each source has FORCE lifted for the copy and the row
counts are asserted to match: a policy-bound copy moves nothing and reports
success, and a fresh install has nothing to copy, so CI would stay green while
every upgrade with data silently lost it.

Order is create -> backfill -> drop. RLS policies, grants and the
``created_by`` trigger are NOT written here: provisioning renders those from the
live ``guild_template`` and the registries, and the boot backfill re-applies
them to every guild whose stamp this revision made stale.

Revision ID: 20260910_0252
Revises: 20260910_0251
Create Date: 2026-09-10
"""

import sqlalchemy as sa
from alembic import op

from app.core.relationships import ENDPOINT_KINDS, NODE_ID_SHIFT
from app.db.guild_migrations import run_for_each_guild_schema

revision = "20260910_0252"
down_revision = "20260910_0251"
branch_labels = None
depends_on = None


#: The junctions, as (table, source column, source kind, target column, target
#: kind). Source and target are assigned by node-id order, not by the junction's
#: own column order, which carries no meaning: ``attached`` is symmetric, so the
#: row is stored once with the lower node id as source. The CHECK constraint
#: refuses anything else, so a mistake here fails the migration rather than
#: landing crooked data.
_JUNCTIONS: tuple[tuple[str, str, str, str, str], ...] = (
    ("project_documents", "document_id", "document", "project_id", "project"),
    ("queue_item_documents", "document_id", "document", "queue_item_id", "queue_item"),
    ("queue_item_tasks", "queue_item_id", "queue_item", "task_id", "task"),
    (
        "calendar_event_documents",
        "calendar_event_id",
        "calendar_event",
        "document_id",
        "document",
    ),
)


def _kind_code_fn() -> str:
    arms = " ".join(
        f"WHEN '{kind.value}' THEN {endpoint.code}"
        for kind, endpoint in ENDPOINT_KINDS.items()
    )
    return f"""
        CREATE OR REPLACE FUNCTION public.relationship_kind_code(kind text)
        RETURNS bigint LANGUAGE sql IMMUTABLE STRICT AS $$
            SELECT (CASE kind {arms} END)::bigint
        $$
    """


def _set_guild_id_fn() -> str:
    arms = "\n".join(
        f"""                    WHEN '{kind.value}' THEN
                        SELECT guild_id INTO NEW.guild_id FROM {endpoint.table}
                        WHERE id = NEW.source_id;"""
        for kind, endpoint in ENDPOINT_KINDS.items()
    )
    return f"""
        CREATE OR REPLACE FUNCTION public.fn_relationships_set_guild_id()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.guild_id IS NULL THEN
                CASE NEW.source_type
{arms}
                    ELSE
                        RAISE EXCEPTION
                            'fn_relationships_set_guild_id has no arm for source_type %',
                            NEW.source_type;
                END CASE;
            END IF;
            RETURN NEW;
        END;
        $$
    """



def _create_table() -> None:
    kinds = ", ".join(f"'{k.value}'" for k in sorted(ENDPOINT_KINDS, key=str))
    op.create_table(
        "relationships",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("guild_id", sa.Integer(), nullable=True),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("relationship_type", sa.String(length=32), nullable=False),
        sa.Column("subtype", sa.String(length=32), nullable=True),
        sa.Column("target_type", sa.String(length=32), nullable=False),
        sa.Column("target_id", sa.Integer(), nullable=False),
        sa.Column(
            "source_node",
            sa.BigInteger(),
            sa.Computed(
                f"(public.relationship_kind_code(source_type) << {NODE_ID_SHIFT}) "
                "| source_id::bigint",
                persisted=True,
            ),
            nullable=False,
        ),
        sa.Column(
            "target_node",
            sa.BigInteger(),
            sa.Computed(
                f"(public.relationship_kind_code(target_type) << {NODE_ID_SHIFT}) "
                "| target_id::bigint",
                persisted=True,
            ),
            nullable=False,
        ),
        sa.Column("provenance", sa.String(length=16), nullable=False),
        sa.Column("confidence", sa.REAL(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("removed_by", sa.Integer(), nullable=True),
        sa.CheckConstraint(
            f"source_type IN ({kinds})", name="ck_relationships_source_type"
        ),
        sa.CheckConstraint(
            f"target_type IN ({kinds})", name="ck_relationships_target_type"
        ),
        sa.CheckConstraint(
            "relationship_type IN "
            "('attached', 'depends_on', 'part_of', 'related_to', 'tagged_with')",
            name="ck_relationships_type",
        ),
        sa.CheckConstraint("subtype IS NULL", name="ck_relationships_subtype"),
        sa.CheckConstraint(
            "provenance IN ('manual', 'content', 'inferred')",
            name="ck_relationships_provenance",
        ),
        sa.CheckConstraint(
            "(provenance = 'inferred') = (confidence IS NOT NULL)",
            name="ck_relationships_confidence",
        ),
        sa.CheckConstraint(
            "source_node <> target_node", name="ck_relationships_no_self_loop"
        ),
        sa.CheckConstraint(
            "relationship_type NOT IN ('attached', 'related_to') "
            "OR source_node < target_node",
            name="ck_relationships_symmetric_order",
        ),
    )
    op.create_index(
        "uq_relationships_edge",
        "relationships",
        ["source_node", "relationship_type", "target_node"],
        unique=True,
        postgresql_where=sa.text("removed_at IS NULL"),
    )
    op.create_index(
        "ix_relationships_target",
        "relationships",
        ["target_node", "relationship_type"],
        postgresql_where=sa.text("removed_at IS NULL"),
    )
    op.execute(
        "CREATE TRIGGER set_guild_id BEFORE INSERT OR UPDATE ON relationships "
        "FOR EACH ROW EXECUTE FUNCTION public.fn_relationships_set_guild_id()"
    )


def _copy_junctions() -> None:
    """Move the four junctions in, asserting nothing was left behind."""
    bind = op.get_bind()
    for table, src_col, src_kind, tgt_col, tgt_kind in _JUNCTIONS:
        if not bind.execute(
            sa.text("SELECT to_regclass(:t) IS NOT NULL"), {"t": table}
        ).scalar():
            continue

        # FORCE binds the owner this migration runs as, and the policies key on
        # request GUCs it has no value for, so the copy would read zero rows and
        # report success. Lifted for the copy; the table is dropped immediately
        # after, so there is nothing to restore it on.
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        expected = bind.execute(sa.text(f"SELECT count(*) FROM {table}")).scalar()  # noqa: S608

        op.execute(f"""
            INSERT INTO relationships (
                source_type, source_id, target_type, target_id,
                relationship_type, provenance, created_by, created_at, guild_id
            )
            SELECT '{src_kind}', j.{src_col}, '{tgt_kind}', j.{tgt_col},
                   'attached', 'manual', j.attached_by_id, j.attached_at, j.guild_id
            FROM {table} j
            ON CONFLICT DO NOTHING
        """)  # noqa: S608

        moved = bind.execute(
            sa.text(
                "SELECT count(*) FROM relationships "
                "WHERE relationship_type = 'attached' "
                "AND source_type = :s AND target_type = :t"
            ),
            {"s": src_kind, "t": tgt_kind},
        ).scalar()
        if moved != expected:
            raise RuntimeError(
                f"{table}: copied {moved} of {expected} rows into relationships"
            )
        op.execute(f"DROP TABLE {table}")


def _apply_upgrade() -> None:
    _create_table()
    _copy_junctions()


def upgrade() -> None:
    # Shared, and created before the table that calls them.
    op.execute(_kind_code_fn())
    op.execute(_set_guild_id_fn())
    run_for_each_guild_schema(op.get_bind(), _apply_upgrade)


def _apply_downgrade() -> None:
    """Rebuild the junctions from the edges, then drop the table.

    Only ``attached`` rows have somewhere to go back to; anything else this
    table came to hold is dropped with it, which is the honest downgrade for a
    revision that introduced the concept.
    """
    for table, src_col, src_kind, tgt_col, tgt_kind in _JUNCTIONS:
        op.execute(f"""
            CREATE TABLE IF NOT EXISTS {table} (
                {src_col} integer NOT NULL,
                {tgt_col} integer NOT NULL,
                guild_id integer,
                attached_by_id integer,
                attached_at timestamptz NOT NULL DEFAULT now(),
                PRIMARY KEY ({src_col}, {tgt_col})
            )
        """)  # noqa: S608
        op.execute(f"""
            INSERT INTO {table} ({src_col}, {tgt_col}, guild_id, attached_by_id, attached_at)
            SELECT r.source_id, r.target_id, r.guild_id, r.created_by, r.created_at
            FROM relationships r
            WHERE r.relationship_type = 'attached'
              AND r.source_type = '{src_kind}' AND r.target_type = '{tgt_kind}'
              AND r.removed_at IS NULL
            ON CONFLICT DO NOTHING
        """)  # noqa: S608
    op.execute("DROP TABLE IF EXISTS relationships")


def downgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_downgrade)
    op.execute("DROP FUNCTION IF EXISTS public.fn_relationships_set_guild_id()")
    op.execute("DROP FUNCTION IF EXISTS public.relationship_kind_code(text)")
