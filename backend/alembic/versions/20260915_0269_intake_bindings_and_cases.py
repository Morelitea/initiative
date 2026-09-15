"""intake_bindings and intake_cases: where operations work lands

Two guild-content tables.

``intake_bindings`` says *this stream lands in that project* — one row per
stream per guild, naming a project and optionally the status a new case starts
in. Guild-schema because every id on it is a per-schema id.

``intake_cases`` is one row per case the writer opened, keyed by the project
and stream it landed in. A repeating source finds its open case there, and the
row carries how often it has been seen and when it was last marked — state held
in a row rather than in a process, so every replica reads the same one.

RLS policies, grants and the ``created_by`` trigger are NOT written here:
provisioning renders those from the live ``guild_template`` and the registries
(``app.db.initiative_rls``), and the boot backfill re-applies them to every
guild whose stamp this revision made stale. Both tables are initiative-scoped
there — a binding through its project, a case through the task it names.

Nothing to backfill: both tables are new and start empty in every schema.

Revision ID: 20260915_0269
Revises: 20260915_0268
Create Date: 2026-09-15
"""

import sqlalchemy as sa
from alembic import op

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20260915_0269"
down_revision = "20260915_0268"
branch_labels = None
depends_on = None

#: The streams as of this revision. Stated here rather than imported from
#: ``app.core.intake`` — a stream added later must not change what this
#: revision writes. ``migration_imports_test`` is what holds the rule.
_STREAMS: tuple[str, ...] = ("feedback", "moderation", "security", "support")


def upgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_upgrade)


def _apply_upgrade() -> None:
    streams = ", ".join(f"'{stream}'" for stream in _STREAMS)
    op.create_table(
        "intake_bindings",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("stream", sa.String(length=32), nullable=False),
        sa.Column(
            "project_id",
            sa.Integer(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "default_status_id",
            sa.Integer(),
            sa.ForeignKey("task_statuses.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.CheckConstraint(f"stream IN ({streams})", name="ck_intake_bindings_stream"),
        sa.UniqueConstraint("stream", name="uq_intake_bindings_stream"),
    )
    op.create_index("ix_intake_bindings_project_id", "intake_bindings", ["project_id"])

    op.create_table(
        "intake_cases",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "project_id",
            sa.Integer(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("stream", sa.String(length=32), nullable=False),
        sa.Column(
            "task_id",
            sa.Integer(),
            sa.ForeignKey("tasks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("dedupe_key", sa.String(length=200), nullable=True),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("noted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "occurrences", sa.Integer(), nullable=False, server_default=sa.text("1")
        ),
        sa.CheckConstraint(f"stream IN ({streams})", name="ck_intake_cases_stream"),
    )
    op.create_index("ix_intake_cases_task_id", "intake_cases", ["task_id"])
    # The writer's two reads: the latest keyed case for a stream in a project,
    # and the latest case of any kind for the settings page.
    op.create_index(
        "ix_intake_cases_key",
        "intake_cases",
        ["project_id", "stream", "dedupe_key", sa.text("opened_at DESC")],
    )


def downgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_downgrade)


def _apply_downgrade() -> None:
    op.drop_table("intake_cases")
    op.drop_table("intake_bindings")
