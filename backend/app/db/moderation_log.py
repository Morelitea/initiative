"""The moderation log and comment tombstones, as the database keeps them.

- **The log is append-only.** ``moderation_actions`` takes no UPDATE but the
  system engine's — the secret-key rotation re-seals ``snapshot`` there — and
  no DELETE but a purge's (``app.db.gucs.PURGING``), which is what takes an
  initiative's log with it. A removal is undone by a ``restore`` row, never by
  changing the removal.
- **A tombstone keeps its place.** Once ``comments.removed_at`` is set, the
  comment's words and the columns saying why are the system engine's to
  change: a moderator's removal and its restore are written there
  (``app.services.tenant.moderation_acts``), and nobody edits a tombstone. Its
  lifecycle columns move as any other row's do, so the thread it is in can
  still be trashed and restored around it.
"""

from __future__ import annotations

from app.db import gucs
from app.db.authorization import SYSTEM_SESSION
from app.db.frozen import FROZEN_SQLSTATE, LOG_CONSTRAINT, TOMBSTONE_CONSTRAINT

#: What makes a comment a tombstone, and what it says.
TOMBSTONE_COLUMNS: tuple[str, ...] = (
    "content",
    "removed_at",
    "removed_reason",
    "removal_id",
)

_SECTION = """\
-- ===========================================================================
-- Moderation (app.db.moderation_log): the log is append-only, and a
-- tombstone's words are the system engine's to change.
-- ==========================================================================="""


def log_guard_fn() -> str:
    return f"""
CREATE OR REPLACE FUNCTION public.fn_moderation_log_guard() RETURNS trigger
    LANGUAGE plpgsql AS $moderation_log$
BEGIN
    IF {SYSTEM_SESSION} OR (TG_OP = 'DELETE' AND {gucs.PURGING}) THEN
        RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
    END IF;
    RAISE EXCEPTION 'the moderation log is kept as it was written'
        USING ERRCODE = '{FROZEN_SQLSTATE}', CONSTRAINT = '{LOG_CONSTRAINT}';
END;
$moderation_log$;
"""


def tombstone_guard_fn() -> str:
    return f"""
CREATE OR REPLACE FUNCTION public.fn_tombstone_guard() RETURNS trigger
    LANGUAGE plpgsql AS $tombstone$
BEGIN
    IF {SYSTEM_SESSION} THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'a removed comment is not edited'
        USING ERRCODE = '{FROZEN_SQLSTATE}', CONSTRAINT = '{TOMBSTONE_CONSTRAINT}';
END;
$tombstone$;
"""


def _changed(columns: tuple[str, ...]) -> str:
    return " OR ".join(f"NEW.{c} IS DISTINCT FROM OLD.{c}" for c in columns)


def render_moderation_log_ddl() -> str:
    """Both guards, for one guild schema."""
    return "\n".join(
        [
            _SECTION,
            log_guard_fn(),
            tombstone_guard_fn(),
            (
                "CREATE OR REPLACE TRIGGER tr_moderation_actions_guard "
                "BEFORE UPDATE OR DELETE ON moderation_actions FOR EACH ROW "
                "EXECUTE FUNCTION public.fn_moderation_log_guard();"
            ),
            (
                "CREATE OR REPLACE TRIGGER tr_comments_tombstone_guard "
                "BEFORE UPDATE ON comments FOR EACH ROW "
                f"WHEN (OLD.removed_at IS NOT NULL AND ({_changed(TOMBSTONE_COLUMNS)})) "
                "EXECUTE FUNCTION public.fn_tombstone_guard();"
            ),
        ]
    )
