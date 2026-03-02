"""Grant app_admin privileges on uploads table.

The uploads table was created in migration 20260225_0060, after the baseline
but before 20260228_0064 which set ALTER DEFAULT PRIVILEGES for app_admin.
As a result, app_admin never received table-level grants on uploads.
The serve_upload_file endpoint uses get_admin_session (app_admin) to query
uploads for guild-scoped access control, so it needs SELECT at minimum.

Revision ID: 20260301_0065
Revises: 20260228_0064
Create Date: 2026-03-01
"""

from alembic import op
from sqlalchemy import text

revision = "20260301_0065"
down_revision = "20260228_0064"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(text("GRANT ALL PRIVILEGES ON TABLE uploads TO app_admin"))


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(text("REVOKE ALL PRIVILEGES ON TABLE uploads FROM app_admin"))
