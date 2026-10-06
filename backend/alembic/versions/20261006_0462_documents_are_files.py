"""Documents are files

The documents tool is the files tool. In ``guild_template`` and every
``guild_<id>``:

* **Tables** — ``documents`` is ``files`` and ``document_file_versions`` is
  ``file_versions``, with their sequences, keys and indexes named to match.
  The index ``idx_documents_updated_at``, which no model declares, is dropped.
* **Columns** — ``files.document_type`` is ``file_type``,
  ``file_versions.document_id`` and ``comments.document_id`` are ``file_id``,
  ``initiatives.documents_enabled`` is ``files_enabled`` and
  ``wikis.document_positions`` is ``file_positions``.
* **Triggers** — the two this chain set on the tables keep their jobs under the
  new names, and the owner-row trigger names the kind ``file``. The rest a
  start renders from the registries, so they are dropped here and the next
  boot renders them again under the new names, before any request is served;
  the search generation is cleared so that boot re-sweeps the index.
* **Stored values** — the kind ``document`` is ``file`` (sharing, property
  values, recent views, relationships, search entries, reactions, the
  reaction digest, moderation reports), and a digest line's address says
  ``/go/file/N`` or ``…/files/N``; the resource
  ``documents`` is ``files`` (the change log and its parents, webhook event
  types); the column names a change or a subscription lists follow the
  columns; the scopes ``documents:read``/``documents:write`` are ``files:*``
  (an install's grant and its definition); the role permissions
  ``documents_enabled``/``create_documents`` are ``files_enabled``/
  ``create_files``; a dashboard's statements read the datasets ``files`` and
  ``file_versions`` and the columns ``file_type`` and ``file_id``, and a
  binding names its spreadsheet as ``file_id`` and its kind as ``file``; a queued export or import names
  the tool ``file``. A role missing either permission row gets it at its
  default, as each tool's backfill does. The CHECK constraints holding the kind are restated for
  the writes; ``ck_comments_single_parent`` follows its column on its own.

``public.relationship_kind_code`` names the kind ``file`` (still code 6)
before the edges are rewritten, since their node columns are computed from it.
The rewrites run with each table's row security unforced and its user
triggers held: nothing changed about the rows but their spelling.

Stored editor content is left as it was written; the reference reader takes
``document`` as the file kind.

Revision ID: 20261006_0462
Revises: 20261006_0461
Create Date: 2026-10-06
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from typing import Any

from alembic import op
from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20261006_0462"
down_revision = "20261006_0461"
branch_labels = None
depends_on = None


_TABLES = (("documents", "files"), ("document_file_versions", "file_versions"))
#: (table under its new name, old column, new column)
_COLUMNS = (
    ("files", "document_type", "file_type"),
    ("file_versions", "document_id", "file_id"),
    ("comments", "document_id", "file_id"),
    ("initiatives", "documents_enabled", "files_enabled"),
    ("wikis", "document_positions", "file_positions"),
)
#: (table under its new name, old constraint, new constraint)
_CONSTRAINTS = (
    ("files", "documents_pkey", "files_pkey"),
    ("files", "documents_initiative_id_fkey", "files_initiative_id_fkey"),
    ("files", "documents_current_version_id_fkey", "files_current_version_id_fkey"),
    ("file_versions", "document_file_versions_pkey", "file_versions_pkey"),
    (
        "file_versions",
        "document_file_versions_document_id_fkey",
        "file_versions_file_id_fkey",
    ),
    ("file_versions", "uq_dfv_document_version", "uq_fv_file_version"),
    ("comments", "comments_document_id_fkey", "comments_file_id_fkey"),
)
_INDEXES = (
    ("ix_documents_active", "ix_files_active"),
    ("ix_documents_current_version_id", "ix_files_current_version_id"),
    ("ix_documents_initiative_id", "ix_files_initiative_id"),
    ("ix_documents_name", "ix_files_name"),
    ("ix_documents_purge", "ix_files_purge"),
    ("ix_document_file_versions_document_id", "ix_file_versions_file_id"),
    ("ix_comments_document_id", "ix_comments_file_id"),
)
_SEQUENCES = (
    ("documents_id_seq", "files_id_seq"),
    ("document_file_versions_id_seq", "file_versions_id_seq"),
)
_DRIFT_INDEX = "idx_documents_updated_at"
#: The triggers this chain set on the two tables, by their old names.
_SET_TRIGGERS = (
    ("tr_documents_set_created_by", "tr_files_set_created_by"),
    ("tr_document_file_versions_set_created_by", "tr_file_versions_set_created_by"),
)
_OWNS_TRIGGERS = ("tr_documents_install_owns", "tr_files_install_owns")

#: (table, constraint) — the CHECKs that hold a kind or a permission.
_CHECKS = (
    ("initiative_role_permissions", "ck_initiative_role_permissions_permission_key"),
    ("property_values", "ck_property_values_entity_type"),
    ("recent_views", "ck_recent_views_entity_type"),
    ("relationships", "ck_relationships_source_type"),
    ("relationships", "ck_relationships_target_type"),
    ("search_entries", "ck_search_entries_entity_type"),
)

#: The value each name takes; the downgrade reads them the other way.
_KIND = {"document": "file"}
_RESOURCE = {"documents": "files"}
_FIELDS = {
    "document_type": "file_type",
    "document_id": "file_id",
    "documents_enabled": "files_enabled",
    "document_positions": "file_positions",
}
_PERMISSIONS = {
    "documents_enabled": "files_enabled",
    "create_documents": "create_files",
}
_SCOPES = {"documents:read": "files:read", "documents:write": "files:write"}
#: Names a dashboard's statement reads: datasets and their columns.
_DATASET_WORDS = {
    "documents": "files",
    "document_versions": "file_versions",
    "document_type": "file_type",
    "document_id": "file_id",
}
#: Keys a queued export or import names the tool by.
_JOB_KEYS = {"document": "file", "document_ids": "file_ids"}
_ENVELOPE_TYPES = {"initiative-document": "initiative-file"}
#: An address that names the tool: its ``/go/`` reference and its page path.
_ADDRESSES = {"/go/document/": "/go/file/", "/documents/": "/files/"}
#: The key a binding names its spreadsheet by (a sheet range's).
_SHEET_KEY = {"document_id": "file_id"}

# Permission key -> the value a role created at this revision stores, every
# key, as 20261004_0453 states it with the file tool's two respelled. The
# rewrite moves every stored row; this makes whole any role missing one.
_ROLE_PERMISSION_DEFAULTS: dict[str, bool] = {
    "projects_enabled": True,
    "files_enabled": True,
    "queues_enabled": False,
    "counter_groups_enabled": False,
    "calendars_enabled": False,
    "dashboards_enabled": False,
    "posts_enabled": False,
    "galleries_enabled": False,
    "wikis_enabled": False,
    "create_projects": False,
    "create_files": False,
    "create_queues": False,
    "create_counter_groups": False,
    "create_calendars": False,
    "create_dashboards": False,
    "create_posts": False,
    "create_galleries": False,
    "create_wikis": False,
    "dashboards_run_as_initiative": False,
}


def backfill_sql(defaults: dict[str, bool]) -> str:
    """The INSERT this revision runs, unqualified so it applies in whichever
    guild schema the search_path names. A built-in manager role holds every
    key; everything else gets the default."""
    values = ", ".join(
        f"('{key}', {'true' if enabled else 'false'})"
        for key, enabled in sorted(defaults.items())
    )
    return f"""
        INSERT INTO initiative_role_permissions
            (initiative_role_id, permission_key, enabled)
        SELECT r.id,
               k.permission_key,
               CASE
                   WHEN r.is_builtin AND r.is_manager THEN true
                   ELSE k.enabled
               END
        FROM initiative_roles AS r
        CROSS JOIN (VALUES {values}) AS k(permission_key, enabled)
        ON CONFLICT (initiative_role_id, permission_key) DO NOTHING
    """


#: ``public.relationship_kind_code``: kind -> its permanent code. The file kind
#: keeps 6, so every stored node id stays what it was.
_KIND_CODES_BEFORE = (
    ("calendar", 1),
    ("calendar_event", 2),
    ("counter", 3),
    ("counter_group", 4),
    ("dashboard", 5),
    ("document", 6),
    ("gallery", 7),
    ("gallery_image", 8),
    ("post", 9),
    ("project", 10),
    ("queue", 11),
    ("queue_item", 12),
    ("tag", 13),
    ("task", 14),
    ("wiki", 15),
    ("wiki_page", 16),
)
_KIND_CODES_AFTER = tuple(
    (_KIND.get(kind, kind), code) for kind, code in _KIND_CODES_BEFORE
)

_CLEAR_SEARCH_GENERATION = "COMMENT ON TABLE search_entries IS NULL"


def _flip(mapping: Mapping[str, str], forward: bool) -> dict[str, str]:
    return dict(mapping) if forward else {new: old for old, new in mapping.items()}


def _kind_code_fn(codes: tuple[tuple[str, int], ...]) -> str:
    arms = " ".join(f"WHEN '{kind}' THEN {code}" for kind, code in codes)
    return f"""
        CREATE OR REPLACE FUNCTION public.relationship_kind_code(kind text)
        RETURNS bigint LANGUAGE sql IMMUTABLE STRICT AS $$
            SELECT (CASE kind {arms} END)::bigint
        $$
    """


def _exists(bind: Connection, sql: str, params: dict[str, Any]) -> bool:
    return bind.execute(text(sql), params).scalar() is not None


def _table_exists(bind: Connection, table: str) -> bool:
    return bool(bind.execute(text("SELECT to_regclass(:t)"), {"t": table}).scalar())


def _has_column(bind: Connection, table: str, column: str) -> bool:
    return _exists(
        bind,
        "SELECT 1 FROM pg_attribute WHERE attrelid = to_regclass(:t) "
        "AND attname = :c AND NOT attisdropped",
        {"t": table, "c": column},
    )


def _has_constraint(bind: Connection, table: str, name: str) -> bool:
    return _exists(
        bind,
        "SELECT 1 FROM pg_constraint WHERE conrelid = to_regclass(:t) AND conname = :n",
        {"t": table, "n": name},
    )


# --- structure ---------------------------------------------------------------


def _rename_structure(bind: Connection, forward: bool) -> None:
    """Tables, columns, keys, indexes and sequences, in the current schema."""
    tables = _TABLES if forward else tuple((new, old) for old, new in _TABLES)
    for old, new in tables:
        if _table_exists(bind, old):
            bind.exec_driver_sql(f"ALTER TABLE {old} RENAME TO {new}")

    def table_now(name: str) -> str:
        """A table this list names by its new name, as it is called now."""
        return name if forward else dict((n, o) for o, n in _TABLES).get(name, name)

    for table, old, new in _COLUMNS:
        old, new = (old, new) if forward else (new, old)
        if _has_column(bind, table_now(table), old):
            bind.exec_driver_sql(
                f"ALTER TABLE {table_now(table)} RENAME COLUMN {old} TO {new}"
            )
    for table, old, new in _CONSTRAINTS:
        old, new = (old, new) if forward else (new, old)
        if _has_constraint(bind, table_now(table), old):
            bind.exec_driver_sql(
                f"ALTER TABLE {table_now(table)} RENAME CONSTRAINT {old} TO {new}"
            )
    for old, new in _INDEXES:
        old, new = (old, new) if forward else (new, old)
        bind.exec_driver_sql(f"ALTER INDEX IF EXISTS {old} RENAME TO {new}")
    for old, new in _SEQUENCES:
        old, new = (old, new) if forward else (new, old)
        bind.exec_driver_sql(f"ALTER SEQUENCE IF EXISTS {old} RENAME TO {new}")
    if forward:
        bind.exec_driver_sql(f"DROP INDEX IF EXISTS {_DRIFT_INDEX}")


def _replace_triggers(bind: Connection, forward: bool) -> None:
    """Rename the triggers this chain set, re-attach the owner row under the
    kind's name, and drop the ones a start renders (it renders them again).

    Runs while the two tables carry their new names: after the upgrade's
    renames, and before the downgrade's."""
    renames = dict(_SET_TRIGGERS if forward else ((n, o) for o, n in _SET_TRIGGERS))
    owns_old, owns_new = _OWNS_TRIGGERS if forward else _OWNS_TRIGGERS[::-1]
    kind = "file" if forward else "document"
    had_owns = False
    for _old, table in _TABLES:
        names = bind.execute(
            text(
                "SELECT tgname FROM pg_trigger WHERE tgrelid = to_regclass(:t) "
                "AND NOT tgisinternal ORDER BY tgname"
            ),
            {"t": table},
        ).scalars()
        for name in list(names):
            if name in renames:
                bind.exec_driver_sql(
                    f"ALTER TRIGGER {name} ON {table} RENAME TO {renames[name]}"
                )
                continue
            had_owns = had_owns or name == owns_old
            bind.exec_driver_sql(f"DROP TRIGGER {name} ON {table}")
    if had_owns:
        bind.exec_driver_sql(
            f"CREATE TRIGGER {owns_new} AFTER INSERT ON files "
            "FOR EACH ROW EXECUTE FUNCTION "
            f"public.fn_install_owns_what_it_creates('{kind}')"
        )


