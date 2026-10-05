"""Let a case tell its filer where it stands

``intake_bindings`` gains the two statuses a filer's view is read through:

* ``awaiting_filer_status_id`` — the status that means "waiting on whoever
  filed it". A filer sees *Waiting on you* while their case is in it.
* ``active_status_id`` — the status a waiting case goes back to when the filer
  answers.

Both are optional and fall to NULL when the status goes, like the landing
status: a project without them shows its filers *Received*, *In progress* and
*Closed*, and an answer moves nothing.

``intake_cases`` gains what its filer was last told: ``filer_notified_state``
and ``filer_notified_comment_id``. The ticket sweep compares them with the case
as it is now and tells the filer only about what moved.

Guild-scoped: applied to ``guild_template`` and every ``guild_<id>``.

Revision ID: 20261003_0452
Revises: 20261003_0451
Create Date: 2026-10-03
"""

revision = "20261003_0452"
down_revision = "20261003_0451"
branch_labels = None
depends_on = None

from alembic import op  # noqa: E402
import sqlalchemy as sa  # noqa: E402
from app.db.guild_migrations import run_for_each_guild_schema  # noqa: E402


def upgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_upgrade)


def _status_ref(name: str) -> sa.Column:
    return sa.Column(
        name,
        sa.Integer(),
        sa.ForeignKey("task_statuses.id", ondelete="SET NULL"),
        nullable=True,
    )


def _apply_upgrade() -> None:
    op.add_column("intake_bindings", _status_ref("awaiting_filer_status_id"))
    op.add_column("intake_bindings", _status_ref("active_status_id"))
    op.add_column(
        "intake_cases",
        sa.Column("filer_notified_state", sa.String(length=16), nullable=True),
    )
    op.add_column(
        "intake_cases",
        sa.Column("filer_notified_comment_id", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_downgrade)


def _apply_downgrade() -> None:
    op.drop_column("intake_cases", "filer_notified_comment_id")
    op.drop_column("intake_cases", "filer_notified_state")
    op.drop_column("intake_bindings", "active_status_id")
    op.drop_column("intake_bindings", "awaiting_filer_status_id")
