"""Drop the frozen public copies of guild-content tables.

Deployments that predate the v0.53.5 baseline squash (20260626_0125) still
carry copies of the 42 guild-content tables in ``public``, kept since the
squash as a data-integrity backstop while schema-per-guild soaked. They have
been inert throughout: nothing reads or writes them, guild-scoped migrations
skip them, the post-squash reconciler (20260702_0126) severed every dependency
that pointed at them, and fresh installs never create them at all. This drops
them — the last physical remnant of the pre-schema-per-guild layout.

No-op on fresh installs and on any deployment that already reached the
baseline without the copies.

Deliberately left standing:

* ``public.admin_api_keys_id_seq`` — despite the legacy name it is the LIVE
  sequence behind the shared ``public.user_api_keys``, so it is not in the
  drop set and nothing here owns it.
* The six guild-flavoured enums and the ``fn_*_set_guild_id`` trigger function
  bodies that live in ``public`` by design — guild schemas resolve them
  through ``search_path``. ``DROP TABLE`` reaches neither.

Sequences owned by the dropped tables (including the legacy-named
``teams_id_seq``, owned by ``public.initiatives``), their inert policies and
their triggers go with the tables.

``CASCADE`` is required because the copies reference each other, so a guard
runs first: any foreign key pointing INTO the drop set from a table outside it
aborts the migration instead of being silently cascaded away. The audit found
none on either fresh or legacy databases; if one exists, it wants a human.

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
    """Intentionally a no-op.

    The copies held no live data on either side of this revision — every
    release since v0.53.5 reads guild content only from ``guild_<id>`` schemas
    — so a rollback has nothing to restore and re-creating empty shells would
    only resurrect the thing this removed. Kept reversible (rather than
    raising) so the rest of the chain stays walkable for release rollbacks.
    """
