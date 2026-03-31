"""Add automation tables for the automation engine execution logs.

Creates automation_flows (source of truth for flow definitions),
automation_runs (execution history), and automation_run_steps (per-node logs).
Adds automation_engine PostgreSQL role with BYPASSRLS for direct writes.
Adds RLS policies with guild isolation and initiative-scoped RESTRICTIVE controls.

Revision ID: 20260331_0068
Revises: 20260330_0067
Create Date: 2026-03-31
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

revision = "20260331_0068"
down_revision = "20260330_0067"
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


def _init_member_direct(table: str) -> str:
    return (
        f"EXISTS ("
        f"SELECT 1 FROM initiatives "
        f"WHERE initiatives.id = {table}.initiative_id "
        f"AND is_initiative_member(initiatives.id, ({USER_ID}))"
        f")"
    )


def _init_member_via_run(table: str) -> str:
    return (
        f"EXISTS ("
        f"SELECT 1 FROM automation_runs "
        f"WHERE automation_runs.id = {table}.run_id "
        f"AND EXISTS ("
        f"  SELECT 1 FROM initiatives "
        f"  WHERE initiatives.id = automation_runs.initiative_id "
        f"  AND is_initiative_member(initiatives.id, ({USER_ID}))"
        f")"
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


def _add_run_steps_rls(conn, table: str, membership_expr: str) -> None:
    """RLS for automation_run_steps — no guild_id column, so no guild isolation layer."""
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

    # -- Create automation_engine PostgreSQL role --
    # The role is created without a password. The deployer must set one via:
    #   ALTER ROLE automation_engine WITH PASSWORD 'your-secure-password';
    # or by using peer/cert authentication in pg_hba.conf.
    conn.execute(text("""
        DO $$ BEGIN
            CREATE ROLE automation_engine WITH LOGIN;
        EXCEPTION WHEN DUPLICATE_OBJECT THEN
            NULL;
        END $$
    """))
    conn.execute(text("ALTER ROLE automation_engine BYPASSRLS"))

    # -- automation_flows --
    op.create_table(
        "automation_flows",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("guild_id", sa.Integer(), nullable=False),
        sa.Column("initiative_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("flow_data", sa.JSON(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_by_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["guild_id"], ["guilds.id"]),
        sa.ForeignKeyConstraint(["initiative_id"], ["initiatives.id"]),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_automation_flows_guild_id", "automation_flows", ["guild_id"])
    op.create_index("ix_automation_flows_initiative_id", "automation_flows", ["initiative_id"])

    # -- automation_runs --
    op.create_table(
        "automation_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("guild_id", sa.Integer(), nullable=False),
        sa.Column("flow_id", sa.Integer(), nullable=False),
        sa.Column("initiative_id", sa.Integer(), nullable=False),
        sa.Column("flow_snapshot", sa.JSON(), nullable=False),
        sa.Column("trigger_event", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["guild_id"], ["guilds.id"]),
        sa.ForeignKeyConstraint(["flow_id"], ["automation_flows.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["initiative_id"], ["initiatives.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_automation_runs_guild_id", "automation_runs", ["guild_id"])
    op.create_index("ix_automation_runs_initiative_id", "automation_runs", ["initiative_id"])
    op.create_index("ix_automation_runs_flow_id", "automation_runs", ["flow_id"])

    # -- automation_run_steps --
    op.create_table(
        "automation_run_steps",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("node_id", sa.String(255), nullable=False),
        sa.Column("node_type", sa.String(50), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("input_data", sa.JSON(), nullable=True),
        sa.Column("output_data", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["automation_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_automation_run_steps_run_id", "automation_run_steps", ["run_id"])

    # -- RLS policies --
    _add_rls_policies(conn, "automation_flows", _init_member_direct("automation_flows"))
    _add_rls_policies(conn, "automation_runs", _init_member_direct("automation_runs"))
    _add_run_steps_rls(conn, "automation_run_steps", _init_member_via_run("automation_run_steps"))

    # -- Grant privileges to app_admin --
    for table in ("automation_flows", "automation_runs", "automation_run_steps"):
        conn.execute(text(f"GRANT ALL PRIVILEGES ON TABLE {table} TO app_admin"))
    conn.execute(text(
        "GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO app_admin"
    ))

    # -- Grant engine-specific privileges --
    conn.execute(text("GRANT SELECT ON automation_flows TO automation_engine"))
    conn.execute(text("GRANT SELECT ON initiatives TO automation_engine"))
    conn.execute(text("GRANT SELECT, INSERT, UPDATE ON automation_runs TO automation_engine"))
    conn.execute(text("GRANT SELECT, INSERT, UPDATE ON automation_run_steps TO automation_engine"))
    conn.execute(text("GRANT USAGE, SELECT ON SEQUENCE automation_flows_id_seq TO automation_engine"))
    conn.execute(text("GRANT USAGE, SELECT ON SEQUENCE automation_runs_id_seq TO automation_engine"))
    conn.execute(text("GRANT USAGE, SELECT ON SEQUENCE automation_run_steps_id_seq TO automation_engine"))


def downgrade() -> None:
    conn = op.get_bind()

    # Drop RLS
    for table in ("automation_run_steps", "automation_runs", "automation_flows"):
        _drop_rls(conn, table)

    # Drop tables
    op.drop_table("automation_run_steps")
    op.drop_table("automation_runs")
    op.drop_table("automation_flows")

    # Drop role
    conn.execute(text("DROP ROLE IF EXISTS automation_engine"))
