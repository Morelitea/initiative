"""Let the system engine stamp push token delivery.

``app_admin`` held SELECT/INSERT/DELETE on ``public.push_tokens`` but not
UPDATE, while ``send_push_to_user`` writes ``last_used_at`` after every
successful delivery. Every push the system engine sends — the background
overdue/assignment digests, the PAM access-grant notices — therefore reached
FCM and then faulted on the bookkeeping write.

The request-path roles (``app_guild_base`` / ``platform_base``) already carry
UPDATE for exactly this call; this brings the system engine in line. The bare
login role still holds nothing on the table.

Revision ID: 20260814_0181
Revises: 20260814_0180
Create Date: 2026-08-14
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text

revision = "20260814_0181"
down_revision = "20260814_0180"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().execute(text("GRANT UPDATE ON TABLE public.push_tokens TO app_admin"))


def downgrade() -> None:
    op.get_bind().execute(
        text("REVOKE UPDATE ON TABLE public.push_tokens FROM app_admin")
    )
