"""Create app_admin role with BYPASSRLS (Phase 6 of RLS)

Revision ID: 20260127_0029
Revises: 20260127_0028
Create Date: 2026-01-27

This migration creates the app_admin database role that bypasses RLS.
Use this role for:
- Running Alembic migrations
- Background jobs that need cross-guild access
- Admin operations

IMPORTANT: This migration requires the database user running migrations
to have CREATEROLE privilege. If the migration fails, you may need to
create the role manually as a superuser:

    CREATE ROLE app_admin WITH LOGIN BYPASSRLS;
    GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO app_admin;
    GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO app_admin;
    ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO app_admin;
    ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO app_admin;

Then set DATABASE_URL_ADMIN in your .env to use this role.
"""

from alembic import op
from sqlalchemy import text


revision = "20260127_0029"
down_revision = "20260127_0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()

    # Check if role already exists
    result = connection.execute(
        text("SELECT 1 FROM pg_roles WHERE rolname = 'app_admin'")
    )
    if result.fetchone() is None:
        # Create the admin role with BYPASSRLS
        # Note: LOGIN allows direct connection, BYPASSRLS skips RLS policies
        try:
            connection.execute(text("CREATE ROLE app_admin WITH BYPASSRLS"))
        except Exception:
            # If we can't create the role (insufficient privileges), that's OK
            # The admin will need to create it manually
            print(
                "WARNING: Could not create app_admin role. "
                "Please create it manually with superuser privileges."
            )
            return

    # Grant privileges to the admin role
    # These grants ensure the role can access all current and future tables
    connection.execute(
        text("GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO app_admin")
    )
    connection.execute(
        text("GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO app_admin")
    )

    # Set default privileges for future tables/sequences
    connection.execute(
        text("ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO app_admin")
    )
    connection.execute(
        text("ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO app_admin")
    )


def downgrade() -> None:
    connection = op.get_bind()

    # Revoke default privileges
    try:
        connection.execute(
            text("ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES FROM app_admin")
        )
        connection.execute(
            text("ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON SEQUENCES FROM app_admin")
        )
    except Exception:
        pass

    # Revoke all privileges
    try:
        connection.execute(
            text("REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM app_admin")
        )
        connection.execute(
            text("REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public FROM app_admin")
        )
    except Exception:
        pass

    # Note: We don't drop the role in downgrade because:
    # 1. It might have database connections
    # 2. The user might have manually configured it with a password
    # To fully remove: DROP ROLE app_admin;
