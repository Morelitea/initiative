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
    # The read half of app_guild_base, table by table, rather than everything
    # in the schema: several shared tables are deliberately withheld from the
    # request-path roles (see SHARED_TABLE_APP_USER_GRANTS), and this role is
    # held to the same set.
    #
    # Derived from what app_guild_base can already read, so this role's reach
    # is that role's reach with the writes removed. No sequences: a read names
    # none. No default privileges either — a shared table added later is
    # granted here by the migration that adds it, and
    # guild_base_ro_parity_test is what asks for that decision.
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
                  AND has_table_privilege('app_guild_base', c.oid, 'SELECT')
            LOOP
                EXECUTE format('GRANT SELECT ON %s TO {ROLE}', readable.rel);
            END LOOP;
        END
        $$;
        """
    )
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
            FOR holder IN
                SELECT m.member::regrole AS who
                FROM pg_auth_members m
                JOIN pg_roles g ON g.oid = m.roleid
                WHERE g.rolname = '{ROLE}'
            LOOP
                EXECUTE format('REVOKE {ROLE} FROM %s', holder.who);
            END LOOP;
            REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {ROLE};
            -- Sequences are not granted on the way up. Revoked anyway, so a
            -- database that ran an earlier draft of this revision is cleaned
            -- by a down/up cycle.
            REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM {ROLE};
            REVOKE ALL ON SCHEMA public FROM {ROLE};
        END
        $$;
        """
    )
