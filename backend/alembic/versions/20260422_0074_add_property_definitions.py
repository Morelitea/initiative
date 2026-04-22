"""Add custom property definitions and value junction tables.

Creates the ``property_type`` and ``property_applies_to`` enums, the
guild-scoped ``property_definitions`` table, and the two typed-column
junction tables (``document_property_values`` and ``task_property_values``)
that store property values for documents and tasks. Applies guild-scoped
RLS to the definitions table and junction-through-parent RLS (with a
fallback to initiative membership for global documents that have
``guild_id IS NULL``) to the value tables.

Revision ID: 20260422_0074
Revises: 20260421_0073
Create Date: 2026-04-22
"""

from alembic import op
from sqlalchemy import text

revision = "20260422_0074"
down_revision = "20260421_0073"
branch_labels = None
depends_on = None


# ---------------------------------------------------------------------------
# RLS session-variable helpers (mirrors calendar_events migration template)
# ---------------------------------------------------------------------------
GUILD_ID = "current_setting('app.current_guild_id'::text, true)::int"
USER_ID = "NULLIF(current_setting('app.current_user_id'::text, true), ''::text)::integer"
GUILD_ROLE = "current_setting('app.current_guild_role'::text, true)"
IS_SUPER = "current_setting('app.is_superadmin'::text, true) = 'true'::text"
IS_ADMIN = f"{GUILD_ROLE} = 'admin'::text"
BYPASS = f"OR ({IS_ADMIN}) OR ({IS_SUPER})"


def _document_value_rls_expr() -> str:
    """RLS predicate for document_property_values.

    Enforces that:
      * the definition belongs to the same guild as the document (blocking
        cross-guild attach attempts)
      * the current session has access to the document via guild or
        initiative membership (fallback for ``guild_id IS NULL`` global docs)
    """
    return (
        "EXISTS ("
        "SELECT 1 FROM documents d "
        "JOIN property_definitions pd ON pd.id = document_property_values.property_id "
        "WHERE d.id = document_property_values.document_id "
        f"AND ((d.guild_id = pd.guild_id "
        f"      AND (d.guild_id = ({GUILD_ID}) OR ({IS_SUPER}))) "
        f"     OR (d.guild_id IS NULL "
        f"         AND is_initiative_member(d.initiative_id, ({USER_ID}))))"
        ")"
    )


def _task_value_rls_expr() -> str:
    """RLS predicate for task_property_values.

    Tasks reach the initiative through ``projects`` and may have
    ``guild_id IS NULL``; the fallback to ``is_initiative_member`` routes
    via the owning project.
    """
    return (
        "EXISTS ("
        "SELECT 1 FROM tasks t "
        "JOIN projects proj ON proj.id = t.project_id "
        "JOIN property_definitions pd ON pd.id = task_property_values.property_id "
        "WHERE t.id = task_property_values.task_id "
        f"AND ((t.guild_id = pd.guild_id "
        f"      AND (t.guild_id = ({GUILD_ID}) OR ({IS_SUPER}))) "
        f"     OR (t.guild_id IS NULL "
        f"         AND is_initiative_member(proj.initiative_id, ({USER_ID}))))"
        ")"
    )


