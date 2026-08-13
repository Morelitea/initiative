"""Retire the last pre-schema-per-guild names in ``public``.

Two leftovers from the same era, in the order that keeps them from being
confused with each other.

**1. Finish the ``admin_api_keys`` -> ``user_api_keys`` rename.** The table was
renamed long ago but its constraints, indexes and id sequence kept the old
name, and the baseline snapshot froze that half-done state — so *every*
install, fresh ones included, still carries `admin_api_keys_pkey`,
`admin_api_keys_id_seq` and friends on a table called ``user_api_keys``. That
mismatch is what made ``admin_api_keys_id_seq`` read like something the drop
below should take. Renaming first removes the trap rather than documenting
around it. Grants and column defaults track the object, not its name, so
nothing else moves (Postgres also renames a constraint's backing index with
the constraint).

**2. Drop the frozen public copies of guild-content tables.** Deployments that
predate the v0.53.5 baseline squash (20260626_0125) still carry copies of the
42 guild-content tables in ``public``, kept since the squash as a
data-integrity backstop while schema-per-guild soaked. They have been inert
throughout: nothing reads or writes them, guild-scoped migrations skip them,
the post-squash reconciler (20260702_0126) severed every dependency that
pointed at them, and fresh installs never create them at all.

Sequences owned by the dropped tables (including the legacy-named
``teams_id_seq``, owned by ``public.initiatives``), their inert policies and
their triggers go with the tables. The six guild-flavoured enums and the
``fn_*_set_guild_id`` trigger function bodies that live in ``public`` by design
stay — guild schemas resolve them through ``search_path``, and ``DROP TABLE``
reaches neither.

``CASCADE`` is required because the copies reference each other, so a guard
runs first: any foreign key pointing INTO the drop set from a table outside it
aborts the migration instead of being silently cascaded away. The audit found
none on either fresh or legacy databases; if one exists, it wants a human.

Every step is conditional on what the database actually has, so the drop half
is a no-op on installs that never had the copies.

**One-way door.** ``downgrade()`` raises: dropped rows can't come back, and a
downgrade that silently stamped 20260811_0162 over a database still missing
those tables would leave the revision and the physical schema disagreeing —
worse than refusing. Roll forward only.

Revision ID: 20260811_0163
Revises: 20260811_0162
Create Date: 2026-08-11
"""

from alembic import op
from sqlalchemy import text

revision = "20260811_0163"
down_revision = "20260811_0162"
branch_labels = None
depends_on = None


# --- 1. finish the admin_api_keys -> user_api_keys rename -------------------

_API_KEY_TABLE = "user_api_keys"

# (kind, old name, new name). Renaming a constraint renames its backing index
# too, so ``admin_api_keys_pkey`` / ``_token_hash_key`` appear once each.
_API_KEY_RENAMES: tuple[tuple[str, str, str], ...] = (
    ("constraint", "admin_api_keys_pkey", "user_api_keys_pkey"),
    ("constraint", "admin_api_keys_token_hash_key", "user_api_keys_token_hash_key"),
    ("constraint", "admin_api_keys_user_id_fkey", "user_api_keys_user_id_fkey"),
    ("index", "ix_admin_api_keys_token_prefix", "ix_user_api_keys_token_prefix"),
    ("index", "ix_admin_api_keys_user_id", "ix_user_api_keys_user_id"),
    ("sequence", "admin_api_keys_id_seq", "user_api_keys_id_seq"),
)


def _exists(conn, kind: str, name: str) -> bool:
    """Is there a ``kind`` named ``name`` in ``public``? Constraints live in
    ``pg_constraint``; everything else is a relation."""
    if kind == "constraint":
        return bool(
            conn.execute(
                text(
                    "SELECT 1 FROM pg_constraint "
                    "WHERE conname = :n AND conrelid = to_regclass(:t)"
                ),
                {"n": name, "t": f"public.{_API_KEY_TABLE}"},
            ).scalar()
        )
    return (
        conn.execute(text("SELECT to_regclass(:n)"), {"n": f"public.{name}"}).scalar()
        is not None
    )


def _rename_sql(kind: str, old: str, new: str) -> str:
    """Names are literals from ``_API_KEY_RENAMES``, never input."""
    if kind == "constraint":
        return (
            f'ALTER TABLE public."{_API_KEY_TABLE}" '
            f'RENAME CONSTRAINT "{old}" TO "{new}"'
        )
    if kind == "index":
        return f'ALTER INDEX public."{old}" RENAME TO "{new}"'
    return f'ALTER SEQUENCE public."{old}" RENAME TO "{new}"'


