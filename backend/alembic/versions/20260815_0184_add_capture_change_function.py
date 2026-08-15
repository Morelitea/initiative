"""Add public.capture_change(), the one change-capture trigger function

Created once in ``public`` and shared by every guild schema, exactly like
``public.initiative_access``. The body names content tables unqualified, so they
resolve through the caller's ``search_path`` — the routed ``guild_<id>`` — and
one function serves every guild rather than one per schema.

Per-table knowledge arrives as trigger arguments rendered from the registries
that already describe these tables (``app/db/event_capture.py``): how a row
resolves its initiative, which resource an event names, and which columns are
excluded from the reported change set. The triggers themselves are installed per
schema at provisioning time, not here.

The function writes identifiers, an action, and changed column NAMES. It never
writes a value: a consumer reads current state back through the REST API.

Revision ID: 20260815_0184
Revises: 20260815_0183
Create Date: 2026-08-15
"""

from __future__ import annotations

from alembic import op

from app.db.event_capture import CAPTURE_FUNCTION, CAPTURE_FUNCTION_SQL

revision = "20260815_0184"
down_revision = "20260815_0183"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The body names guild-local tables that no schema on the migration-time
    # search_path holds; resolution is per call, through the routed search_path.
    op.execute("SET LOCAL check_function_bodies = false")
    op.execute(CAPTURE_FUNCTION_SQL)


def downgrade() -> None:
    op.execute(f"DROP FUNCTION IF EXISTS {CAPTURE_FUNCTION}()")
