"""Documents are files in public

The shared half of 20261006_0464:

* **Type** — ``public.document_type`` is ``public.file_type``. Its values do
  not change: a file is ``native``, ``file``, ``whiteboard``, ``smart_link``
  or ``spreadsheet``.
* **Notices** — a notification, and one still queued, names the file kind and
  its address the new way: ``tool``, ``subject_type``, ``entity_type`` and
  ``context_entity_type`` say ``file``, a ``/go/document/N`` address is ``/go/file/N``
  and a ``…/documents/N`` page path is ``…/files/N`` (each also in the encoded
  form a link carries), and a thread's rollup key is
  ``file:`` or ``file-body:``. Unread lines never expire, so the stored ones
  are rewritten.
* **Scopes** — a plug-in service's scope ceiling names ``files:read`` and
  ``files:write``.
* **Listings** — a tool listing of files is a ``file`` listing, and what a
  tool listing's versions store (its envelope and its example) names files
  the way an export now does: ``initiative-file``, ``files`` and
  ``file_type``, a ``file:N`` ref and the tool's two permissions. A dashboard
  listing's statements read ``files`` and ``file_type`` (string values left
  as written), and its sheet widgets name ``file_id``. A plug-in's own
  manifest is not rewritten: one still asking for ``documents:*`` is refused
  until its publisher republishes it.
* **View preferences** — the ones saved for the documents views
  (``documents`` and ``documents:…``) are removed; those views are the files
  views now and start from their defaults.

``public.member_departs`` and ``public.search_entry_write`` are rendered by a
start from the registries, and the provisioning stamp moved with this change,
so the next boot restates them before any request is served.

The downgrade reverses each rewrite; the removed view preferences stay removed.

Revision ID: 20261006_0465
Revises: 20261006_0464
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

revision = "20261006_0465"
down_revision = "20261006_0464"
branch_labels = None
depends_on = None


_TYPES = ("document_type", "file_type")
#: The payload keys that hold a kind.
_KIND_KEYS = ("tool", "subject_type", "entity_type", "context_entity_type")
_KIND = {"document": "file"}
#: An address that names the tool — its ``/go/`` reference and its page path —
#: as a path and as a link carries it encoded.
_ADDRESSES = {
    "/go/document/": "/go/file/",
    "/documents/": "/files/",
    "%2Fgo%2Fdocument%2F": "%2Fgo%2Ffile%2F",
    "%2Fdocuments%2F": "%2Ffiles%2F",
}
_ROLLUP_PREFIXES = {"document:": "file:", "document-body:": "file-body:"}
_SCOPES = {"documents:read": "files:read", "documents:write": "files:write"}
_VIEW_PREFERENCES = "scope_key = 'documents' OR starts_with(scope_key, 'documents:')"
#: Listing kinds that are not a tool's: their definitions are not envelopes.
_NOT_TOOL_LISTINGS = ("plugin", "auto", "profile_pack")
#: How an envelope names files: its keys, its type, its refs and permissions.
_ENVELOPE_KEYS = {"documents": "files", "document_type": "file_type"}
_ENVELOPE_TYPES = {"initiative-document": "initiative-file"}
_REF_KEYS = ("external_ref", "importSourceRef")
_PERMISSIONS = {
    "documents_enabled": "files_enabled",
    "create_documents": "create_files",
}
#: What a dashboard listing's statements, bindings and widgets name.
_DATASET_WORDS = {
    "documents": "files",
    "document_versions": "file_versions",
    "document_type": "file_type",
    "document_id": "file_id",
}
_SHEET_KEY = {"document_id": "file_id"}
#: A statement's string values, single- or dollar-quoted: left as written.
_QUOTED = re.compile(r"'(?:[^']|'')*'|\$(\w*)\$.*?\$\1\$", re.S)


def _flip(mapping: Mapping[str, str], forward: bool) -> dict[str, str]:
    return dict(mapping) if forward else {new: old for old, new in mapping.items()}


def _writable(bind: Connection, table: str, fn: Callable[[], None]) -> None:
    """Run ``fn`` with ``table``'s row security unforced and its user triggers
    held, both restored either way."""
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


def _rename_type(bind: Connection, forward: bool) -> None:
    old, new = _TYPES if forward else _TYPES[::-1]
    if bind.execute(text("SELECT to_regtype(:t)"), {"t": f"public.{old}"}).scalar():
        bind.exec_driver_sql(f"ALTER TYPE public.{old} RENAME TO {new}")


def _payload(
    bind: Connection, table: str, column: str, cast: str, forward: bool
) -> None:
    """A notice's JSON: the kinds it names, its addresses and its rollup key."""
    doc = f"CAST({column} AS jsonb)"
    for key in _KIND_KEYS:
        for old, new in _flip(_KIND, forward).items():
            bind.execute(
                text(
                    f"UPDATE {table} SET {column} = CAST(jsonb_set({doc}, "
                    f"'{{{key}}}', to_jsonb(CAST(:new AS text))) AS {cast}) "
                    f"WHERE {doc} ->> '{key}' = :old"
                ),
                {"old": old, "new": new},
            )
    for old, new in _flip(_ADDRESSES, forward).items():
        bind.execute(
            text(
                f"UPDATE {table} SET {column} = CAST(replace(CAST({column} AS text), "
                f":old, :new) AS {cast}) WHERE strpos(CAST({column} AS text), :old) > 0"
            ),
            {"old": old, "new": new},
        )
    for old, new in _flip(_ROLLUP_PREFIXES, forward).items():
        bind.execute(
            text(
                f"UPDATE {table} SET {column} = CAST(jsonb_set({doc}, '{{rollup_key}}', "
                f"to_jsonb(CAST(:new AS text) || substr({doc} ->> 'rollup_key', "
                f"length(CAST(:old AS text)) + 1))) "
                f"AS {cast}) WHERE starts_with({doc} ->> 'rollup_key', :old)"
            ),
            {"old": old, "new": new},
        )


