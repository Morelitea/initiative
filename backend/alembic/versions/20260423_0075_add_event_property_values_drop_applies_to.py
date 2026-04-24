"""Add calendar_event_property_values and drop property_definitions.applies_to.

Extends the Custom Properties feature to calendar events by introducing
``calendar_event_property_values`` (mirrors ``document_property_values`` /
``task_property_values``), and simplifies ``property_definitions`` by
removing the ``applies_to`` column + ``property_applies_to`` enum.

Pre-rename, ``applies_to`` gated which entity kinds a definition could
attach to. Post initiative scope, every definition belongs to exactly one
initiative and is expected to apply everywhere in that initiative — so the
enum adds configuration surface area without carrying its weight. Adding a
third entity kind (events) would also have required expanding the enum with
new combinations; dropping it avoids that combinatoric growth.

Downgrade restores the column with a default of ``'both'`` — per-row
original values are lost.

Revision ID: 20260423_0075
Revises: 20260422_0074
Create Date: 2026-04-23
"""

from alembic import op
from sqlalchemy import text

revision = "20260423_0075"
down_revision = "20260422_0074"
branch_labels = None
depends_on = None


# RLS session-variable helpers (mirror of the 0074 migration).
USER_ID = "NULLIF(current_setting('app.current_user_id'::text, true), ''::text)::integer"
GUILD_ROLE = "current_setting('app.current_guild_role'::text, true)"
IS_SUPER = "current_setting('app.is_superadmin'::text, true) = 'true'::text"
IS_ADMIN = f"{GUILD_ROLE} = 'admin'::text"
BYPASS = f"OR ({IS_ADMIN}) OR ({IS_SUPER})"


def _event_value_rls_expr() -> str:
    """RLS predicate for calendar_event_property_values.

    Enforces:
      * the event's initiative matches the definition's initiative
        (blocks cross-initiative attach attempts)
      * the current user is a member of that initiative

    Simpler than the task variant — events carry ``initiative_id`` directly,
    so no ``projects`` hop is needed.
    """
    return (
        "EXISTS ("
        "SELECT 1 FROM calendar_events ce "
        "JOIN property_definitions pd ON pd.id = calendar_event_property_values.property_id "
        "WHERE ce.id = calendar_event_property_values.event_id "
        "AND ce.initiative_id = pd.initiative_id "
        f"AND is_initiative_member(pd.initiative_id, ({USER_ID}))"
        ")"
    )


def _add_event_value_rls(conn) -> None:
    """Single-policy-per-command RLS for calendar_event_property_values."""
    table = "calendar_event_property_values"
    conn.execute(text(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY"))
    conn.execute(text(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY"))

    bypass_expr = f"(({_event_value_rls_expr()}) {BYPASS})"

    conn.execute(text(
        f"CREATE POLICY initiative_member_select ON {table} "
        f"AS PERMISSIVE FOR SELECT USING ({bypass_expr})"
    ))
    conn.execute(text(
        f"CREATE POLICY initiative_member_insert ON {table} "
        f"AS PERMISSIVE FOR INSERT WITH CHECK ({bypass_expr})"
    ))
    conn.execute(text(
        f"CREATE POLICY initiative_member_update ON {table} "
        f"AS PERMISSIVE FOR UPDATE USING ({bypass_expr}) WITH CHECK ({bypass_expr})"
    ))
    conn.execute(text(
        f"CREATE POLICY initiative_member_delete ON {table} "
        f"AS PERMISSIVE FOR DELETE USING ({bypass_expr})"
    ))


def _drop_event_value_rls(conn) -> None:
    for policy in (
        "initiative_member_select",
        "initiative_member_insert",
        "initiative_member_update",
        "initiative_member_delete",
    ):
        conn.execute(text(
            f"DROP POLICY IF EXISTS {policy} ON calendar_event_property_values"
        ))
    conn.execute(text(
        "ALTER TABLE calendar_event_property_values DISABLE ROW LEVEL SECURITY"
    ))


def upgrade() -> None:
    conn = op.get_bind()

    # -- calendar_event_property_values --
    conn.execute(text("""
        CREATE TABLE calendar_event_property_values (
            event_id INTEGER NOT NULL REFERENCES calendar_events(id) ON DELETE CASCADE,
            property_id INTEGER NOT NULL REFERENCES property_definitions(id) ON DELETE CASCADE,
            value_text TEXT,
            value_number NUMERIC,
            value_boolean BOOLEAN,
            value_date DATE,
            value_datetime TIMESTAMPTZ,
            value_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
            value_json JSONB,
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            PRIMARY KEY (event_id, property_id)
        )
    """))

    junction = "calendar_event_property_values"
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

    conn.execute(text(f"GRANT ALL PRIVILEGES ON TABLE {junction} TO app_admin"))

    _add_event_value_rls(conn)

    # -- Drop property_definitions.applies_to + enum --
    conn.execute(text("ALTER TABLE property_definitions DROP COLUMN applies_to"))
    conn.execute(text("DROP TYPE property_applies_to"))


def downgrade() -> None:
    conn = op.get_bind()

    # Recreate property_applies_to enum + applies_to column (defaults to
    # 'both' — per-row history is not recoverable).
    conn.execute(text(
        "CREATE TYPE property_applies_to AS ENUM ('document', 'task', 'both')"
    ))
    conn.execute(text(
        "ALTER TABLE property_definitions "
        "ADD COLUMN applies_to property_applies_to NOT NULL DEFAULT 'both'"
    ))

    # Drop calendar_event_property_values RLS + table.
    _drop_event_value_rls(conn)
    conn.execute(text("DROP TABLE IF EXISTS calendar_event_property_values CASCADE"))
