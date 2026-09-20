"""the quiet-hours stamp moves under holds

When a hold ends, the notifications it held go out as one summary, and the
account keeps a stamp saying when that last happened so the same stretch is
not summarised twice. The stamp started life as
``quiet_hours.last_summary_at`` — a string, or per channel as
``{"email": …, "push": …}`` — when quiet hours were the only hold. It now
lives per kind of hold under ``holds.last_summary_at``, and the reading code
carried a fallback to the old key for rows written before that.

This moves the stamp for every row still holding it (the push half, where the
old shape stamped per channel — the email half stopped being read when email
started waiting its turn), and drops the old key, so the fallback can go.

The downgrade leaves the moved stamps where they are: a build that reads the
old key finds none and summarises the next closed window once more, which is
a duplicate summary rather than a missing one.

Revision ID: 20260919_0322
Revises: 20260919_0321
Create Date: 2026-09-19
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260919_0322"
down_revision = "20260919_0321"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    expected = conn.execute(
        sa.text(
            "SELECT count(*) FROM public.user_notification_prefs "
            " WHERE prefs->'quiet_hours' ? 'last_summary_at'"
        )
    ).scalar_one()
    if expected == 0:
        return

    # The table is FORCE-RLS and the migration role owns it; the policies key
    # on request settings a migration has no value for, so the force is lifted
    # for the write and restored with it.
    op.execute("ALTER TABLE public.user_notification_prefs NO FORCE ROW LEVEL SECURITY")
    try:
        moved = conn.execute(
            sa.text(
                "WITH legacy AS ("
                "  SELECT user_id,"
                "         CASE jsonb_typeof(prefs->'quiet_hours'->'last_summary_at')"
                "           WHEN 'string' THEN prefs->'quiet_hours'->'last_summary_at'"
                "           WHEN 'object' THEN prefs->'quiet_hours'->'last_summary_at'->'push'"
                "         END AS stamp"
                "    FROM public.user_notification_prefs"
                "   WHERE prefs->'quiet_hours' ? 'last_summary_at'"
                ") "
                "UPDATE public.user_notification_prefs p"
                "   SET prefs = ("
                "         CASE WHEN jsonb_typeof(l.stamp) = 'string'"
                "                   AND p.prefs->'holds'->'last_summary_at'->'quiet_hours' IS NULL"
                "              THEN p.prefs || jsonb_build_object('holds',"
                "                     coalesce(p.prefs->'holds', '{}'::jsonb)"
                "                     || jsonb_build_object('last_summary_at',"
                "                          coalesce(p.prefs->'holds'->'last_summary_at', '{}'::jsonb)"
                "                          || jsonb_build_object('quiet_hours', l.stamp)))"
                "              ELSE p.prefs"
                "         END"
                "       ) #- '{quiet_hours,last_summary_at}',"
                "       updated_at = now()"
                "  FROM legacy l"
                " WHERE l.user_id = p.user_id"
            )
        ).rowcount
    finally:
        op.execute(
            "ALTER TABLE public.user_notification_prefs FORCE ROW LEVEL SECURITY"
        )
    assert moved == expected, f"moved {moved} stamp(s), expected {expected}"


def downgrade() -> None:
    pass
