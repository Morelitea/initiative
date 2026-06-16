"""Fail-closed guild roles: an app_guild_base role for shared/public access.

Under schema-per-guild a request reaches a guild's schema by ``SET ROLE`` to that
guild's role — the login roles (``app_user``/``app_admin``) hold NO standing
access to any guild schema (fail-closed). A ``SET ROLE``'d session still needs to
read the shared public tables (``users``, ``guilds``, ...), so every per-guild
role inherits those from this single base role (provisioning does
``GRANT app_guild_base TO guild_<id>``).

``app_user`` is already ``NOINHERIT``; provisioning grants the guild role to the
login roles ``WITH INHERIT FALSE`` so neither can touch a guild schema without an
explicit ``SET ROLE``.

Revision ID: 20260609_0100
Revises: 20260609_0099
Create Date: 2026-06-09
"""

from alembic import op

revision = "20260609_0100"
down_revision = "20260609_0099"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_guild_base') THEN
                CREATE ROLE app_guild_base NOLOGIN;
            END IF;
        END$$;
        """
    )
    # The shared public objects a routed (SET ROLE'd) guild session must reach.
    # Broad for now (all public tables); the legacy guild-scoped public tables go
    # away with the data conversion, after which this can narrow to SHARED_TABLES.
    op.execute("GRANT USAGE ON SCHEMA public TO app_guild_base")
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO app_guild_base"
    )
    op.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO app_guild_base")
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO app_guild_base"
    )
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO app_guild_base"
    )


def downgrade() -> None:
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        "REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM app_guild_base"
    )
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE USAGE, SELECT ON SEQUENCES FROM app_guild_base"
    )
    op.execute("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM app_guild_base")
    op.execute("REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM app_guild_base")
    op.execute("REVOKE USAGE ON SCHEMA public FROM app_guild_base")
    op.execute("DROP OWNED BY app_guild_base")
