"""Connect a case to its filer, and a comment to its audience

``intake_cases`` gains ``filer_user_id`` and ``filer_subject``: the account
that filed a case, when a person did, and what they called it in their own
words. A weak ref like the case's others, indexed because "the cases this
person filed" is the question it answers.

``comments`` gains two columns:

* ``audience`` — who the comment is said to. ``members`` for every comment
  that exists, and the default for every one written after; ``filer`` for the
  part of an operations case that is said to the person who filed it. Held to
  those two by ``ck_comments_audience``.
* ``system_kind`` — what the platform's writer posted a comment as, NULL on
  everything a person or an app wrote. It is what tells the platform's notes
  on a case from an app's comment, since neither names an author.

Guild-scoped: applied to ``guild_template`` and every ``guild_<id>``.

Revision ID: 20261002_0441
Revises: 20261002_0440
Create Date: 2026-10-02
"""

revision = "20261002_0441"
down_revision = "20261002_0440"
branch_labels = None
depends_on = None

from alembic import op  # noqa: E402
import sqlalchemy as sa  # noqa: E402
from app.db.guild_migrations import run_for_each_guild_schema  # noqa: E402


def upgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_upgrade)


def _apply_upgrade() -> None:
    with op.batch_alter_table("comments", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "audience",
                sa.String(length=16),
                server_default="members",
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column("system_kind", sa.String(length=32), nullable=True)
        )
        batch_op.create_check_constraint(
            "ck_comments_audience", "audience IN ('members', 'filer')"
        )

    with op.batch_alter_table("intake_cases", schema=None) as batch_op:
        batch_op.add_column(sa.Column("filer_user_id", sa.Integer(), nullable=True))
        batch_op.add_column(
            sa.Column("filer_subject", sa.String(length=200), nullable=True)
        )
        batch_op.create_index(
            batch_op.f("ix_intake_cases_filer_user_id"),
            ["filer_user_id"],
            unique=False,
        )


def downgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_downgrade)


def _apply_downgrade() -> None:
    with op.batch_alter_table("intake_cases", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_intake_cases_filer_user_id"))
        batch_op.drop_column("filer_subject")
        batch_op.drop_column("filer_user_id")

    op.execute("ALTER TABLE comments DROP CONSTRAINT IF EXISTS ck_comments_audience")
    with op.batch_alter_table("comments", schema=None) as batch_op:
        batch_op.drop_column("system_kind")
        batch_op.drop_column("audience")
