"""Apps are plug-ins: rename every stored name the marketplace concept carried.

The code now says ``plugin`` wherever it said ``app`` for something a community
installs. This revision moves the database to match, with nothing kept under
the old names:

* **Tables** — three in ``public`` (``plugin_assertion_jtis``,
  ``plugin_installs``, ``plugin_service_registrations``) and eight in every
  guild schema and ``guild_template`` (``guild_plugins``,
  ``guild_plugin_secrets``, ``guild_plugin_user_connections``,
  ``plugin_event_outbox``, ``plugin_hook_deliveries``,
  ``plugin_member_consents``, ``plugin_placements``, ``plugin_schedule_runs``).
* **Columns** — ``plugin_kind``, ``plugin_id``, ``plugin_install_id`` and the
  stored signing key's ``plugin_platform_signing_key_encrypted``.
* **Names derived from them** — primary keys, foreign keys, unique and check
  constraints, indexes, sequences and the migration-owned
  ``tr_guild_plugins_set_created_by`` trigger, found in the catalog by an
  ``app`` segment in their name. The deployment's own ``app_settings`` /
  ``app_setting_secrets`` objects and the login roles' ``users_app_*``
  policies name the application, not a plug-in, and keep their names.
* **Policies** — ``app_scope_*`` on each guild table an install reaches
  becomes ``plugin_scope_*``, renamed in place so the restriction never lapses;
  provisioning re-renders it under that name.
* **Functions and triggers whose bodies name a table** —
  ``fn_place_following_plugins`` and ``fn_plugin_secret_fields`` are created
  with the new table names and their triggers re-pointed; the old functions
  are dropped. The change-capture trigger on ``guild_plugins`` is dropped:
  its arguments carry the published resource type, and provisioning renders
  ``capture_guild_plugins`` with ``plugins`` on the next boot, before any
  request is served.
* **Roles** — each ``guild_<id>_app`` becomes ``guild_<id>_plugin``, renamed
  when the new name is free; when both exist, this database's privileges move
  to the new role and the old one is dropped. The install floor is one role the
  whole cluster shares, so it is never renamed: ``plugin_install_base`` is
  created, this database's privileges and its own guild roles' memberships move
  to it, and ``app_install_base`` is dropped only once no other database in the
  cluster still holds anything through it.
* **Stored values** — a reference's purpose ``app`` is ``plugin``, and its
  rendered prefix follows (``uapp_…`` -> ``uplu_…``); a listing's ``kind``
  ``app`` is ``plugin``; scopes ``apps:<id>`` are ``plugins:<id>``; a widget
  type ``app:<uid>:<widget>`` is ``plugin:…`` with its binding's ``source``
  ``plugin`` and ``plugin_uid``; a definition's ``app_kind`` is
  ``plugin_kind``; webhook event types and pending outbox rows say
  ``plugins``. The rewrite runs with user triggers off: nothing about the rows
  changed but their spelling, so nothing is captured or delivered for it.

A plug-in that kept a reference minted before this revision holds the old
prefix and must be given the new one by its operator.

Revision ID: 20261005_0457
Revises: 20261005_0456
Create Date: 2026-10-05
"""

from __future__ import annotations

import json
import re
import string
from collections.abc import Callable
from typing import Any

from alembic import op
from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.db.guild_migrations import guild_schema_names

revision = "20261005_0457"
down_revision = "20261005_0456"
branch_labels = None
depends_on = None


_PUBLIC_TABLES = [
    ("app_assertion_jtis", "plugin_assertion_jtis"),
    ("app_installs", "plugin_installs"),
    ("app_service_registrations", "plugin_service_registrations"),
]
_GUILD_TABLES = [
    ("guild_apps", "guild_plugins"),
    ("guild_app_secrets", "guild_plugin_secrets"),
    ("guild_app_user_connections", "guild_plugin_user_connections"),
    ("app_event_outbox", "plugin_event_outbox"),
    ("app_hook_deliveries", "plugin_hook_deliveries"),
    ("app_member_consents", "plugin_member_consents"),
    ("app_placements", "plugin_placements"),
    ("app_schedule_runs", "plugin_schedule_runs"),
]
_PUBLIC_COLUMNS = [
    (
        "app_setting_secrets",
        "app_platform_signing_key_encrypted",
        "plugin_platform_signing_key_encrypted",
    ),
]
_GUILD_COLUMNS = [
    ("guild_plugins", "app_kind", "plugin_kind"),
    ("guild_plugin_user_connections", "app_id", "plugin_id"),
    ("resource_grants", "app_install_id", "plugin_install_id"),
    ("webhook_subscriptions", "app_install_id", "plugin_install_id"),
]

