"""The floors hold on alembic_version and app_settings what the registry says

A database first started on v0.72.0 with one owner ``DATABASE_URL`` and then
upgraded holds grants a fresh install never has: ``app_guild_base`` and
``platform_base`` hold ``INSERT``, ``UPDATE`` and ``DELETE`` on
``app_settings`` (the registry gives them ``SELECT``), and they and their
read-only floors hold ``alembic_version`` (the registry gives them nothing).
This removes what the registry does not give, so the two shapes agree. On a
database that never held the grants, each ``REVOKE`` changes nothing.

Revision ID: 20260930_0419
Revises: 20260929_0418
Create Date: 2026-09-30
"""

import string

from alembic import op

revision = "20260930_0419"
down_revision = "20260929_0418"
branch_labels = None
depends_on = None

_ALLOWED_PREFIX_CHARS = frozenset(string.ascii_letters + string.digits + "_")


def _platform_floors() -> tuple[str, str]:
    """The prefixed names, read at apply time: the suite sets a prefix before it
    migrates, and production and dev have none."""
    from app.core.config import settings

    prefix = settings.PLATFORM_ROLE_PREFIX
    if not set(prefix) <= _ALLOWED_PREFIX_CHARS:
        raise ValueError(f"unsafe PLATFORM_ROLE_PREFIX for role DDL: {prefix!r}")
    return f"{prefix}platform_base", f"{prefix}platform_base_ro"


def upgrade() -> None:
    platform_base, platform_base_ro = _platform_floors()
    op.execute(
        "REVOKE INSERT, UPDATE, DELETE ON TABLE public.app_settings "
        f'FROM app_guild_base, "{platform_base}"'
    )
    op.execute(
        "REVOKE ALL ON TABLE public.alembic_version FROM app_guild_base, "
        f'app_guild_base_ro, "{platform_base}", "{platform_base_ro}"'
    )


def downgrade() -> None:
    # The grants this removes are ones the registry never gave.
    pass
