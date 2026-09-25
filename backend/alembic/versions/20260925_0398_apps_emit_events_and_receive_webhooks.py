"""apps emit events and receive webhooks

Three tables.

- ``public.app_installs`` indexes every install across communities: the
  listing it came from, the community and install, whether it is switched on,
  and ``hook_route``, the value a vendor webhook is routed to it by. It lists
  an app's installs and routes its webhooks without visiting a guild schema.
  It is the system engine's alone: ``app_admin`` reads and writes it; the
  login role and the guild and platform floors, which the schema default
  grants full DML on a new table, are revoked; the seat and install floors
  take no default privileges and are granted nothing. RLS is enabled and
  forced with no policies (``FORCED_NO_POLICY`` in ``app.db.public_rls``).
  Existing installs are carried in from each guild schema before it is
  locked down.
- ``app_event_outbox``, in every guild schema: the events installed apps
  emit, delivered by the outbox poller.
- ``app_hook_deliveries``, in every guild schema: the vendor webhook
  deliveries an install accepted, kept 24 hours.

The guild tables' policies are rendered from the registries at boot.

Revision ID: 20260925_0398
Revises: 20260925_0397
Create Date: 2026-09-25
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.core.config import settings
from app.db.guild_migrations import guild_schema_names, run_for_each_guild_schema

revision = "20260925_0398"
down_revision = "20260925_0397"
branch_labels = None
depends_on = None

INSTALLS = "app_installs"
EVENTS = "app_event_outbox"
DELIVERIES = "app_hook_deliveries"

#: One community's installs, with the value its app's webhooks route by: the
#: stored field of the static connection the pinned definition names.
_CARRY = """
INSERT INTO public.app_installs
    (guild_id, install_id, listing_uid, enabled, hook_route)
SELECT {guild_id}, a.id, a.listing_uid, a.enabled,
       a.config -> (a.definition #>> '{{webhooks,route,connection}}')
                ->> (a.definition #>> '{{webhooks,route,field}}')
FROM "{schema}".guild_apps a
WHERE a.listing_uid IS NOT NULL
  AND EXISTS (SELECT 1 FROM public.guilds g WHERE g.id = {guild_id})
"""


def _platform_base() -> str:
    return f"{settings.PLATFORM_ROLE_PREFIX}platform_base"


def upgrade() -> None:
    op.create_table(
        INSTALLS,
        sa.Column("guild_id", sa.Integer(), nullable=False),
        sa.Column("install_id", sa.Integer(), nullable=False),
        sa.Column("listing_uid", sa.String(length=14), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("hook_route", sa.String(length=200), nullable=True),
        sa.ForeignKeyConstraint(["guild_id"], ["guilds.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("guild_id", "install_id"),
    )
    op.create_index(
        "ix_app_installs_hook_route", INSTALLS, ["listing_uid", "hook_route"]
    )
    op.create_index(
        "ix_app_installs_listing", INSTALLS, ["listing_uid", "guild_id", "install_id"]
    )

    bind = op.get_bind()
    for schema in guild_schema_names(bind):
        if schema == "guild_template":
            continue
        guild_id = int(schema.removeprefix("guild_"))
        op.execute(_CARRY.format(guild_id=guild_id, schema=schema))

    base = _platform_base()
    for statement in (
        f"ALTER TABLE public.{INSTALLS} ENABLE ROW LEVEL SECURITY",
        f"ALTER TABLE public.{INSTALLS} FORCE ROW LEVEL SECURITY",
        f'REVOKE ALL ON TABLE public.{INSTALLS} FROM app_user, app_guild_base, "{base}"',
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.{INSTALLS} TO app_admin",
    ):
        op.execute(statement)

    run_for_each_guild_schema(bind, _create_guild_tables)


def _create_guild_tables() -> None:
    op.create_table(
        EVENTS,
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("txn_id", sa.BigInteger(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("install_id", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=200), nullable=False),
        sa.Column("initiative_id", sa.Integer(), nullable=True),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(f"ix_{EVENTS}_txn_id", EVENTS, ["txn_id"])
    op.create_index(f"ix_{EVENTS}_occurred_at", EVENTS, ["occurred_at"])
    op.create_index(f"ix_{EVENTS}_initiative_id", EVENTS, ["initiative_id"])

    op.create_table(
        DELIVERIES,
        sa.Column("install_id", sa.Integer(), nullable=False),
        sa.Column("delivery_id", sa.String(length=200), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["install_id"], ["guild_apps.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("install_id", "delivery_id"),
    )
    op.create_index(f"ix_{DELIVERIES}_expires_at", DELIVERIES, ["expires_at"])

    for table in (EVENTS, DELIVERIES):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _drop_guild_tables)
    op.execute(f"ALTER TABLE public.{INSTALLS} NO FORCE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE public.{INSTALLS} DISABLE ROW LEVEL SECURITY")
    op.drop_index("ix_app_installs_listing", table_name=INSTALLS)
    op.drop_index("ix_app_installs_hook_route", table_name=INSTALLS)
    op.drop_table(INSTALLS)


def _drop_guild_tables() -> None:
    # Named in the schema being walked, never resolved through the search
    # path's fallback to ``public``. Indexes and policies go with each table.
    for table in (DELIVERIES, EVENTS):
        op.execute(
            "DO $$ BEGIN EXECUTE format("
            f"'DROP TABLE IF EXISTS %I.{table}', current_schema()); END $$;"
        )