#: Catalog names that say ``app`` for the application, not a plug-in.
_KEEP = re.compile(
    r"^(app_settings?|app_setting_secrets|ck_app_settings|fk_app_settings|users_app_)"
)
_APP_SEGMENT = re.compile(r"(?<![a-z0-9])apps?(?![a-z0-9])")

_OLD_FLOOR = "app_install_base"
_NEW_FLOOR = "plugin_install_base"

_ALLOWED_IDENT_CHARS = frozenset(string.ascii_letters + string.digits + "_")

_PLACE_FUNCTION = """
CREATE OR REPLACE FUNCTION public.fn_place_following_plugins() RETURNS trigger
    LANGUAGE plpgsql AS $place$
BEGIN
    IF NEW.is_builtin AND NEW.name = 'moderator' THEN
        EXECUTE format(
            'INSERT INTO %I.plugin_placements '
            '(install_id, initiative_id, role_ids, created_at, updated_at) '
            'SELECT a.id, $1, ARRAY[$2]::integer[], now(), now() '
            'FROM %I.guild_plugins a WHERE a.follows_new_initiatives '
            'ON CONFLICT DO NOTHING',
            TG_TABLE_SCHEMA, TG_TABLE_SCHEMA
        ) USING NEW.initiative_id, NEW.id;
    END IF;
    RETURN NULL;
END;
$place$;
"""

_SECRET_FIELDS_FUNCTION = """
CREATE OR REPLACE FUNCTION public.fn_plugin_secret_fields() RETURNS trigger
    LANGUAGE plpgsql AS $secret_fields$
DECLARE
    v_install integer;
    v_secrets jsonb := '{}'::jsonb;
    v_fields jsonb;
BEGIN
    IF TG_OP = 'DELETE' THEN
        v_install := OLD.install_id;
    ELSE
        v_install := NEW.install_id;
        v_secrets := NEW.secrets;
    END IF;
    SELECT COALESCE(jsonb_object_agg(c.key, (
        SELECT COALESCE(jsonb_object_agg(
            f.key, encode(sha256(convert_to(f.value, 'UTF8')), 'hex')
        ), '{}'::jsonb)
        FROM jsonb_each_text(c.value) f
    )), '{}'::jsonb)
    INTO v_fields
    FROM jsonb_each(v_secrets) c
    WHERE jsonb_typeof(c.value) = 'object';
    EXECUTE format(
        $q$UPDATE %I.guild_plugins SET secret_fields = $1
            WHERE id = $2 AND secret_fields IS DISTINCT FROM $1$q$,
        TG_TABLE_SCHEMA
    ) USING v_fields, v_install;
    RETURN NULL;
END;
$secret_fields$;
"""


def _ident(name: str) -> str:
    """Quote a catalog or literal identifier after holding it to the allow-list."""
    if not name or not set(name) <= _ALLOWED_IDENT_CHARS:
        raise ValueError(f"unsafe identifier for DDL: {name!r}")
    return f'"{name}"'


def _renamed(name: str) -> str | None:
    """``name`` with each ``app``/``apps`` segment spelled ``plugin``/``plugins``,
    or None when it keeps its name."""
    if _KEEP.match(name) or not _APP_SEGMENT.search(name):
        return None
    return _APP_SEGMENT.sub(
        lambda m: "plugins" if m.group() == "apps" else "plugin", name
    )


def _exists(bind: Connection, sql: str, **params: Any) -> bool:
    return bind.execute(text(sql), params).scalar() is not None


# --- structure ---------------------------------------------------------------


