"""Add user_status enum + drop is_active + RLS DELETE deny on users.

Replaces the binary ``users.is_active`` boolean with a richer ``status`` enum
(``active`` / ``deactivated`` / ``anonymized``) so the existing reversible
deactivation can coexist with the new permanent anonymization (soft delete)
without overloading a single bit.

Backfill: existing ``is_active=true`` rows become ``active``; ``false`` rows
become ``deactivated``. The downgrade reverses this — ``status='active'`` maps
back to ``is_active=true`` and everything else to ``false``, so per-row
distinction between deactivated and anonymized is lost on downgrade (anonymized
rows have already cleared their PII, which the downgrade cannot restore).

Also enables RLS on the ``users`` table for the first time and adds a single
``RESTRICTIVE FOR DELETE USING (false)`` policy. The ``app_admin`` role
created in the baseline migration has ``BYPASSRLS``, so ``AdminSessionDep``
(which connects via that role) is unaffected. Every other session — including
any in-app code path that runs as ``app_user`` — is now incapable of deleting
a user row, regardless of session variables. The application-layer
``require_roles(UserRole.admin)`` guard remains; the policy is the
infrastructure-level guarantee.

Revision ID: 20260424_0076
Revises: 20260423_0075
Create Date: 2026-04-24
"""

from alembic import op
from sqlalchemy import text


revision = "20260424_0076"
down_revision = "20260423_0075"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    # 1. Create the user_status enum.
    conn.execute(text("""
    DO $$ BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'user_status') THEN
            CREATE TYPE user_status AS ENUM ('active', 'deactivated', 'anonymized');
        END IF;
    END $$
    """))

    # 2. Add the status column. Default 'active' so existing rows get a value
    #    immediately; we then backfill from is_active and drop the boolean.
    conn.execute(text(
        "ALTER TABLE users "
        "ADD COLUMN status user_status NOT NULL DEFAULT 'active'"
    ))

    # 3. Backfill from is_active.
    conn.execute(text(
        "UPDATE users SET status = 'deactivated'::user_status "
        "WHERE is_active = false"
    ))

    # 4. Drop the now-redundant boolean.
    conn.execute(text("ALTER TABLE users DROP COLUMN is_active"))

    # 5. Enable + force RLS on users (was previously not in the force_rls list).
    conn.execute(text("ALTER TABLE users ENABLE ROW LEVEL SECURITY"))
    conn.execute(text("ALTER TABLE users FORCE ROW LEVEL SECURITY"))

    # 6. Permissive policy so SELECT/INSERT/UPDATE behave exactly as today.
    #    Locking those down further is intentionally out of scope for this
    #    migration.
    conn.execute(text(
        "CREATE POLICY users_open ON users "
        "AS PERMISSIVE FOR ALL "
        "USING (true) WITH CHECK (true)"
    ))

    # 7. Restrictive policy that denies DELETE for any session that goes
    #    through RLS evaluation. The app_admin role bypasses this via
    #    BYPASSRLS, so AdminSessionDep is unaffected.
    conn.execute(text(
        "CREATE POLICY users_no_delete ON users "
        "AS RESTRICTIVE FOR DELETE "
        "USING (false)"
    ))


def downgrade() -> None:
    conn = op.get_bind()

    conn.execute(text("DROP POLICY IF EXISTS users_no_delete ON users"))
    conn.execute(text("DROP POLICY IF EXISTS users_open ON users"))
    conn.execute(text("ALTER TABLE users NO FORCE ROW LEVEL SECURITY"))
    conn.execute(text("ALTER TABLE users DISABLE ROW LEVEL SECURITY"))

    # Re-add is_active and backfill from status. Anonymized rows can't be
    # un-anonymized — their PII is gone — so we just map them to is_active=false.
    conn.execute(text(
        "ALTER TABLE users "
        "ADD COLUMN is_active boolean NOT NULL DEFAULT true"
    ))
    conn.execute(text(
        "UPDATE users SET is_active = (status = 'active'::user_status)"
    ))

    conn.execute(text("ALTER TABLE users DROP COLUMN status"))
    conn.execute(text("DROP TYPE IF EXISTS user_status"))
