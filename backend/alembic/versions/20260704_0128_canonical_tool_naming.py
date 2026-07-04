"""canonical tool naming

Rename every per-tool name to the stem derived from the canonical ``Tool``
enum (``{plural}_enabled`` / ``create_{plural}`` / ``can_view_{plural}``):

- ``initiatives`` master-switch columns: ``events_enabled`` →
  ``calendar_events_enabled``, ``advanced_tool_enabled`` →
  ``advanced_tools_enabled``, ``counters_enabled`` → ``counter_groups_enabled``.
- ``initiative_role_permissions.permission_key`` values rewritten to the new
  ``PermissionKey`` spellings (stored strings, part of the composite PK; the
  mapping is injective so no conflicts are possible).
- ``recent_views`` CHECK constraint extended with ``calendar_event`` (recents
  now cover calendar events).

Pre-v1 breaking rename — no compatibility shims, downgrade restores the old
names exactly.
"""

from alembic import op

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20260704_0128"
down_revision = "20260704_0127"
branch_labels = None
depends_on = None


_COLUMN_RENAMES = [
    ("events_enabled", "calendar_events_enabled"),
    ("advanced_tool_enabled", "advanced_tools_enabled"),
    ("counters_enabled", "counter_groups_enabled"),
]

_PERMISSION_KEY_RENAMES = [
    ("docs_enabled", "documents_enabled"),
    ("create_docs", "create_documents"),
    ("events_enabled", "calendar_events_enabled"),
    ("create_events", "create_calendar_events"),
    ("advanced_tool_enabled", "advanced_tools_enabled"),
    ("create_advanced_tool", "create_advanced_tools"),
    ("counters_enabled", "counter_groups_enabled"),
    ("create_counters", "create_counter_groups"),
]

_OLD_RECENT_TYPES = (
    "'project'::text, 'document'::text, 'queue'::text, 'counter_group'::text"
)
_NEW_RECENT_TYPES = _OLD_RECENT_TYPES + ", 'calendar_event'::text"

_OLD_PERMISSION_KEYS = [
    "docs_enabled",
    "projects_enabled",
    "create_docs",
    "create_projects",
    "queues_enabled",
    "create_queues",
    "events_enabled",
    "create_events",
    "advanced_tool_enabled",
    "create_advanced_tool",
    "counters_enabled",
    "create_counters",
]
_NEW_PERMISSION_KEYS = [
    dict(_PERMISSION_KEY_RENAMES).get(key, key) for key in _OLD_PERMISSION_KEYS
]


def _rewrite_permission_keys(renames: list[tuple[str, str]]) -> None:
    cases = " ".join(
        f"WHEN permission_key = '{old}' THEN '{new}'" for old, new in renames
    )
    olds = ", ".join(f"'{old}'" for old, _new in renames)
    op.execute(
        f"UPDATE initiative_role_permissions "
        f"SET permission_key = CASE {cases} ELSE permission_key END "
        f"WHERE permission_key IN ({olds})"
    )


def _swap_permission_key_check(keys: list[str]) -> None:
    values = ", ".join(f"'{key}'" for key in keys)
    op.execute(
        "ALTER TABLE initiative_role_permissions "
        "DROP CONSTRAINT IF EXISTS ck_initiative_role_permissions_permission_key"
    )
    op.execute(
        "ALTER TABLE initiative_role_permissions "
        "ADD CONSTRAINT ck_initiative_role_permissions_permission_key "
        f"CHECK (permission_key::text = ANY (ARRAY[{values}]::text[]))"
    )


def _swap_recent_check(types: str) -> None:
    op.execute(
        "ALTER TABLE recent_views DROP CONSTRAINT IF EXISTS ck_recent_views_entity_type"
    )
    op.execute(
        "ALTER TABLE recent_views ADD CONSTRAINT ck_recent_views_entity_type "
        f"CHECK (entity_type = ANY (ARRAY[{types}]))"
    )


def _recent_views_trigger_fn(entity_tables: list[tuple[str, str]]) -> str:
    """Render public.fn_recent_views_set_guild_id with one CASE arm per
    recentable entity type (the trigger denormalizes guild_id from the entity's
    own table; a type with no arm makes every INSERT fail with
    CaseNotFoundError)."""
    arms = "\n".join(
        f"""                    WHEN '{etype}' THEN
                        SELECT guild_id INTO NEW.guild_id FROM {table}
                        WHERE id = NEW.entity_id;"""
        for etype, table in entity_tables
    )
    return f"""
        CREATE OR REPLACE FUNCTION public.fn_recent_views_set_guild_id() RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF NEW.guild_id IS NULL OR (TG_OP = 'UPDATE' AND (
                OLD.entity_type IS DISTINCT FROM NEW.entity_type
                OR OLD.entity_id IS DISTINCT FROM NEW.entity_id
            )) THEN
                CASE NEW.entity_type
{arms}
                END CASE;
            END IF;
            RETURN NEW;
        END;
        $$
    """


_OLD_ENTITY_TABLES = [
    ("project", "projects"),
    ("document", "documents"),
    ("queue", "queues"),
    ("counter_group", "counter_groups"),
]
_NEW_ENTITY_TABLES = _OLD_ENTITY_TABLES + [("calendar_event", "calendar_events")]


def upgrade() -> None:
    # Shared public-schema trigger function: one replacement, not per guild.
    op.execute(_recent_views_trigger_fn(_NEW_ENTITY_TABLES))
    run_for_each_guild_schema(op.get_bind(), _apply_upgrade)


def _apply_upgrade() -> None:
    for old, new in _COLUMN_RENAMES:
        op.alter_column("initiatives", old, new_column_name=new)
    # Constraint first (widened), then the data rewrite, then re-pin to the
    # new values only.
    _swap_permission_key_check(_OLD_PERMISSION_KEYS + _NEW_PERMISSION_KEYS)
    _rewrite_permission_keys(_PERMISSION_KEY_RENAMES)
    _swap_permission_key_check(_NEW_PERMISSION_KEYS)
    _swap_recent_check(_NEW_RECENT_TYPES)


def downgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_downgrade)
    op.execute(_recent_views_trigger_fn(_OLD_ENTITY_TABLES))


def _apply_downgrade() -> None:
    op.execute("DELETE FROM recent_views WHERE entity_type = 'calendar_event'")
    _swap_recent_check(_OLD_RECENT_TYPES)
    _swap_permission_key_check(_OLD_PERMISSION_KEYS + _NEW_PERMISSION_KEYS)
    _rewrite_permission_keys([(new, old) for old, new in _PERMISSION_KEY_RENAMES])
    _swap_permission_key_check(_OLD_PERMISSION_KEYS)
    for old, new in _COLUMN_RENAMES:
        op.alter_column("initiatives", new, new_column_name=old)
