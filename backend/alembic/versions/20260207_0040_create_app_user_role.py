"""Create app_user role for RLS-enforced connections

Revision ID: 20260207_0040
Revises: 20260202_0038
Create Date: 2026-02-07

Creates a non-superuser app_user role without BYPASSRLS so RLS policies
are enforced. The application connects as this role for all user-facing
queries. Grants DML on all current tables and USAGE/SELECT on sequences.
Also refreshes app_admin grants for any tables created since Phase 6.
"""

from alembic import op
from sqlalchemy import text


revision = "20260207_0040"
down_revision = "b80896e96c1b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()

    # --- app_user: non-superuser for RLS-enforced queries ---
    result = connection.execute(
        text("SELECT 1 FROM pg_roles WHERE rolname = 'app_user'")
    )
    if result.fetchone() is None:
        try:
            connection.execute(text("CREATE ROLE app_user WITH LOGIN NOINHERIT"))
        except Exception:
            print(
                "WARNING: Could not create app_user role. "
                "Please create it manually with superuser privileges:\n"
                "  CREATE ROLE app_user WITH LOGIN NOINHERIT PASSWORD 'your_password';"
            )
            return
    else:
        # Ensure correct attributes on pre-existing role
        connection.execute(text("ALTER ROLE app_user WITH LOGIN NOINHERIT"))

    # Grant DML on all existing tables
    connection.execute(
        text("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO app_user")
    )
    # Grant sequence access (needed for serial/identity columns)
    connection.execute(
        text("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO app_user")
    )
    # Default privileges for future tables/sequences
    connection.execute(
        text(
            "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
            "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO app_user"
        )
    )
    connection.execute(
        text(
            "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
            "GRANT USAGE, SELECT ON SEQUENCES TO app_user"
        )
    )

    # --- Refresh app_admin grants and ensure LOGIN (tables created after Phase 6) ---
    result = connection.execute(
        text("SELECT 1 FROM pg_roles WHERE rolname = 'app_admin'")
    )
    if result.fetchone() is not None:
        connection.execute(text("ALTER ROLE app_admin WITH LOGIN BYPASSRLS"))
        connection.execute(
            text("GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO app_admin")
        )
        connection.execute(
            text("GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO app_admin")
        )


def downgrade() -> None:
    connection = op.get_bind()

    result = connection.execute(
        text("SELECT 1 FROM pg_roles WHERE rolname = 'app_user'")
    )
    if result.fetchone() is None:
        return

    try:
        connection.execute(
            text(
                "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
                "REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM app_user"
            )
        )
        connection.execute(
            text(
                "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
                "REVOKE USAGE, SELECT ON SEQUENCES FROM app_user"
            )
        )
    except Exception:
        pass

    try:
        connection.execute(
            text("REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM app_user")
        )
        connection.execute(
            text("REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public FROM app_user")
        )
    except Exception:
        pass

    # Don't drop the role - might have active connections or manual config
