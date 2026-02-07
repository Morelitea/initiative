"""Grant privileges to app_user and app_admin roles for RLS

Revision ID: 20260207_0040
Revises: 20260202_0038
Create Date: 2026-02-07

Grants DML on all tables and USAGE/SELECT on sequences to app_user
(non-superuser, RLS-enforced) and refreshes app_admin grants for
tables created since Phase 6.

Role creation is handled by infrastructure (docker/init-db.sh or
manual DBA setup) — not by this migration — because roles require
passwords for authentication.
"""

from alembic import op
from sqlalchemy import text


revision = "20260207_0040"
down_revision = "b80896e96c1b"
branch_labels = None
depends_on = None


def _role_exists(connection, rolname: str) -> bool:
    result = connection.execute(
        text("SELECT 1 FROM pg_roles WHERE rolname = :name"),
        {"name": rolname},
    )
    return result.fetchone() is not None


def upgrade() -> None:
    connection = op.get_bind()

    # --- app_user: non-superuser for RLS-enforced queries ---
    if _role_exists(connection, "app_user"):
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
    else:
        print(
            "NOTE: app_user role does not exist — skipping grants. "
            "RLS enforcement requires this role. Create it with:\n"
            "  CREATE ROLE app_user WITH LOGIN NOINHERIT PASSWORD 'your_password';\n"
            "Then re-run this migration or grant privileges manually.\n"
            "For Docker deployments, docker/init-db.sh handles this automatically."
        )

    # --- Refresh app_admin grants (tables created after Phase 6) ---
    if _role_exists(connection, "app_admin"):
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