def _drop_checks(bind: Connection) -> dict[tuple[str, str], str]:
    """Drop the CHECKs that hold a kind, returning each one's definition."""
    dropped: dict[tuple[str, str], str] = {}
    for table, name in _CHECKS:
        definition = bind.execute(
            text(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conrelid = to_regclass(:t) AND conname = :n"
            ),
            {"t": table, "n": name},
        ).scalar()
        if definition is None:
            continue
        bind.exec_driver_sql(f"ALTER TABLE {table} DROP CONSTRAINT {name}")
        dropped[(table, name)] = definition
    return dropped


def _restore_checks(
    bind: Connection, dropped: dict[tuple[str, str], str], forward: bool
) -> None:
    """Put each CHECK back with the values it holds respelled."""
    values = {**_flip(_KIND, forward), **_flip(_PERMISSIONS, forward)}
    for (table, name), definition in dropped.items():
        for old, new in values.items():
            definition = definition.replace(f"'{old}'::", f"'{new}'::")
        bind.exec_driver_sql(f"ALTER TABLE {table} ADD CONSTRAINT {name} {definition}")


# --- stored values -----------------------------------------------------------


def _writable(bind: Connection, table: str, fn: Callable[[], None]) -> None:
    """Run ``fn`` with ``table``'s row security unforced and its user triggers
    held, both restored either way."""
    if not _table_exists(bind, table):
        return
    forced = bool(
        bind.execute(
            text(
                "SELECT relforcerowsecurity FROM pg_class WHERE oid = to_regclass(:t)"
            ),
            {"t": table},
        ).scalar()
    )
    if forced:
        bind.exec_driver_sql(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
    bind.exec_driver_sql(f"ALTER TABLE {table} DISABLE TRIGGER USER")
    try:
        fn()
    finally:
        bind.exec_driver_sql(f"ALTER TABLE {table} ENABLE TRIGGER USER")
        if forced:
            bind.exec_driver_sql(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")


def _set_values(
    bind: Connection, table: str, columns: tuple[str, ...], mapping: Mapping[str, str]
) -> None:
    def run() -> None:
        for column in columns:
            for old, new in mapping.items():
                bind.execute(
                    text(f"UPDATE {table} SET {column} = :new WHERE {column} = :old"),
                    {"old": old, "new": new},
                )

    _writable(bind, table, run)


def _replace_in(
    bind: Connection, table: str, column: str, mapping: Mapping[str, str]
) -> None:
    """Replace each substring in a text column."""

    def run() -> None:
        for old, new in mapping.items():
            bind.execute(
                text(
                    f"UPDATE {table} SET {column} = replace({column}, :old, :new) "
                    f"WHERE strpos({column}, :old) > 0"
                ),
                {"old": old, "new": new},
            )

    _writable(bind, table, run)


def _map_array(
    bind: Connection,
    table: str,
    column: str,
    mapping: Mapping[str, str],
    *,
    prefix: bool = False,
) -> None:
    """Respell each element of a text array: a whole element, or with
    ``prefix`` its leading part (``documents.`` in ``documents.updated``)."""
    if prefix:
        match = "starts_with(CAST(v AS text), m.key)"
        element = "m.value || substr(CAST(v AS text), length(m.key) + 1)"
    else:
        match = "CAST(v AS text) = m.key"
        element = "m.value"
    pairs = "jsonb_each_text(CAST(:pairs AS jsonb)) m"

    def run() -> None:
        bind.execute(
            text(
                f"UPDATE {table} SET {column} = ARRAY("
                f"SELECT coalesce((SELECT {element} FROM {pairs} WHERE {match} "
                "LIMIT 1), CAST(v AS text)) "
                f"FROM unnest({column}) WITH ORDINALITY AS u(v, i) ORDER BY i) "
                f"WHERE EXISTS (SELECT 1 FROM unnest({column}) v, {pairs} "
                f"WHERE {match})"
            ),
            {"pairs": json.dumps(mapping)},
        )

    _writable(bind, table, run)


def _respell_json(
    bind: Connection, table: str, column: str, respell: Callable[[Any], Any]
) -> None:
    def run() -> None:
        rows = bind.execute(
            text(f"SELECT id, {column} FROM {table} WHERE {column} IS NOT NULL")
        ).all()
        for row_id, value in rows:
            if isinstance(value, str):
                value = json.loads(value)
            respelled = respell(value)
            if respelled != value:
                bind.execute(
                    text(
                        f"UPDATE {table} SET {column} = CAST(:v AS jsonb) WHERE id = :id"
                    ),
                    {"v": json.dumps(respelled), "id": row_id},
                )

    _writable(bind, table, run)


def _statement(sql: str, words: Mapping[str, str]) -> str:
    for old, new in words.items():
        sql = re.sub(rf"\b{re.escape(old)}\b", new, sql)
    return sql


def _definition_respeller(forward: bool) -> Callable[[Any], Any]:
    """A dashboard's or an install's definition: its scopes, its statements,
    and the file a binding names and the kind it names it as."""
    scopes = _flip(_SCOPES, forward)
    words = _flip(_DATASET_WORDS, forward)
    sheet_old, sheet_new = next(iter(_flip(_SHEET_KEY, forward).items()))
    kinds = _flip(_KIND, forward)

    def respell(value: Any) -> Any:
        if isinstance(value, list):
            return [respell(item) for item in value]
        if isinstance(value, str):
            return scopes.get(value, value)
        if not isinstance(value, dict):
            return value
        out: dict[str, Any] = {}
        for key, item in value.items():
            if key == "sql" and isinstance(item, str):
                out[key] = _statement(item, words)
            else:
                out[scopes.get(key, key)] = respell(item)
        if "source" in out and sheet_old in out:
            out[sheet_new] = out.pop(sheet_old)
        if out.get("entity") in kinds:
            out["entity"] = kinds[out["entity"]]
        return out

    return respell


def _job_respeller(forward: bool) -> Callable[[Any], Any]:
    """A queued job's parameters: the tool keys its maps and ids use, and an
    envelope type."""
    keys = _flip(_JOB_KEYS, forward)
    types = _flip(_ENVELOPE_TYPES, forward)

    def respell(value: Any) -> Any:
        if isinstance(value, list):
            return [respell(item) for item in value]
        if isinstance(value, str):
            return types.get(value, value)
        if isinstance(value, dict):
            return {keys.get(key, key): respell(item) for key, item in value.items()}
        return value

    return respell


def _parents(bind: Connection, mapping: Mapping[str, str]) -> None:
    """The change log's parents: ``[{"id": 2, "type": "documents"}]``."""

    def run() -> None:
        bind.execute(
            text(
                "UPDATE event_outbox SET parents = (SELECT jsonb_agg(CASE "
                "WHEN CAST(:pairs AS jsonb) ? (p ->> 'type') THEN jsonb_set(p, "
                "'{type}', CAST(:pairs AS jsonb) -> (p ->> 'type')) ELSE p END "
                "ORDER BY i) FROM jsonb_array_elements(parents) WITH ORDINALITY "
                "AS e(p, i)) WHERE jsonb_typeof(parents) = 'array' AND EXISTS ("
                "SELECT 1 FROM jsonb_array_elements(parents) p "
                "WHERE CAST(:pairs AS jsonb) ? (p ->> 'type'))"
            ),
            {"pairs": json.dumps(mapping)},
        )

    _writable(bind, "event_outbox", run)


def _respell_values(bind: Connection, forward: bool) -> None:
    kind = _flip(_KIND, forward)
    resource = _flip(_RESOURCE, forward)
    fields = _flip(_FIELDS, forward)

    _set_values(bind, "resource_grants", ("resource_type",), kind)
    _set_values(bind, "property_values", ("entity_type",), kind)
    _set_values(bind, "recent_views", ("entity_type",), kind)
    _set_values(bind, "relationships", ("source_type", "target_type"), kind)
    _set_values(bind, "search_entries", ("entity_type", "dac_tool"), kind)
    _set_values(bind, "reactions", ("target_type",), kind)
    _set_values(bind, "reaction_digest_items", ("target_type",), kind)
    _replace_in(
        bind, "reaction_digest_items", "target_path", _flip(_ADDRESSES, forward)
    )
    _set_values(bind, "moderation_reports", ("target_type",), kind)
    _set_values(
        bind,
        "initiative_role_permissions",
        ("permission_key",),
        _flip(_PERMISSIONS, forward),
    )

    _set_values(bind, "event_outbox", ("resource_type",), resource)
    _parents(bind, resource)
    _map_array(bind, "event_outbox", "changed", fields)
    _map_array(
        bind,
        "webhook_subscriptions",
        "event_types",
        {f"{old}.": f"{new}." for old, new in resource.items()},
        prefix=True,
    )
    _map_array(bind, "webhook_subscriptions", "fields", fields)

    _map_array(bind, "guild_plugins", "granted_scopes", _flip(_SCOPES, forward))
    definitions = _definition_respeller(forward)
    _respell_json(bind, "guild_plugins", "definition", definitions)
    _respell_json(bind, "dashboards", "definition", definitions)

    jobs = _job_respeller(forward)
    _set_values(bind, "export_jobs", ("source",), kind)
    _respell_json(bind, "export_jobs", "params", jobs)
    _set_values(bind, "import_jobs", ("source",), _flip(_ENVELOPE_TYPES, forward))
    _respell_json(bind, "import_jobs", "params", jobs)


# --- entry points ------------------------------------------------------------


def _apply(forward: bool) -> None:
    bind = op.get_bind()
    checks = _drop_checks(bind)
    if forward:
        _rename_structure(bind, forward)
        _replace_triggers(bind, forward)
    else:
        _replace_triggers(bind, forward)
        _rename_structure(bind, forward)
    _respell_values(bind, forward)
    _restore_checks(bind, checks, forward)
    if forward:
        _writable(
            bind,
            "initiative_role_permissions",
            lambda: bind.exec_driver_sql(backfill_sql(_ROLE_PERMISSION_DEFAULTS)),
        )
    bind.exec_driver_sql(_CLEAR_SEARCH_GENERATION)


def upgrade() -> None:
    bind = op.get_bind()
    bind.exec_driver_sql(_kind_code_fn(_KIND_CODES_AFTER))
    run_for_each_guild_schema(bind, lambda: _apply(True))


def downgrade() -> None:
    bind = op.get_bind()
    bind.exec_driver_sql(_kind_code_fn(_KIND_CODES_BEFORE))
    run_for_each_guild_schema(bind, lambda: _apply(False))
