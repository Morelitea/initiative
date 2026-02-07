"""Create and configure app_user and app_admin roles for RLS

Revision ID: 20260207_0040
Revises: 20260202_0038
Create Date: 2026-02-07

Creates app_user (non-superuser, RLS-enforced) and refreshes app_admin
grants. Passwords are extracted from DATABASE_URL_APP / DATABASE_URL_ADMIN
environment variables so self-hosted upgrades work without manual SQL.
"""

import os
from urllib.parse import urlparse

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


def _password_from_url(env_var: str) -> str | None:
    """Extract the password component from a DATABASE_URL env var."""
    url = os.environ.get(env_var)
    if not url:
        return None
    try:
        parsed = urlparse(url)
        return parsed.password
    except Exception:
        return None


def _exec_role_ddl(connection, ddl_template: str, password: str | None) -> None:
    """Execute a role DDL statement with an optional password.

    PostgreSQL DDL (CREATE/ALTER ROLE) doesn't support bind parameters,
    so we pass the password through set_config() and use format('%L')
    for safe literal quoting inside a DO block.
    """
    if password is not None:
        connection.execute(
            text("SELECT set_config('app._migration_pw', :pw, true)"),
            {"pw": password},
        )
        connection.execute(text(
            "DO $$ BEGIN "
            f"EXECUTE format('{ddl_template} PASSWORD %L', "
            "current_setting('app._migration_pw')); "
            "END $$"
        ))
        # Clear the temporary variable
        connection.execute(
            text("SELECT set_config('app._migration_pw', '', true)")
        )
    else:
        connection.execute(text(ddl_template))


def upgrade() -> None:
    connection = op.get_bind()

    # --- app_user: non-superuser for RLS-enforced queries ---
    app_user_pw = _password_from_url("DATABASE_URL_APP")

    if not _role_exists(connection, "app_user"):
        if app_user_pw:
            _exec_role_ddl(
                connection,
                "CREATE ROLE app_user WITH LOGIN NOINHERIT",
                app_user_pw,
            )
        else:
            print(
                "NOTE: app_user role does not exist and DATABASE_URL_APP is not set.\n"
                "RLS enforcement requires this role. Create it with:\n"
                "  CREATE ROLE app_user WITH LOGIN NOINHERIT PASSWORD 'your_password';\n"
                "For Docker deployments, docker/init-db.sh handles this automatically."
            )
    else:
        # Ensure correct attributes and sync password from env
        _exec_role_ddl(
            connection,
            "ALTER ROLE app_user WITH LOGIN NOINHERIT",
            app_user_pw,
        )

    if _role_exists(connection, "app_user"):
        connection.execute(
            text("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO app_user")
        )
        connection.execute(
            text("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO app_user")
        )
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

    # --- app_admin: BYPASSRLS for migrations and background jobs ---
    app_admin_pw = _password_from_url("DATABASE_URL_ADMIN")

    if not _role_exists(connection, "app_admin"):
        if app_admin_pw:
            _exec_role_ddl(
                connection,
                "CREATE ROLE app_admin WITH LOGIN BYPASSRLS",
                app_admin_pw,
            )
    else:
        _exec_role_ddl(
            connection,
            "ALTER ROLE app_admin WITH LOGIN BYPASSRLS",
            app_admin_pw,
        )

    if _role_exists(connection, "app_admin"):
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