def _rename_tables_and_columns(
    bind: Connection,
    schema: str,
    tables: list[tuple[str, str]],
    columns: list[tuple[str, str, str]],
) -> None:
    for old, new in tables:
        if bind.execute(
            text("SELECT to_regclass(:t)"), {"t": f'"{schema}".{old}'}
        ).scalar():
            op.execute(
                f"ALTER TABLE {_ident(schema)}.{_ident(old)} RENAME TO {_ident(new)}"
            )
    for table, old, new in columns:
        has_old = bind.execute(
            text(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_schema = :s AND table_name = :t AND column_name = :c"
            ),
            {"s": schema, "t": table, "c": old},
        ).scalar()
        if has_old:
            op.execute(
                f"ALTER TABLE {_ident(schema)}.{_ident(table)} "
                f"RENAME COLUMN {_ident(old)} TO {_ident(new)}"
            )


def _rename_derived_names(bind: Connection, schema: str) -> None:
    """Constraints, indexes and sequences named after a renamed table or column."""
    constraints = bind.execute(
        text(
            "SELECT c.relname, co.conname FROM pg_constraint co "
            "JOIN pg_class c ON c.oid = co.conrelid "
            "JOIN pg_namespace n ON n.oid = co.connamespace "
            "WHERE n.nspname = :s ORDER BY 1, 2"
        ),
        {"s": schema},
    ).all()
    for table, name in constraints:
        new = _renamed(name)
        if new:
            op.execute(
                f"ALTER TABLE {_ident(schema)}.{_ident(table)} "
                f"RENAME CONSTRAINT {_ident(name)} TO {_ident(new)}"
            )
    # Indexes a constraint backs were renamed with it above.
    indexes = bind.execute(
        text(
            "SELECT i.relname FROM pg_index x "
            "JOIN pg_class i ON i.oid = x.indexrelid "
            "JOIN pg_namespace n ON n.oid = i.relnamespace "
            "WHERE n.nspname = :s "
            "AND NOT EXISTS (SELECT 1 FROM pg_constraint co WHERE co.conindid = i.oid) "
            "ORDER BY 1"
        ),
        {"s": schema},
    ).scalars()
    for name in list(indexes):
        new = _renamed(name)
        if new:
            op.execute(
                f"ALTER INDEX {_ident(schema)}.{_ident(name)} RENAME TO {_ident(new)}"
            )
    sequences = bind.execute(
        text("SELECT sequencename FROM pg_sequences WHERE schemaname = :s ORDER BY 1"),
        {"s": schema},
    ).scalars()
    for name in list(sequences):
        new = _renamed(name)
        if new:
            op.execute(
                f"ALTER SEQUENCE {_ident(schema)}.{_ident(name)} RENAME TO {_ident(new)}"
            )


def _rename_policies(bind: Connection, schema: str) -> None:
    policies = bind.execute(
        text(
            "SELECT c.relname, p.polname FROM pg_policy p "
            "JOIN pg_class c ON c.oid = p.polrelid "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = :s ORDER BY 1, 2"
        ),
        {"s": schema},
    ).all()
    for table, name in policies:
        new = _renamed(name)
        if new:
            op.execute(
                f"ALTER POLICY {_ident(name)} ON {_ident(schema)}.{_ident(table)} "
                f"RENAME TO {_ident(new)}"
            )


def _triggers(bind: Connection, schema: str) -> list[tuple[str, str]]:
    rows = bind.execute(
        text(
            "SELECT c.relname, tg.tgname FROM pg_trigger tg "
            "JOIN pg_class c ON c.oid = tg.tgrelid "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = :s AND NOT tg.tgisinternal ORDER BY 1, 2"
        ),
        {"s": schema},
    ).all()
    return [(table, name) for table, name in rows]


