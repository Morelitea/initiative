"""Fix quoted color/icon defaults and widen hex-color columns for alpha.

Two fixes to color/icon columns:

1. Double-quoted ``server_default``: three columns were defined with
   ``server_default="'#value'"`` — the extra SQL quotes get double-escaped, so
   the stored DEFAULT became the literal quoted string (e.g. ``'#6366F1'``,
   quotes included) instead of ``#6366F1``. For ``tags.color`` (VARCHAR(7)) that
   default can't even be applied. Masked because the ORM always sends an
   explicit value. Affected: ``tags.color``, ``task_statuses.color``,
   ``task_statuses.icon``.

2. Alpha channel: hex-color columns that were VARCHAR(7) (``#RRGGBB`` only) are
   widened to VARCHAR(9) so ``#RRGGBBAA`` fits, matching ``task_statuses.color``
   which was already 9. Affected: ``tags.color``, ``property_definitions.color``.

Revision ID: 20260608_0098
Revises: 20260607_0097
Create Date: 2026-06-08
"""

from alembic import op
import sqlalchemy as sa

revision = "20260608_0098"
down_revision = "20260607_0097"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Widen hex-color columns to allow an alpha channel (#RRGGBBAA).
    op.alter_column(
        "tags", "color",
        existing_type=sa.String(7), type_=sa.String(9), existing_nullable=False,
    )
    op.alter_column(
        "property_definitions", "color",
        existing_type=sa.String(7), type_=sa.String(9), existing_nullable=True,
    )

    # 2. Correct the double-quoted DEFAULT clauses (unquoted values).
    op.execute("ALTER TABLE tags ALTER COLUMN color SET DEFAULT '#6366F1'")
    op.execute("ALTER TABLE task_statuses ALTER COLUMN color SET DEFAULT '#94A3B8'")
    op.execute("ALTER TABLE task_statuses ALTER COLUMN icon SET DEFAULT 'circle-dashed'")

    # Repair any rows that captured the bad literal-quoted value (quotes included).
    op.execute("UPDATE task_statuses SET color = '#94A3B8' WHERE color = '''#94A3B8'''")
    op.execute(
        "UPDATE task_statuses SET icon = 'circle-dashed' WHERE icon = '''circle-dashed'''"
    )


def downgrade() -> None:
    # Restore the original (double-quoted) defaults.
    op.execute("ALTER TABLE tags ALTER COLUMN color SET DEFAULT '''#6366F1'''")
    op.execute("ALTER TABLE task_statuses ALTER COLUMN color SET DEFAULT '''#94A3B8'''")
    op.execute(
        "ALTER TABLE task_statuses ALTER COLUMN icon SET DEFAULT '''circle-dashed'''"
    )

    # Narrow the hex-color columns back to VARCHAR(7), truncating any alpha.
    op.alter_column(
        "property_definitions", "color",
        existing_type=sa.String(9), type_=sa.String(7), existing_nullable=True,
        postgresql_using="left(color, 7)",
    )
    op.alter_column(
        "tags", "color",
        existing_type=sa.String(9), type_=sa.String(7), existing_nullable=False,
        postgresql_using="left(color, 7)",
    )