def _rename_api_key_objects(conn) -> None:
    """Rename whichever objects still carry the pre-rename table name.

    Each is skipped unless the old name exists and the new one doesn't, so a
    database at either end — or part-way between, which is what the half-done
    rename left behind — comes out the same.
    """
    if not _exists(conn, "table", _API_KEY_TABLE):
        return  # table absent — nothing this step owns
    for kind, old, new in _API_KEY_RENAMES:
        if not _exists(conn, kind, old) or _exists(conn, kind, new):
            continue
        conn.execute(text(_rename_sql(kind, old, new)))
        print(f"  renamed {kind} {old} -> {new}")


# --- 2. drop the frozen public copies ---------------------------------------

# The guild-content tables that existed in ``public`` at squash time (v0.53.5).
# Frozen, like the identical list in 20260702_0126: this is the LEGACY
# snapshot, not a live registry — tables added after the squash never got a
# public copy, so they must never appear here.
_LEGACY_PUBLIC_GUILD_TABLES = (
    "calendar_event_attendees",
    "calendar_event_documents",
    "calendar_event_property_values",
    "calendar_event_tags",
    "calendar_events",
    "comments",
    "counter_groups",
    "counters",
    "document_file_versions",
    "document_links",
    "document_property_values",
    "document_tags",
    "documents",
    "event_reminder_dispatches",
    "guild_settings",
    "initiative_members",
    "initiative_role_permissions",
    "initiative_roles",
    "initiatives",
    "project_documents",
    "project_favorites",
    "project_orders",
    "project_tags",
    "projects",
    "property_definitions",
    "queue_item_documents",
    "queue_item_tags",
    "queue_item_tasks",
    "queue_items",
    "queues",
    "recent_views",
    "resource_grants",
    "subtasks",
    "tags",
    "task_assignees",
    "task_assignment_digest_items",
    "task_property_values",
    "task_statuses",
    "task_tags",
    "tasks",
    "uploads",
    "webhook_subscriptions",
)


def _existing_copies(conn) -> list[str]:
    """The subset of the frozen list that this database actually has in
    ``public``. Empty on fresh installs."""
    rows = conn.execute(
        text(
            "SELECT c.relname FROM pg_class c "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'public' AND c.relkind = 'r' "
            "AND c.relname = ANY(:t) ORDER BY c.relname"
        ),
        {"t": list(_LEGACY_PUBLIC_GUILD_TABLES)},
    )
    return [row[0] for row in rows]


def _assert_no_outside_references(conn, copies: list[str]) -> None:
    """Abort if any table OUTSIDE the drop set has a foreign key into it.

    The copies reference each other, so they can only go as a CASCADE group —
    and a CASCADE would drop such a constraint on a live table without a word.
    20260702_0126 already dropped the guild-schema FKs into these tables, and
    no shared table has ever pointed at one.
    """
    rows = conn.execute(
        text(
            """
            SELECT sn.nspname, sc.relname, con.conname, tc.relname
            FROM pg_constraint con
            JOIN pg_class sc ON sc.oid = con.conrelid
            JOIN pg_namespace sn ON sn.oid = sc.relnamespace
            JOIN pg_class tc ON tc.oid = con.confrelid
            JOIN pg_namespace tn ON tn.oid = tc.relnamespace AND tn.nspname = 'public'
            WHERE con.contype = 'f'
              AND tc.relname = ANY(:copies)
              AND NOT (sn.nspname = 'public' AND sc.relname = ANY(:copies))
            """
        ),
        {"copies": copies},
    ).fetchall()
    if rows:
        detail = ", ".join(
            f"{schema}.{table}.{constraint} -> public.{target}"
            for schema, table, constraint, target in rows
        )
        raise RuntimeError(
            "Refusing to drop the frozen public copies of guild-content tables: "
            f"a live table still references them ({detail}). Dropping would "
            "cascade that constraint away. Re-point or drop the foreign key, "
            "then re-run the upgrade."
        )


def upgrade() -> None:
    conn = op.get_bind()
    # Rename first: afterwards no legacy-named object survives near the drop
    # set to be mistaken for part of it.
    _rename_api_key_objects(conn)

    copies = _existing_copies(conn)
    if not copies:
        return  # fresh install (or already dropped) — nothing to remove
    _assert_no_outside_references(conn, copies)
    # Names come from pg_class intersected with the frozen allow-list above.
    targets = ", ".join(f'public."{table}"' for table in copies)
    conn.execute(text(f"DROP TABLE IF EXISTS {targets} CASCADE"))
    print(
        f"  dropped {len(copies)} frozen public copies of guild-content tables "
        "(pre-v0.53.5 backstop)"
    )


def downgrade() -> None:
    raise NotImplementedError(
        "20260811_0163 drops the frozen public copies of guild-content tables; "
        "the rows are gone and cannot be restored from the database. Stamping "
        "20260811_0162 back over a schema that no longer has those tables "
        "would put the revision and the physical schema out of step. Restore "
        "from a backup taken before the upgrade instead."
    )