def _replace_guild_triggers(bind: Connection, schema: str) -> None:
    s = _ident(schema)
    for table, name in _triggers(bind, schema):
        if name == "capture_guild_apps":
            op.execute(f"DROP TRIGGER {_ident(name)} ON {s}.{_ident(table)}")
        elif name == "tr_guild_app_secrets_fields":
            op.execute(f"DROP TRIGGER {_ident(name)} ON {s}.{_ident(table)}")
            op.execute(
                f"CREATE OR REPLACE TRIGGER tr_guild_plugin_secrets_fields "
                f"AFTER INSERT OR UPDATE OR DELETE ON {s}.guild_plugin_secrets "
                "FOR EACH ROW EXECUTE FUNCTION public.fn_plugin_secret_fields()"
            )
        elif name == "tr_initiative_roles_place_following_apps":
            op.execute(f"DROP TRIGGER {_ident(name)} ON {s}.{_ident(table)}")
            op.execute(
                f"CREATE OR REPLACE TRIGGER tr_initiative_roles_place_following_plugins "
                f"AFTER INSERT ON {s}.initiative_roles "
                "FOR EACH ROW EXECUTE FUNCTION public.fn_place_following_plugins()"
            )
        else:
            new = _renamed(name)
            if new:
                op.execute(
                    f"ALTER TRIGGER {_ident(name)} ON {s}.{_ident(table)} RENAME TO {_ident(new)}"
                )


# --- roles -------------------------------------------------------------------


def _role_oid(bind: Connection, name: str) -> int | None:
    return bind.execute(
        text("SELECT oid FROM pg_roles WHERE rolname = :r"), {"r": name}
    ).scalar()


#: ``pg_default_acl.defaclobjtype`` -> what ``ALTER DEFAULT PRIVILEGES`` calls it.
_DEFAULT_ACL_OBJECTS = {
    "r": "TABLES",
    "S": "SEQUENCES",
    "f": "FUNCTIONS",
    "T": "TYPES",
    "n": "SCHEMAS",
}


def _move_privileges(
    bind: Connection, old: str, new: str, members: list[str] | None = None
) -> None:
    """Grant ``new`` what ``old`` holds in THIS database, then clear ``old`` here.

    ``members`` limits the memberships moved to this database's own roles; a
    role another database's guild holds keeps its membership of ``old``.

    Each privilege is revoked from ``old`` as it is granted to ``new``: the
    migration's login granted them and may take them back, where ``DROP OWNED
    BY`` would need the privileges of ``old`` itself, which it does not hold.
    """
    old_oid = _role_oid(bind, old)
    o, n = _ident(old), _ident(new)
    relations = bind.execute(
        text(
            "SELECT nsp.nspname, c.relname, c.relkind, a.privilege_type "
            "FROM pg_class c JOIN pg_namespace nsp ON nsp.oid = c.relnamespace, "
            "aclexplode(c.relacl) a WHERE a.grantee = :o"
        ),
        {"o": old_oid},
    ).all()
    for sch, rel, kind, priv in relations:
        what = "SEQUENCE" if kind == "S" else "TABLE"
        target = f"{what} {_ident(sch)}.{_ident(rel)}"
        op.execute(f"GRANT {priv} ON {target} TO {n}")
        op.execute(f"REVOKE {priv} ON {target} FROM {o}")
    columns = bind.execute(
        text(
            "SELECT nsp.nspname, c.relname, att.attname, a.privilege_type "
            "FROM pg_attribute att JOIN pg_class c ON c.oid = att.attrelid "
            "JOIN pg_namespace nsp ON nsp.oid = c.relnamespace, "
            "aclexplode(att.attacl) a WHERE a.grantee = :o"
        ),
        {"o": old_oid},
    ).all()
    for sch, rel, col, priv in columns:
        target = f"({_ident(col)}) ON {_ident(sch)}.{_ident(rel)}"
        op.execute(f"GRANT {priv} {target} TO {n}")
        op.execute(f"REVOKE {priv} {target} FROM {o}")
    functions = bind.execute(
        text(
            "SELECT p.oid::regprocedure::text FROM pg_proc p, aclexplode(p.proacl) a "
            "WHERE a.grantee = :o"
        ),
        {"o": old_oid},
    ).scalars()
    for signature in list(functions):
        op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO {n}")
        op.execute(f"REVOKE EXECUTE ON FUNCTION {signature} FROM {o}")
    schemas = bind.execute(
        text(
            "SELECT nsp.nspname, a.privilege_type FROM pg_namespace nsp, "
            "aclexplode(nsp.nspacl) a WHERE a.grantee = :o"
        ),
        {"o": old_oid},
    ).all()
    for sch, priv in schemas:
        op.execute(f"GRANT {priv} ON SCHEMA {_ident(sch)} TO {n}")
        op.execute(f"REVOKE {priv} ON SCHEMA {_ident(sch)} FROM {o}")
    defaults = bind.execute(
        text(
            "SELECT nsp.nspname, d.defaclobjtype, a.privilege_type "
            "FROM pg_default_acl d "
            "LEFT JOIN pg_namespace nsp ON nsp.oid = d.defaclnamespace, "
            "aclexplode(d.defaclacl) a "
            "WHERE a.grantee = :o AND d.defaclrole = "
            "(SELECT oid FROM pg_roles WHERE rolname = current_user)"
        ),
        {"o": old_oid},
    ).all()
    for sch, objtype, priv in defaults:
        scope = f" IN SCHEMA {_ident(sch)}" if sch else ""
        on = _DEFAULT_ACL_OBJECTS[objtype]
        op.execute(f"ALTER DEFAULT PRIVILEGES{scope} GRANT {priv} ON {on} TO {n}")
        op.execute(f"ALTER DEFAULT PRIVILEGES{scope} REVOKE {priv} ON {on} FROM {o}")
    held = list(
        bind.execute(
            text(
                "SELECT r.rolname FROM pg_auth_members m "
                "JOIN pg_roles r ON r.oid = m.member WHERE m.roleid = :o"
            ),
            {"o": old_oid},
        ).scalars()
    )
    for member in held if members is None else [m for m in held if m in members]:
        op.execute(f"GRANT {n} TO {_ident(member)}")
        if members is not None:
            op.execute(f"REVOKE {o} FROM {_ident(member)}")


