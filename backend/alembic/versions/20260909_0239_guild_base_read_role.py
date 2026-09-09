"""add app_guild_base_ro, the read-only floor for shared tables

``app_guild_base`` carries full DML on the shared tables, which is what a guild
role needs to serve a request. A role that only ever reads has no use for that
half, and a privilege reached by inheritance cannot be revoked back off — so a
read-only floor has to be its own role rather than a subtraction from that one.

Granted to the per-guild query role by provisioning. The PAM read role
(``guild_<id>_ro``) still carries the writable floor; moving it is a change to
an existing grant's behaviour and belongs on its own.

Revision ID: 20260909_0239
Revises: 20260908_0238
Create Date: 2026-09-09
"""

from alembic import op

revision = "20260909_0239"
down_revision = "20260908_0238"
branch_labels = None
depends_on = None

ROLE = "app_guild_base_ro"


def upgrade() -> None:
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{ROLE}') THEN
                CREATE ROLE {ROLE} NOLOGIN;
            END IF;
        END
        $$;
        """
    )
    op.execute(f"GRANT USAGE ON SCHEMA public TO {ROLE}")
    op.execute(f"GRANT SELECT ON ALL TABLES IN SCHEMA public TO {ROLE}")
    # New shared tables reach it through the default privileges the app sets at
    # startup (app.db.bootstrap), the same way the writable floor is kept current.


def downgrade() -> None:
    op.execute(f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {ROLE}")
    op.execute(f"REVOKE ALL ON SCHEMA public FROM {ROLE}")
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{ROLE}') THEN
                EXECUTE 'DROP OWNED BY {ROLE}';
                DROP ROLE {ROLE};
            END IF;
        END
        $$;
        """
    )