def _notifications(bind: Connection, forward: bool) -> None:
    kind = _flip(_KIND, forward)

    def run() -> None:
        for column in ("tool", "subject_type"):
            for old, new in kind.items():
                bind.execute(
                    text(
                        f"UPDATE public.notifications SET {column} = :new "
                        f"WHERE {column} = :old"
                    ),
                    {"old": old, "new": new},
                )
        _payload(bind, "public.notifications", "data", "json", forward)

    _writable(bind, "public.notifications", run)


def _notice_outbox(bind: Connection, forward: bool) -> None:
    def run() -> None:
        _payload(bind, "public.notice_outbox", "data", "jsonb", forward)
        _payload(bind, "public.notice_outbox", "push_data", "jsonb", forward)
        for old, new in _flip(_ADDRESSES, forward).items():
            bind.execute(
                text(
                    "UPDATE public.notice_outbox SET email_link = "
                    "replace(email_link, :old, :new) WHERE strpos(email_link, :old) > 0"
                ),
                {"old": old, "new": new},
            )
        for old, new in _flip(_ROLLUP_PREFIXES, forward).items():
            bind.execute(
                text(
                    "UPDATE public.notice_outbox SET rollup_key = "
                    "CAST(:new AS text) || substr(rollup_key, length(CAST(:old AS text)) + 1) "
                    "WHERE starts_with(rollup_key, :old)"
                ),
                {"old": old, "new": new},
            )

    _writable(bind, "public.notice_outbox", run)


def _scope_ceilings(bind: Connection, forward: bool) -> None:
    def run() -> None:
        bind.execute(
            text(
                "UPDATE public.plugin_service_registrations SET scope_ceiling = "
                "ARRAY(SELECT coalesce(CAST(:pairs AS jsonb) ->> CAST(v AS text), "
                "CAST(v AS text)) FROM unnest(scope_ceiling) WITH ORDINALITY "
                "AS u(v, i) ORDER BY i) WHERE EXISTS (SELECT 1 FROM "
                "unnest(scope_ceiling) v WHERE CAST(:pairs AS jsonb) ? CAST(v AS text))"
            ),
            {"pairs": json.dumps(_flip(_SCOPES, forward))},
        )

    _writable(bind, "public.plugin_service_registrations", run)