def _drop_role_if_unheld(name: str) -> None:
    op.execute(
        f"""
        DO $$ BEGIN
            BEGIN
                DROP ROLE {_ident(name)};
            EXCEPTION WHEN dependent_objects_still_exist THEN
                NULL;
            END;
        END $$;
        """
    )


def _move_floor(bind: Connection, guild_roles: list[str]) -> None:
    """Give the install floor its new name without taking it from a sibling.

    The floor is one cluster-global role that every database in the cluster
    shares, unlike a guild's roles. This database's privileges and its own
    guild roles' memberships move to ``plugin_install_base``; the old role is
    dropped only when no other database still holds anything through it.
    """
    op.execute(
        f"""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{_NEW_FLOOR}') THEN
                CREATE ROLE {_ident(_NEW_FLOOR)} NOLOGIN;
            END IF;
        END $$;
        """
    )
    if _role_oid(bind, _OLD_FLOOR) is None:
        op.execute(f"GRANT USAGE ON SCHEMA public TO {_ident(_NEW_FLOOR)}")
        return
    _move_privileges(bind, _OLD_FLOOR, _NEW_FLOOR, members=guild_roles)
    _drop_role_if_unheld(_OLD_FLOOR)


def _converge_role(bind: Connection, old: str, new: str) -> None:
    if _role_oid(bind, old) is None:
        return
    if _role_oid(bind, new) is None:
        op.execute(f"ALTER ROLE {_ident(old)} RENAME TO {_ident(new)}")
        return
    _move_privileges(bind, old, new)
    _drop_role_if_unheld(old)


def _guild_role_prefix() -> str:
    """The guild-role prefix, read at APPLY time (the suite sets one)."""
    from app.core.config import settings

    prefix = settings.GUILD_ROLE_PREFIX
    if not set(prefix) <= _ALLOWED_IDENT_CHARS:
        raise ValueError(f"unsafe GUILD_ROLE_PREFIX for role DDL: {prefix!r}")
    return prefix


# --- stored values -----------------------------------------------------------

_SCOPE = re.compile(r"apps:[-.0-9_a-z]+")
_KEY_RENAMES = {"app_kind": "plugin_kind", "app_uid": "plugin_uid"}
#: ``app.<public_id>.<id>``: an endpoint or event a definition declares.
_ENDPOINT_ID = re.compile(r"app\.[-.0-9_a-z]+")
#: The keys an endpoint or event id is stored under, as a value or a list.
_ENDPOINT_KEYS = frozenset(
    {"id", "emit", "endpoint", "endpoint_id", "community_summary", "guild_summary"}
)
_ENDPOINT_LIST_KEYS = frozenset({"endpoints", "events", "emits"})