def _add_definition_rls(conn) -> None:
    """property_definitions uses the standard 4-policy guild pattern."""
    table = "property_definitions"
    conn.execute(text(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY"))
    conn.execute(text(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY"))

    # SELECT via membership
    member_check = (
        f"EXISTS (SELECT 1 FROM guild_memberships "
        f"WHERE guild_memberships.guild_id = {table}.guild_id "
        f"AND guild_memberships.user_id = ({USER_ID}))"
    )
    gid_eq = f"guild_id = ({GUILD_ID})"

    conn.execute(text(
        f"CREATE POLICY guild_select ON {table} "
        f"AS PERMISSIVE FOR SELECT "
        f"USING (({member_check}) OR ({IS_SUPER}))"
    ))
    conn.execute(text(
        f"CREATE POLICY guild_insert ON {table} "
        f"AS PERMISSIVE FOR INSERT "
        f"WITH CHECK (({gid_eq}) OR ({IS_SUPER}))"
    ))
    conn.execute(text(
        f"CREATE POLICY guild_update ON {table} "
        f"AS PERMISSIVE FOR UPDATE "
        f"USING (({gid_eq}) OR ({IS_SUPER})) "
        f"WITH CHECK (({gid_eq}) OR ({IS_SUPER}))"
    ))
    conn.execute(text(
        f"CREATE POLICY guild_delete ON {table} "
        f"AS PERMISSIVE FOR DELETE "
        f"USING (({gid_eq}) OR ({IS_SUPER}))"
    ))


def _add_value_rls(conn, junction_table: str, expr: str) -> None:
    """Junction-through-parent RLS for {document,task}_property_values."""
    conn.execute(text(f"ALTER TABLE {junction_table} ENABLE ROW LEVEL SECURITY"))
    conn.execute(text(f"ALTER TABLE {junction_table} FORCE ROW LEVEL SECURITY"))

    bypass_expr = f"(({expr}) {BYPASS})"

    # One policy per command so INSERT's WITH CHECK and SELECT's USING
    # line up cleanly with the baseline guild junction pattern.
    conn.execute(text(
        f"CREATE POLICY guild_select ON {junction_table} "
        f"AS PERMISSIVE FOR SELECT USING ({bypass_expr})"
    ))
    conn.execute(text(
        f"CREATE POLICY guild_insert ON {junction_table} "
        f"AS PERMISSIVE FOR INSERT WITH CHECK ({bypass_expr})"
    ))
    conn.execute(text(
        f"CREATE POLICY guild_update ON {junction_table} "
        f"AS PERMISSIVE FOR UPDATE USING ({bypass_expr}) WITH CHECK ({bypass_expr})"
    ))
    conn.execute(text(
        f"CREATE POLICY guild_delete ON {junction_table} "
        f"AS PERMISSIVE FOR DELETE USING ({bypass_expr})"
    ))


def _drop_rls(conn, table: str) -> None:
    for policy in ("guild_select", "guild_insert", "guild_update", "guild_delete"):
        conn.execute(text(f"DROP POLICY IF EXISTS {policy} ON {table}"))
    conn.execute(text(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY"))


def upgrade() -> None:
    conn = op.get_bind()

    # -- Enum types --
    conn.execute(text(
        "CREATE TYPE property_type AS ENUM ("
        "'text', 'number', 'checkbox', 'date', 'datetime', "
        "'url', 'select', 'multi_select', 'user_reference')"
    ))
    conn.execute(text(
        "CREATE TYPE property_applies_to AS ENUM ('document', 'task', 'both')"
    ))

    # -- property_definitions --
    conn.execute(text("""
        CREATE TABLE property_definitions (
            id SERIAL PRIMARY KEY,
            guild_id INTEGER NOT NULL REFERENCES guilds(id),
            name VARCHAR(100) NOT NULL,
            type property_type NOT NULL,
            applies_to property_applies_to NOT NULL DEFAULT 'both',
            position REAL NOT NULL DEFAULT 0,
            color VARCHAR(7),
            options JSONB,
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL
        )
    """))
    conn.execute(text(
        "CREATE INDEX ix_property_definitions_guild_id "
        "ON property_definitions (guild_id)"
    ))
    conn.execute(text(
        "CREATE UNIQUE INDEX ix_property_definitions_guild_lower_name "
        "ON property_definitions (guild_id, lower(name))"
    ))

    # -- document_property_values --
    conn.execute(text("""
        CREATE TABLE document_property_values (
            document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
            property_id INTEGER NOT NULL REFERENCES property_definitions(id) ON DELETE CASCADE,
            value_text TEXT,
            value_number NUMERIC,
            value_boolean BOOLEAN,
            value_date DATE,
            value_datetime TIMESTAMPTZ,
            value_user_id INTEGER REFERENCES users(id),
            value_json JSONB,
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            PRIMARY KEY (document_id, property_id)
        )
    """))

    # -- task_property_values --
    conn.execute(text("""
        CREATE TABLE task_property_values (
            task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
            property_id INTEGER NOT NULL REFERENCES property_definitions(id) ON DELETE CASCADE,
            value_text TEXT,
            value_number NUMERIC,
            value_boolean BOOLEAN,
            value_date DATE,
            value_datetime TIMESTAMPTZ,
            value_user_id INTEGER REFERENCES users(id),
            value_json JSONB,
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            PRIMARY KEY (task_id, property_id)
        )
    """))

    # -- Indexes on value tables --
    for junction in ("document_property_values", "task_property_values"):
        conn.execute(text(
            f"CREATE INDEX ix_{junction}_property_id "
            f"ON {junction} (property_id)"
        ))
        conn.execute(text(
            f"CREATE INDEX ix_{junction}_property_value_text "
            f"ON {junction} (property_id, value_text) "
            f"WHERE value_text IS NOT NULL"
        ))
        conn.execute(text(
            f"CREATE INDEX ix_{junction}_property_value_number "
            f"ON {junction} (property_id, value_number) "
            f"WHERE value_number IS NOT NULL"
        ))
        conn.execute(text(
            f"CREATE INDEX ix_{junction}_property_value_date "
            f"ON {junction} (property_id, value_date) "
            f"WHERE value_date IS NOT NULL"
        ))
        conn.execute(text(
            f"CREATE INDEX ix_{junction}_property_value_datetime "
            f"ON {junction} (property_id, value_datetime) "
            f"WHERE value_datetime IS NOT NULL"
        ))
        conn.execute(text(
            f"CREATE INDEX ix_{junction}_property_value_user_id "
            f"ON {junction} (property_id, value_user_id) "
            f"WHERE value_user_id IS NOT NULL"
        ))
        conn.execute(text(
            f"CREATE INDEX ix_{junction}_property_json_gin "
            f"ON {junction} USING GIN (value_json jsonb_path_ops) "
            f"WHERE value_json IS NOT NULL"
        ))

    # -- Grants --
    for table in ("property_definitions", "document_property_values", "task_property_values"):
        conn.execute(text(f"GRANT ALL PRIVILEGES ON TABLE {table} TO app_admin"))
    conn.execute(text(
        "GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO app_admin"
    ))

    # -- RLS --
    _add_definition_rls(conn)
    _add_value_rls(conn, "document_property_values", _document_value_rls_expr())
    _add_value_rls(conn, "task_property_values", _task_value_rls_expr())


def downgrade() -> None:
    conn = op.get_bind()

    # Drop RLS policies
    for table in ("document_property_values", "task_property_values", "property_definitions"):
        _drop_rls(conn, table)

    # Drop tables (CASCADE handles any lingering references)
    conn.execute(text("DROP TABLE IF EXISTS document_property_values CASCADE"))
    conn.execute(text("DROP TABLE IF EXISTS task_property_values CASCADE"))
    conn.execute(text("DROP TABLE IF EXISTS property_definitions CASCADE"))

    # Drop enum types
    conn.execute(text("DROP TYPE IF EXISTS property_applies_to"))
    conn.execute(text("DROP TYPE IF EXISTS property_type"))