def _statement(sql: str, words: Mapping[str, str]) -> str:
    def respell(part: str) -> str:
        for old, new in words.items():
            part = re.sub(rf"\b{re.escape(old)}\b", new, part)
        return part

    parts: list[str] = []
    last = 0
    for quoted in _QUOTED.finditer(sql):
        parts += [respell(sql[last : quoted.start()]), quoted.group(0)]
        last = quoted.end()
    return "".join(parts) + respell(sql[last:])


def _envelope_respeller(forward: bool, dashboard: bool) -> Callable[[Any], Any]:
    """A tool listing's envelope, spelled the way an export of this build
    spells it. A dashboard's also has its statements and sheet keys."""
    keys = _flip(_ENVELOPE_KEYS, forward)
    if dashboard:
        keys = {**keys, **_flip(_SHEET_KEY, forward)}
    kinds = _flip(_KIND, forward)
    types = _flip(_ENVELOPE_TYPES, forward)
    permissions = _flip(_PERMISSIONS, forward)
    words = _flip(_DATASET_WORDS, forward)

    def respell(value: Any) -> Any:
        if isinstance(value, list):
            return [respell(item) for item in value]
        if not isinstance(value, dict):
            return value
        out = {keys.get(key, key): respell(item) for key, item in value.items()}
        if isinstance(out.get("type"), str):
            out["type"] = types.get(out["type"], out["type"])
        for key in ("tool", "entity"):
            if isinstance(out.get(key), str):
                out[key] = kinds.get(out[key], out[key])
        for key in _REF_KEYS:
            ref = out.get(key)
            if isinstance(ref, str):
                kind, colon, rest = ref.partition(":")
                if colon and kind in kinds:
                    out[key] = f"{kinds[kind]}:{rest}"
        if isinstance(out.get("permissions"), dict):
            out["permissions"] = {
                permissions.get(key, key): item
                for key, item in out["permissions"].items()
            }
        if dashboard and isinstance(out.get("sql"), str):
            out["sql"] = _statement(out["sql"], words)
        return out

    return respell


def _listings(bind: Connection, forward: bool) -> None:
    kinds = _flip(_KIND, forward)

    def run_kinds() -> None:
        for old, new in kinds.items():
            bind.execute(
                text(
                    "UPDATE public.marketplace_listings SET kind = :new WHERE kind = :old"
                ),
                {"old": old, "new": new},
            )

    def run_versions() -> None:
        rows = bind.execute(
            text(
                "SELECT v.id, l.kind, v.definition, v.example "
                "FROM public.marketplace_listing_versions v "
                "JOIN public.marketplace_listings l ON l.id = v.listing_id "
                "WHERE l.kind <> ALL(:skip)"
            ),
            {"skip": list(_NOT_TOOL_LISTINGS)},
        ).all()
        for version_id, kind, definition, example in rows:
            respell = _envelope_respeller(forward, kind == "dashboard")
            changed = {}
            for column, value in (("definition", definition), ("example", example)):
                if value is None:
                    continue
                if isinstance(value, str):
                    value = json.loads(value)
                respelled = respell(value)
                if respelled != value:
                    changed[column] = json.dumps(respelled)
            for column, value in changed.items():
                bind.execute(
                    text(
                        f"UPDATE public.marketplace_listing_versions "
                        f"SET {column} = CAST(:v AS jsonb) WHERE id = :id"
                    ),
                    {"v": value, "id": version_id},
                )

    _writable(bind, "public.marketplace_listings", run_kinds)
    _writable(bind, "public.marketplace_listing_versions", run_versions)


def upgrade() -> None:
    bind = op.get_bind()
    _rename_type(bind, True)
    _notifications(bind, True)
    _notice_outbox(bind, True)
    _scope_ceilings(bind, True)
    _listings(bind, True)
    _writable(
        bind,
        "public.user_view_preferences",
        lambda: bind.exec_driver_sql(
            f"DELETE FROM public.user_view_preferences WHERE {_VIEW_PREFERENCES}"
        ),
    )


def downgrade() -> None:
    bind = op.get_bind()
    _listings(bind, False)
    _scope_ceilings(bind, False)
    _notice_outbox(bind, False)
    _notifications(bind, False)
    _rename_type(bind, False)