def _endpoint(value: Any) -> Any:
    if isinstance(value, str) and _ENDPOINT_ID.fullmatch(value):
        return "plugin." + value[len("app.") :]
    return value


def _respell(value: Any) -> Any:
    """A stored document with its plug-in names respelled."""
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            key = _KEY_RENAMES.get(key, key)
            # A map keyed by endpoint id (a widget's ``sample_data``) or by scope.
            key = _endpoint(key)
            if _SCOPE.fullmatch(key):
                key = "plugins:" + key[len("apps:") :]
            item = _respell(item)
            if key == "type" and isinstance(item, str) and item.startswith("app:"):
                item = "plugin:" + item[len("app:") :]
            elif key == "source" and item == "app":
                item = "plugin"
            elif key in _ENDPOINT_KEYS:
                item = _endpoint(item)
            elif key in _ENDPOINT_LIST_KEYS and isinstance(item, list):
                item = [_endpoint(entry) for entry in item]
            out[key] = item
        return out
    if isinstance(value, list):
        return [_respell(item) for item in value]
    if isinstance(value, str) and _SCOPE.fullmatch(value):
        return "plugins:" + value[len("apps:") :]
    return value


def _with_rows_writable(
    bind: Connection, schema: str, table: str, fn: Callable[[], None]
) -> None:
    """Run ``fn`` with the table's RLS unforced and its user triggers off."""
    qualified = f"{_ident(schema)}.{_ident(table)}"
    if not bind.execute(
        text("SELECT to_regclass(:t)"), {"t": f'"{schema}".{table}'}
    ).scalar():
        return
    forced = bool(
        bind.execute(
            text(
                "SELECT relforcerowsecurity FROM pg_class WHERE oid = to_regclass(:t)"
            ),
            {"t": f'"{schema}".{table}'},
        ).scalar()
    )
    if forced:
        bind.execute(text(f"ALTER TABLE {qualified} NO FORCE ROW LEVEL SECURITY"))
    bind.execute(text(f"ALTER TABLE {qualified} DISABLE TRIGGER USER"))
    try:
        fn()
    finally:
        bind.execute(text(f"ALTER TABLE {qualified} ENABLE TRIGGER USER"))
        if forced:
            bind.execute(text(f"ALTER TABLE {qualified} FORCE ROW LEVEL SECURITY"))


def _respell_json(
    bind: Connection, schema: str, table: str, column: str, cast: str = "jsonb"
) -> None:
    def run() -> None:
        rows = bind.execute(
            text(
                f"SELECT id, {_ident(column)} FROM {_ident(schema)}.{_ident(table)} "
                f"WHERE {_ident(column)} IS NOT NULL"
            )
        ).all()
        for row_id, document in rows:
            if isinstance(document, str):
                document = json.loads(document)
            respelled = _respell(document)
            if respelled != document:
                bind.execute(
                    text(
                        f"UPDATE {_ident(schema)}.{_ident(table)} "
                        f"SET {_ident(column)} = CAST(:d AS {cast}) WHERE id = :id"
                    ),
                    {"d": json.dumps(respelled), "id": row_id},
                )

    _with_rows_writable(bind, schema, table, run)


def _respell_array(
    bind: Connection,
    schema: str,
    table: str,
    column: str,
    pattern: str,
    old: str,
    new: str,
) -> None:
    col = _ident(column)
    qualified = f"{_ident(schema)}.{_ident(table)}"

    def run() -> None:
        bind.execute(
            text(
                f"UPDATE {qualified} SET {col} = ARRAY("
                f"SELECT CASE WHEN v ~ :p THEN :new || substr(v, :n) ELSE v END "
                f"FROM unnest({col}) WITH ORDINALITY AS u(v, i) ORDER BY i"
                f") WHERE EXISTS (SELECT 1 FROM unnest({col}) v WHERE v ~ :p)"
            ),
            {"p": pattern, "new": new, "n": len(old) + 1},
        )

    _with_rows_writable(bind, schema, table, run)


