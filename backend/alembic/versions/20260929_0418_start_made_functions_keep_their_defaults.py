"""Functions a start makes keep their default privileges

0363 granted ``platform_base_ro`` ``EXECUTE`` on every caller's-rights function
in ``public`` that ``platform_base`` could run. On a database that had started
before, that included six functions a start creates (the freeze guards and the
search index's writers), which a fresh install does not have yet when it
migrates, so only upgraded databases carry the grant. ``PUBLIC`` holds
``EXECUTE`` on each of them by default, so the grant adds nothing; this
removes it, and the two shapes agree.

Revision ID: 20260929_0418
Revises: 20260929_0417
Create Date: 2026-09-29
"""

import string

from alembic import op

revision = "20260929_0418"
down_revision = "20260929_0417"
branch_labels = None
depends_on = None

_ALLOWED_PREFIX_CHARS = frozenset(string.ascii_letters + string.digits + "_")

FUNCTIONS: tuple[str, ...] = (
    "public.fn_frozen_ancestor_guard()",
    "public.fn_frozen_parent_guard()",
    "public.fn_frozen_row_guard()",
    "public.refresh_search_dependents()",
    "public.refresh_search_entry()",
    "public.search_entry_write(text, text, integer, integer, text, integer, "
    "text, text, boolean, boolean)",
)


def _read_floor() -> str:
    """The prefixed name, read at apply time: the suite sets a prefix before it
    migrates, and production and dev have none."""
    from app.core.config import settings

    prefix = settings.PLATFORM_ROLE_PREFIX
    if not set(prefix) <= _ALLOWED_PREFIX_CHARS:
        raise ValueError(f"unsafe PLATFORM_ROLE_PREFIX for role DDL: {prefix!r}")
    return f"{prefix}platform_base_ro"


def upgrade() -> None:
    read_floor = _read_floor()
    for signature in FUNCTIONS:
        op.execute(
            f"""
            DO $$
            BEGIN
                IF to_regprocedure('{signature}') IS NOT NULL THEN
                    REVOKE EXECUTE ON FUNCTION {signature} FROM "{read_floor}";
                END IF;
            END
            $$;
            """
        )


def downgrade() -> None:
    # The grant this removes gave nothing PUBLIC does not hold.
    pass
