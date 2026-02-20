"""add check constraint for permission_key enum values

Revision ID: 20260220_0055
Revises: 20260217_0054
Create Date: 2026-02-20
"""

revision = "20260220_0055"
down_revision = "20260217_0054"
branch_labels = None
depends_on = None

from alembic import op
from sqlalchemy import text

# Valid PermissionKey values — must match app.models.initiative.PermissionKey
VALID_KEYS = ("docs_enabled", "projects_enabled", "create_docs", "create_projects")


def upgrade() -> None:
    conn = op.get_bind()

    # Remove any rows with invalid permission_key values before adding constraint
    valid_list = ", ".join(f"'{k}'" for k in VALID_KEYS)
    conn.execute(text(
        f"DELETE FROM initiative_role_permissions "
        f"WHERE permission_key NOT IN ({valid_list})"
    ))

    # Add CHECK constraint to enforce valid enum values
    op.create_check_constraint(
        "ck_initiative_role_permissions_permission_key",
        "initiative_role_permissions",
        f"permission_key IN ({valid_list})",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_initiative_role_permissions_permission_key",
        "initiative_role_permissions",
        type_="check",
    )
