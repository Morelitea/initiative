"""Add calendar event tables for initiative-scoped scheduling.

Creates calendar_events, calendar_event_attendees, calendar_event_tags,
calendar_event_documents tables with guild isolation and initiative-scoped
RESTRICTIVE RLS policies. Adds events_enabled column to initiatives and
backfills initiative role permissions for events_enabled and create_events.

Revision ID: 20260325_0066
Revises: 20260301_0065
Create Date: 2026-03-25
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

revision = "20260325_0066"
down_revision = "20260301_0065"
branch_labels = None
depends_on = None

# ---------------------------------------------------------------------------
# RLS session-variable helpers
# ---------------------------------------------------------------------------
GUILD_ID = "current_setting('app.current_guild_id'::text, true)::int"
USER_ID = "NULLIF(current_setting('app.current_user_id'::text, true), ''::text)::integer"
GUILD_ROLE = "current_setting('app.current_guild_role'::text, true)"
IS_SUPER = "current_setting('app.is_superadmin'::text, true) = 'true'::text"
IS_ADMIN = f"{GUILD_ROLE} = 'admin'::text"
BYPASS = f"OR ({IS_ADMIN}) OR ({IS_SUPER})"

GUILD_CHECK = f"guild_id = {GUILD_ID} OR {IS_SUPER}"

TABLES_DIRECT_INITIATIVE = ["calendar_events"]
TABLES_VIA_EVENT = ["calendar_event_attendees"]
TABLES_VIA_EVENT_JUNCTION = ["calendar_event_tags", "calendar_event_documents"]


def _init_member_direct(table: str) -> str:
    return (
        f"EXISTS ("
        f"SELECT 1 FROM initiatives "
        f"WHERE initiatives.id = {table}.initiative_id "
        f"AND is_initiative_member(initiatives.id, ({USER_ID}))"
        f")"
    )


def _init_member_via_event(table: str) -> str:
    return (
        f"EXISTS ("
        f"SELECT 1 FROM calendar_events "
        f"WHERE calendar_events.id = {table}.calendar_event_id "
        f"AND is_initiative_member(calendar_events.initiative_id, ({USER_ID}))"
        f")"
    )


def _add_rls_policies(conn, table: str, membership_expr: str) -> None:
    conn.execute(text(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY"))
    conn.execute(text(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY"))

    conn.execute(text(
        f"CREATE POLICY guild_isolation ON {table} "
        f"AS PERMISSIVE FOR ALL "
        f"USING ({GUILD_CHECK}) "
        f"WITH CHECK ({GUILD_CHECK})"
    ))

    bypass_expr = f"({membership_expr} {BYPASS})"
    for cmd, policy_name in [
        ("SELECT", "initiative_member_select"),
        ("INSERT", "initiative_member_insert"),
        ("UPDATE", "initiative_member_update"),
        ("DELETE", "initiative_member_delete"),
    ]:
        if cmd == "SELECT":
            conn.execute(text(
                f"CREATE POLICY {policy_name} ON {table} "
                f"AS RESTRICTIVE FOR SELECT USING ({bypass_expr})"
            ))
        elif cmd == "INSERT":
            conn.execute(text(
                f"CREATE POLICY {policy_name} ON {table} "
                f"AS RESTRICTIVE FOR INSERT WITH CHECK ({bypass_expr})"
            ))
        elif cmd == "UPDATE":
            conn.execute(text(
                f"CREATE POLICY {policy_name} ON {table} "
                f"AS RESTRICTIVE FOR UPDATE USING ({bypass_expr}) WITH CHECK ({bypass_expr})"
            ))
        elif cmd == "DELETE":
            conn.execute(text(
                f"CREATE POLICY {policy_name} ON {table} "
                f"AS RESTRICTIVE FOR DELETE USING ({bypass_expr})"
            ))


def _add_junction_rls_policies(conn, table: str, membership_expr: str) -> None:
    conn.execute(text(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY"))
    conn.execute(text(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY"))

    bypass_expr = f"({membership_expr} {BYPASS})"
    for cmd, policy_name in [
        ("SELECT", "initiative_member_select"),
        ("INSERT", "initiative_member_insert"),
        ("UPDATE", "initiative_member_update"),
        ("DELETE", "initiative_member_delete"),
    ]:
        if cmd == "SELECT":
            conn.execute(text(
                f"CREATE POLICY {policy_name} ON {table} "
                f"AS PERMISSIVE FOR SELECT USING ({bypass_expr})"
            ))
        elif cmd == "INSERT":
            conn.execute(text(
                f"CREATE POLICY {policy_name} ON {table} "
                f"AS PERMISSIVE FOR INSERT WITH CHECK ({bypass_expr})"
            ))
        elif cmd == "UPDATE":
            conn.execute(text(
                f"CREATE POLICY {policy_name} ON {table} "
                f"AS PERMISSIVE FOR UPDATE USING ({bypass_expr}) WITH CHECK ({bypass_expr})"
            ))
        elif cmd == "DELETE":
            conn.execute(text(
                f"CREATE POLICY {policy_name} ON {table} "
                f"AS PERMISSIVE FOR DELETE USING ({bypass_expr})"
            ))


def _drop_rls(conn, table: str) -> None:
    for policy in [
        "guild_isolation",
        "initiative_member_select",
        "initiative_member_insert",
        "initiative_member_update",
        "initiative_member_delete",
    ]:
        conn.execute(text(f"DROP POLICY IF EXISTS {policy} ON {table}"))
    conn.execute(text(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY"))


def upgrade() -> None:
    conn = op.get_bind()

    # -- Add events_enabled to initiatives --
    op.add_column(
        "initiatives",
        sa.Column("events_enabled", sa.Boolean(), nullable=False, server_default="false"),
    )

    # -- Create enum types --
    conn.execute(text(
        "CREATE TYPE rsvp_status AS ENUM ('pending', 'accepted', 'declined', 'tentative')"
    ))

    # -- calendar_events --
    conn.execute(text("""
        CREATE TABLE calendar_events (
            id SERIAL PRIMARY KEY,
            guild_id INTEGER NOT NULL REFERENCES guilds(id),
            initiative_id INTEGER NOT NULL REFERENCES initiatives(id),
            title VARCHAR(255) NOT NULL,
            description TEXT,
            location VARCHAR(500),
            start_at TIMESTAMPTZ NOT NULL,
            end_at TIMESTAMPTZ NOT NULL,
            all_day BOOLEAN NOT NULL DEFAULT false,
            color VARCHAR(32),
            recurrence TEXT,
            created_by_id INTEGER NOT NULL REFERENCES users(id),
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL
        )
    """))
    conn.execute(text("CREATE INDEX ix_calendar_events_guild_id ON calendar_events (guild_id)"))
    conn.execute(text("CREATE INDEX ix_calendar_events_initiative_id ON calendar_events (initiative_id)"))
    conn.execute(text("CREATE INDEX ix_calendar_events_start_at ON calendar_events (start_at)"))

    # -- calendar_event_attendees --
    conn.execute(text("""
        CREATE TABLE calendar_event_attendees (
            calendar_event_id INTEGER NOT NULL REFERENCES calendar_events(id) ON DELETE CASCADE,
            user_id INTEGER NOT NULL REFERENCES users(id),
            guild_id INTEGER NOT NULL REFERENCES guilds(id),
            rsvp_status rsvp_status NOT NULL DEFAULT 'pending',
            created_at TIMESTAMPTZ NOT NULL,
            PRIMARY KEY (calendar_event_id, user_id)
        )
    """))
    conn.execute(text("CREATE INDEX ix_calendar_event_attendees_user_id ON calendar_event_attendees (user_id)"))

    # -- calendar_event_tags --
    conn.execute(text("""
        CREATE TABLE calendar_event_tags (
            calendar_event_id INTEGER NOT NULL REFERENCES calendar_events(id),
            tag_id INTEGER NOT NULL REFERENCES tags(id),
            created_at TIMESTAMPTZ NOT NULL,
            PRIMARY KEY (calendar_event_id, tag_id)
        )
    """))
    conn.execute(text("CREATE INDEX ix_calendar_event_tags_tag_id ON calendar_event_tags (tag_id)"))

    # -- calendar_event_documents --
    conn.execute(text("""
        CREATE TABLE calendar_event_documents (
            calendar_event_id INTEGER NOT NULL REFERENCES calendar_events(id),
            document_id INTEGER NOT NULL REFERENCES documents(id),
            guild_id INTEGER NOT NULL REFERENCES guilds(id),
            attached_by_id INTEGER REFERENCES users(id),
            attached_at TIMESTAMPTZ NOT NULL,
            PRIMARY KEY (calendar_event_id, document_id)
        )
    """))

    # -- RLS policies --
    for table in TABLES_DIRECT_INITIATIVE:
        _add_rls_policies(conn, table, _init_member_direct(table))

    for table in TABLES_VIA_EVENT:
        _add_rls_policies(conn, table, _init_member_via_event(table))

    for table in TABLES_VIA_EVENT_JUNCTION:
        _add_junction_rls_policies(conn, table, _init_member_via_event(table))

    # -- Grant app_admin privileges --
    all_tables = TABLES_DIRECT_INITIATIVE + TABLES_VIA_EVENT + TABLES_VIA_EVENT_JUNCTION
    for table in all_tables:
        conn.execute(text(f"GRANT ALL PRIVILEGES ON TABLE {table} TO app_admin"))
    conn.execute(text(
        "GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO app_admin"
    ))

    # -- Update permission_key check constraint --
    conn.execute(text(
        "ALTER TABLE initiative_role_permissions "
        "DROP CONSTRAINT IF EXISTS ck_initiative_role_permissions_permission_key"
    ))
    conn.execute(text(
        "ALTER TABLE initiative_role_permissions "
        "ADD CONSTRAINT ck_initiative_role_permissions_permission_key "
        "CHECK (permission_key IN ("
        "'docs_enabled', 'projects_enabled', 'create_docs', 'create_projects', "
        "'queues_enabled', 'create_queues', "
        "'events_enabled', 'create_events'))"
    ))

    # -- Backfill initiative role permissions --
    conn.execute(text("""
        INSERT INTO initiative_role_permissions (initiative_role_id, permission_key, enabled)
        SELECT ir.id, 'events_enabled', ir.is_manager
        FROM initiative_roles ir
        WHERE NOT EXISTS (
            SELECT 1 FROM initiative_role_permissions irp
            WHERE irp.initiative_role_id = ir.id AND irp.permission_key = 'events_enabled'
        )
    """))
    conn.execute(text("""
        INSERT INTO initiative_role_permissions (initiative_role_id, permission_key, enabled)
        SELECT ir.id, 'create_events', ir.is_manager
        FROM initiative_roles ir
        WHERE NOT EXISTS (
            SELECT 1 FROM initiative_role_permissions irp
            WHERE irp.initiative_role_id = ir.id AND irp.permission_key = 'create_events'
        )
    """))


def downgrade() -> None:
    conn = op.get_bind()

    # Remove backfilled permissions
    conn.execute(text(
        "DELETE FROM initiative_role_permissions "
        "WHERE permission_key IN ('events_enabled', 'create_events')"
    ))

    # Restore permission_key check constraint
    conn.execute(text(
        "ALTER TABLE initiative_role_permissions "
        "DROP CONSTRAINT IF EXISTS ck_initiative_role_permissions_permission_key"
    ))
    conn.execute(text(
        "ALTER TABLE initiative_role_permissions "
        "ADD CONSTRAINT ck_initiative_role_permissions_permission_key "
        "CHECK (permission_key IN ("
        "'docs_enabled', 'projects_enabled', 'create_docs', 'create_projects', "
        "'queues_enabled', 'create_queues'))"
    ))

    # Drop RLS policies
    all_tables = TABLES_DIRECT_INITIATIVE + TABLES_VIA_EVENT + TABLES_VIA_EVENT_JUNCTION
    for table in all_tables:
        _drop_rls(conn, table)

    # Drop tables
    conn.execute(text("DROP TABLE IF EXISTS calendar_event_documents CASCADE"))
    conn.execute(text("DROP TABLE IF EXISTS calendar_event_tags CASCADE"))
    conn.execute(text("DROP TABLE IF EXISTS calendar_event_attendees CASCADE"))
    conn.execute(text("DROP TABLE IF EXISTS calendar_events CASCADE"))

    # Drop enum type
    conn.execute(text("DROP TYPE IF EXISTS rsvp_status"))

    # Remove events_enabled from initiatives
    op.drop_column("initiatives", "events_enabled")