def _respell_public_values(bind: Connection) -> None:
    def refs() -> None:
        bind.execute(
            text(
                "UPDATE public.identity_refs "
                "SET purpose = 'plugin', ref = left(ref, 1) || 'plu' || substr(ref, 5) "
                "WHERE purpose = 'app'"
            )
        )

    _with_rows_writable(bind, "public", "identity_refs", refs)

    def listings() -> None:
        bind.execute(
            text(
                "UPDATE public.marketplace_listings SET kind = 'plugin' WHERE kind = 'app'"
            )
        )

    _with_rows_writable(bind, "public", "marketplace_listings", listings)
    _respell_json(bind, "public", "marketplace_listing_versions", "definition")
    _respell_array(
        bind,
        "public",
        "plugin_service_registrations",
        "scope_ceiling",
        "^apps:",
        "apps:",
        "plugins:",
    )

    def notifications() -> None:
        rows = bind.execute(
            text(
                "SELECT id, type, data FROM public.notifications "
                "WHERE type IN ('app_consent_requested', 'app_update_pending')"
            )
        ).all()
        for row_id, kind, data in rows:
            data = dict(json.loads(data) if isinstance(data, str) else data or {})
            if "app_id" in data:
                data["plugin_id"] = data.pop("app_id")
            target = data.get("target_path")
            if isinstance(target, str):
                data["target_path"] = target.replace("?app=", "?plugin=")
            bind.execute(
                text(
                    "UPDATE public.notifications "
                    "SET type = :t, data = CAST(:d AS json) WHERE id = :id"
                ),
                {
                    "t": "plugin" + kind[len("app") :],
                    "d": json.dumps(data),
                    "id": row_id,
                },
            )

    _with_rows_writable(bind, "public", "notifications", notifications)


def _respell_guild_values(bind: Connection, schema: str) -> None:
    _respell_json(bind, schema, "guild_plugins", "definition")
    _respell_json(bind, schema, "dashboards", "definition")
    _respell_array(
        bind, schema, "guild_plugins", "granted_scopes", "^apps:", "apps:", "plugins:"
    )
    _respell_array(
        bind,
        schema,
        "webhook_subscriptions",
        "event_types",
        r"^apps\.",
        "apps.",
        "plugins.",
    )
    _respell_array(
        bind,
        schema,
        "webhook_subscriptions",
        "event_types",
        r"^app\.",
        "app.",
        "plugin.",
    )

    def outbox() -> None:
        bind.execute(
            text(
                f"UPDATE {_ident(schema)}.event_outbox SET resource_type = 'plugins' "
                "WHERE resource_type = 'apps'"
            )
        )

    _with_rows_writable(bind, schema, "event_outbox", outbox)


# --- entry points ------------------------------------------------------------


def upgrade() -> None:
    bind = op.get_bind()

    _rename_tables_and_columns(bind, "public", _PUBLIC_TABLES, _PUBLIC_COLUMNS)
    _rename_derived_names(bind, "public")
    _rename_policies(bind, "public")

    op.execute(_PLACE_FUNCTION)
    op.execute(_SECRET_FIELDS_FUNCTION)

    prefix = _guild_role_prefix()
    guild_roles: list[str] = []
    for schema in guild_schema_names(bind):
        _rename_tables_and_columns(bind, schema, _GUILD_TABLES, _GUILD_COLUMNS)
        _rename_derived_names(bind, schema)
        _rename_policies(bind, schema)
        _replace_guild_triggers(bind, schema)
        if schema != "guild_template":
            guild_id = schema.removeprefix("guild_")
            guild_role = f"{prefix}guild_{guild_id}_plugin"
            _converge_role(bind, f"{prefix}guild_{guild_id}_app", guild_role)
            guild_roles.append(guild_role)

    op.execute("DROP FUNCTION IF EXISTS public.fn_place_following_apps()")
    op.execute("DROP FUNCTION IF EXISTS public.fn_app_secret_fields()")

    _move_floor(bind, guild_roles)

    _respell_public_values(bind)
    for schema in guild_schema_names(bind):
        _respell_guild_values(bind, schema)


def downgrade() -> None:
    raise NotImplementedError(
        "Apps became plug-ins with nothing kept under the old names; restore a "
        "backup taken before 20261005_0457 to go back."
    )
