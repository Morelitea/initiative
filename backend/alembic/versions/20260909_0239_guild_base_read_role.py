"""add app_guild_base_ro, the read-only floor for shared tables

``app_guild_base`` carries full DML on the shared tables, which is what a guild
role needs to serve a request. A role that only ever reads has no use for that
half, and a privilege reached by inheritance cannot be revoked back off — so a
read-only floor has to be its own role rather than a subtraction from that one.

Provisioning grants it to the two per-guild roles that only read: the query
role, and ``guild_<id>_ro``, which serves PAM read grants and read-only
members and is described as SELECT-only.

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
    # SELECT, not USAGE: reading a sequence's value is a read; advancing it is
    # what an insert does.
    op.execute(f"GRANT SELECT ON ALL SEQUENCES IN SCHEMA public TO {ROLE}")
    # New shared tables reach it through the default privileges the app sets at
    # startup (app.db.bootstrap), the same way the writable floor is kept current.


def downgrade() -> None:
    """Give back what this database granted, and leave the role.

    Roles are cluster-global while a migration runs in one database, and
    ``DROP OWNED BY`` reaches only the database it runs in — so a role holding
    privileges in a sibling database (every test database is one) cannot be
    dropped from here. Revoking is the part that is this database's to do.
    """
    op.execute(
        f"""
        DO $$
        DECLARE
            holder record;
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{ROLE}') THEN
                RETURN;
            END IF;
            EXECUTE format(
                'ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA public '
                'REVOKE SELECT ON TABLES FROM {ROLE}', current_user);
            EXECUTE format(
                'ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA public '
                'REVOKE SELECT ON SEQUENCES FROM {ROLE}', current_user);
            FOR holder IN
                SELECT m.member::regrole AS who
                FROM pg_auth_members m
                JOIN pg_roles g ON g.oid = m.roleid
                WHERE g.rolname = '{ROLE}'
            LOOP
                EXECUTE format('REVOKE {ROLE} FROM %s', holder.who);
            END LOOP;
            REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {ROLE};
            REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM {ROLE};
            REVOKE ALL ON SCHEMA public FROM {ROLE};
        END
        $$;
        """
    )
