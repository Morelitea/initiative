"""moderation_reports: what a community's moderators settle

Two guild-content tables and one function in ``public``.

``moderation_reports`` is one row per reported target in one initiative: what
it is, why, and what was decided. It is deliberately **not** a task — a task
carries a checklist, dates, recurrence, a position, assignees and properties,
and a moderator needs none of them.

``moderation_report_reporters`` is who reported it. A row per person rather
than a count on the report, because the count has to mean *distinct people* and
only the identities make it mean that.

``public.initiative_full_access`` is the access rule both tables defer to. It
is ``initiative_access`` with the membership leg replaced by the one the
sharing override already uses: ``app.override_initiatives``, the GUC the
request sets from the reader's roles and ``public.resource_access`` already
reads. So these tables are reachable by whoever already sees everything in the
initiative, by the guild admin, and by a PAM grantee — and by nobody else.

Nothing to backfill: both tables are new and start empty in every schema.

RLS policies, grants and triggers are NOT written here: provisioning renders
those from the live ``guild_template`` and the registries
(``app.db.initiative_rls``), and the boot backfill re-applies them to every
guild whose stamp this revision made stale.

Revision ID: 20260915_0272
Revises: 20260915_0271
Create Date: 2026-09-15
"""

import sqlalchemy as sa
from alembic import op

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20260915_0272"
down_revision = "20260915_0271"
branch_labels = None
depends_on = None

#: The outcomes as of this revision. Stated here rather than imported from
#: ``app.core.moderation`` — one added later must not change what this revision
#: writes. ``migration_imports_test`` is what holds the rule.
_OUTCOMES: tuple[str, ...] = (
    "content_removed",
    "dismissed",
    "escalated",
    "member_warned",
)

_FULL_ACCESS_FN = """
CREATE OR REPLACE FUNCTION public.initiative_full_access(
    p_initiative_id integer, p_need_write boolean DEFAULT false
) RETURNS boolean
    LANGUAGE sql STABLE
    AS $$
    SELECT
        public.guild_auth_satisfied()
        AND (
            current_setting('app.current_guild_role'::text, true) = 'admin'::text
            OR (CASE
                  WHEN p_need_write
                    THEN current_setting('app.pam_write'::text, true) = 'true'::text
                  ELSE current_setting('app.pam_read'::text, true) = 'true'::text
                       OR current_setting('app.pam_write'::text, true) = 'true'::text
                END)
            OR p_initiative_id = ANY(
                string_to_array(
                    NULLIF(current_setting('app.override_initiatives'::text, true), ''),
                    ','
                )::integer[]
            )
        )
$$;
"""


def upgrade() -> None:
    op.execute(_FULL_ACCESS_FN)
    run_for_each_guild_schema(op.get_bind(), _apply_upgrade)


def _apply_upgrade() -> None:
    outcomes = ", ".join(f"'{outcome}'" for outcome in _OUTCOMES)
    op.create_table(
        "moderation_reports",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "guild_id",
            sa.Integer(),
            sa.ForeignKey("guilds.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "initiative_id",
            sa.Integer(),
            sa.ForeignKey("initiatives.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("target_type", sa.String(length=32), nullable=False),
        sa.Column("target_id", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(length=32), nullable=False),
        sa.Column("reported_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("outcome", sa.String(length=32), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("decided_by", sa.Integer(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            f"outcome IS NULL OR outcome IN ({outcomes})",
            name="ck_moderation_reports_outcome",
        ),
        # Settled and unsettled are one state, recorded once: a report has an
        # outcome and a decision, or it has neither.
        sa.CheckConstraint(
            "(outcome IS NULL) = (decided_at IS NULL)",
            name="ck_moderation_reports_decided",
        ),
    )
    op.create_index(
        "ix_moderation_reports_initiative",
        "moderation_reports",
        ["initiative_id", "outcome", sa.text("reported_at DESC")],
    )
    # One open report per target: a second person reporting the same thing
    # joins it rather than opening another.
    op.create_index(
        "uq_moderation_reports_open_target",
        "moderation_reports",
        ["initiative_id", "target_type", "target_id"],
        unique=True,
        postgresql_where=sa.text("outcome IS NULL"),
    )

    op.create_table(
        "moderation_report_reporters",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "report_id",
            sa.Integer(),
            sa.ForeignKey("moderation_reports.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("reporter_id", sa.Integer(), nullable=False),
        sa.Column("reported_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        # Leads on report_id, so it also serves reading one report's reporters.
        sa.UniqueConstraint(
            "report_id", "reporter_id", name="uq_moderation_report_reporter"
        ),
    )


def downgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_downgrade)
    op.execute(
        "DROP FUNCTION IF EXISTS public.initiative_full_access(integer, boolean)"
    )


def _apply_downgrade() -> None:
    op.drop_table("moderation_report_reporters")
    op.drop_table("moderation_reports")
