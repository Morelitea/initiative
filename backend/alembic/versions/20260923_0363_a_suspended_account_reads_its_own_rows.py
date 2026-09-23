"""a suspended account reads its own rows, and writes none

Two NOLOGIN roles beside the platform ladder:

* ``platform_base_ro`` — the read half of ``platform_base``: ``SELECT`` on every
  shared relation ``platform_base`` can read, and ``EXECUTE`` on the functions
  it can run that execute with the caller's rights. No sequences, no default
  privileges; a shared table added later is granted here by the migration that
  adds it, and ``platform_base_ro_parity_test`` is what asks.
* ``platform_suspended`` — the role a suspended account's request assumes
  whatever its tier. It inherits ``platform_base_ro`` and nothing else. The
  login roles may ``SET ROLE`` into it and hold nothing through it, like every
  tier.

The policies that let the read floor see a reader's own rows come from the
registry (``app.db.public_rls``), applied at boot.

Revision ID: 20260923_0363
Revises: 20260923_0362
Create Date: 2026-09-23
"""

import string

from alembic import op

revision = "20260923_0363"
down_revision = "20260923_0362"
branch_labels = None
depends_on = None

_ALLOWED_PREFIX_CHARS = frozenset(string.ascii_letters + string.digits + "_")


def _names() -> tuple[str, str, str]:
    """The prefixed names, read at apply time: the suite sets a prefix before it
    migrates, and production and dev have none."""
    from app.core.config import settings

    prefix = settings.PLATFORM_ROLE_PREFIX
    if not set(prefix) <= _ALLOWED_PREFIX_CHARS:
        raise ValueError(f"unsafe PLATFORM_ROLE_PREFIX for role DDL: {prefix!r}")
    return (
        f"{prefix}platform_base",
        f"{prefix}platform_base_ro",
        f"{prefix}platform_suspended",
    )


def upgrade() -> None:
    base, read_floor, suspended = _names()
    for role in (read_floor, suspended):
        op.execute(
            f"""
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') THEN
                    CREATE ROLE "{role}" NOLOGIN;
                END IF;
            END
            $$;
            """
        )
    op.execute(f'GRANT "{read_floor}" TO "{suspended}"')
    op.execute(f'GRANT USAGE ON SCHEMA public TO "{read_floor}"')
    # What the writable floor reads, table by table, and no more.
    op.execute(
        f"""
        DO $$
        DECLARE
            readable record;
        BEGIN
            FOR readable IN
                SELECT c.oid::regclass AS rel
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'public'
                  AND c.relkind IN ('r', 'p', 'v', 'm', 'f')
                  AND has_table_privilege('{base}', c.oid, 'SELECT')
            LOOP
                EXECUTE format('GRANT SELECT ON %s TO "{read_floor}"', readable.rel);
            END LOOP;
        END
        $$;
        """
    )
    # The functions the writable floor runs that execute with the caller's
    # rights: a policy the read floor shares may call one.
    op.execute(
        f"""
        DO $$
        DECLARE
            callable record;
        BEGIN
            FOR callable IN
                SELECT p.oid::regprocedure AS fn
                FROM pg_proc p
                JOIN pg_namespace n ON n.oid = p.pronamespace
                WHERE n.nspname = 'public'
                  AND p.prokind = 'f'
                  AND NOT p.prosecdef
                  AND has_function_privilege('{base}', p.oid, 'EXECUTE')
            LOOP
                EXECUTE format(
                    'GRANT EXECUTE ON FUNCTION %s TO "{read_floor}"', callable.fn
                );
            END LOOP;
        END
        $$;
        """
    )
    for login_role in ("app_user", "app_admin"):
        op.execute(
            f"""
            DO $$
            BEGIN
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{login_role}') THEN
                    GRANT "{suspended}" TO "{login_role}" WITH INHERIT FALSE;
                END IF;
            END
            $$;
            """
        )


def downgrade() -> None:
    """Give back what this database granted, and leave the roles.

    Roles are cluster-global while a migration runs in one database, so a role
    holding privileges in a sibling database cannot be dropped from here.
    """
    _base, read_floor, suspended = _names()
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{read_floor}') THEN
                RETURN;
            END IF;
            REVOKE ALL ON ALL TABLES IN SCHEMA public FROM "{read_floor}";
            REVOKE ALL ON ALL FUNCTIONS IN SCHEMA public FROM "{read_floor}";
            REVOKE ALL ON SCHEMA public FROM "{read_floor}";
        END
        $$;
        """
    )
