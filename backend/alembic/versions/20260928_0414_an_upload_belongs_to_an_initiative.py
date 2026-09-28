"""an upload belongs to an initiative

``uploads.initiative_id`` names the initiative whose content shows a stored
file; ``claimed_at`` now says the file has been saved into something. A claimed
file with no initiative is shown by content that belongs to the whole guild.

Every existing upload is placed by the rows that show it — archived and
trashed rows included:

* shown in one initiative (or only by guild-level content): kept there, and
  claimed;
* shown in several: the initiative of the oldest showing row keeps it; every
  other initiative gets one copy of the file, and each of its rows that shows
  the file is rewritten to show the copy;
* shown by nothing: left unclaimed, which only its uploader reaches.

Nothing is deleted. A copy is named from the file and the initiative, so a run
repeated after a failure writes the same copies again. The columns the files
are read from are stated here in full, so this revision reads the same whatever
the modules say later. The downgrade drops the column; copies stay, and so do
the rewritten references.

Revision ID: 20260928_0414
Revises: 20260928_0413
Create Date: 2026-09-28
"""

import logging
import uuid
from pathlib import Path

import sqlalchemy as sa
from alembic import op

from app.db.guild_migrations import guild_schema_names, run_for_each_guild_schema

revision = "20260928_0414"
down_revision = "20260928_0413"
branch_labels = None
depends_on = None

logger = logging.getLogger("alembic.runtime.migration")


def _via(parent: str, fk: str) -> str:
    return f"(SELECT p.initiative_id FROM {parent} p WHERE p.id = r.{fk})"


_TASK = (
    "(SELECT p.initiative_id FROM tasks k JOIN projects p ON p.id = k.project_id"
    " WHERE k.id = r.task_id)"
)
_WIKI_PAGE = (
    "(SELECT w.initiative_id FROM wiki_pages k JOIN wikis w ON w.id = k.wiki_id"
    " WHERE k.id = r.wiki_page_id)"
)
_COMMENT = (
    "COALESCE("
    + ", ".join(
        [
            _TASK,
            _WIKI_PAGE,
            _via("projects", "project_id"),
            _via("documents", "document_id"),
            _via("queues", "queue_id"),
            _via("counter_groups", "counter_group_id"),
            _via("calendars", "calendar_id"),
            _via("dashboards", "dashboard_id"),
            _via("posts", "post_id"),
            _via("galleries", "gallery_id"),
            _via("wikis", "wiki_id"),
        ]
    )
    + ")"
)
_GALLERY_IMAGE = (
    "(SELECT g.initiative_id FROM gallery_images k JOIN galleries g"
    " ON g.id = k.gallery_id WHERE k.id = r.gallery_image_id)"
)

#: Every column a stored file is shown from: table, column, whether it holds
#: json, and the initiative of a row of the table (``r``).
_SHOWN: tuple[tuple[str, str, bool, str], ...] = (
    ("projects", "description", False, "r.initiative_id"),
    ("documents", "content", True, "r.initiative_id"),
    ("documents", "original_filename", False, "r.initiative_id"),
    ("documents", "featured_image_url", False, "r.initiative_id"),
    ("documents", "file_url", False, "r.initiative_id"),
    ("queues", "description", False, "r.initiative_id"),
    ("counter_groups", "description", False, "r.initiative_id"),
    ("calendars", "description", False, "r.initiative_id"),
    ("dashboards", "description", False, "r.initiative_id"),
    ("posts", "body", True, "r.initiative_id"),
    ("galleries", "description", False, "r.initiative_id"),
    ("wikis", "description", False, "r.initiative_id"),
    ("tasks", "description", False, _via("projects", "project_id")),
    ("tasks", "checklist", True, _via("projects", "project_id")),
    ("queue_items", "notes", False, _via("queues", "queue_id")),
    ("calendar_events", "description", False, _via("calendars", "calendar_id")),
    ("calendar_events", "location", False, _via("calendars", "calendar_id")),
    ("gallery_images", "caption", False, _via("galleries", "gallery_id")),
    ("gallery_images", "original_filename", False, _via("galleries", "gallery_id")),
    ("gallery_images", "file_url", False, _via("galleries", "gallery_id")),
    ("gallery_images", "thumbnail_url", False, _via("galleries", "gallery_id")),
    ("wiki_pages", "content", True, _via("wikis", "wiki_id")),
    ("comments", "content", False, _COMMENT),
    ("document_file_versions", "file_url", False, _via("documents", "document_id")),
    ("gallery_image_versions", "file_url", False, _GALLERY_IMAGE),
    ("gallery_image_versions", "thumbnail_url", False, _GALLERY_IMAGE),
)

#: Tables whose editor keeps a state of its own beside the column; a rewrite
#: clears it so the editor starts again from the column.
_EDITOR_STATE = frozenset({"documents", "wiki_pages"})

#: Every guild table the backfill reads or writes.
_TABLES = sorted(
    {table for table, *_ in _SHOWN}
    | {
        "uploads",
        "projects",
        "queues",
        "calendars",
        "galleries",
        "wikis",
        "counter_groups",
        "dashboards",
        "posts",
        "documents",
        "tasks",
        "wiki_pages",
        "gallery_images",
    }
)

_JSON = {(table, column) for table, column, is_json, _ in _SHOWN if is_json}


def _copy_name(guild_id: int, filename: str, initiative_id: int | None) -> str:
    """The copy of ``filename`` kept for ``initiative_id``: the same name every
    run, keeping the original's prefix and extension."""
    path = Path(filename)
    prefix = "pasted-" if filename.startswith("pasted-") else ""
    key = uuid.uuid5(uuid.NAMESPACE_URL, f"{guild_id}/{filename}/{initiative_id}")
    return f"{prefix}{key.hex}{path.suffix}"


def _place(bind, schema: str) -> None:
    """Place ``schema``'s uploads by the rows that show them."""
    from app.services.storage import get_guild_storage

    guild_id = int(schema.removeprefix("guild_"))
    bind.execute(
        sa.text("SELECT set_config('search_path', :sp, true)"),
        {"sp": f"{schema}, public"},
    )
    bind.execute(
        sa.text(
            "CREATE TEMP TABLE IF NOT EXISTS _shown (filename text, tbl text,"
            " col text, row_id int, initiative_id int, created_at timestamptz)"
            " ON COMMIT DROP"
        )
    )
    bind.execute(sa.text("TRUNCATE _shown"))
    pattern = f"/uploads/{guild_id}/([\\w.-]+)"
    for table, column, _json, initiative in _SHOWN:
        bind.execute(
            sa.text(
                "INSERT INTO _shown (filename, tbl, col, row_id, initiative_id, created_at)"  # noqa: S608
                f" SELECT m[1], '{table}', '{column}', r.id, {initiative}, r.created_at"
                f" FROM {table} r, regexp_matches(r.{column}::text, :pattern, 'g') m"
            ),
            {"pattern": pattern},
        )
    rows = bind.execute(
        sa.text(
            "SELECT DISTINCT s.filename, s.initiative_id, s.tbl, s.col, s.row_id,"
            " s.created_at FROM _shown s JOIN uploads u ON u.filename = s.filename"
            " ORDER BY s.filename, s.created_at, s.tbl, s.row_id"
        )
    ).all()

    # filename -> initiative -> the (table, column, row) showing it there, the
    # initiatives in the order their first row was written.
    shown: dict[str, dict[int | None, list[tuple[str, str, int]]]] = {}
    for filename, initiative_id, table, column, row_id, _created in rows:
        shown.setdefault(filename, {}).setdefault(initiative_id, []).append(
            (table, column, row_id)
        )

    storage = get_guild_storage(guild_id)
    claimed = copied = failed = 0
    for filename, by_initiative in shown.items():
        keeper, *others = by_initiative
        bind.execute(
            sa.text(
                "UPDATE uploads SET initiative_id = :i,"
                " claimed_at = COALESCE(claimed_at, now()) WHERE filename = :f"
            ),
            {"i": keeper, "f": filename},
        )
        claimed += 1
        for initiative_id in others:
            copy = _copy_name(guild_id, filename, initiative_id)
            if not storage.copy(filename, copy):
                logger.warning(
                    "uploads in %s: could not copy %s; its rows keep the original",
                    schema,
                    filename,
                )
                failed += 1
                continue
            bind.execute(
                sa.text(
                    "INSERT INTO uploads (filename, created_by, size_bytes,"
                    " content_type, content_hash, created_at, claimed_at,"
                    " initiative_id) SELECT :copy, created_by, size_bytes,"
                    " content_type, content_hash, created_at, now(), :i"
                    " FROM uploads WHERE filename = :f"
                    " ON CONFLICT (filename) DO NOTHING"
                ),
                {"copy": copy, "i": initiative_id, "f": filename},
            )
            old = f"/uploads/{guild_id}/{filename}"
            new = f"/uploads/{guild_id}/{copy}"
            for table, column, row_id in by_initiative[initiative_id]:
                value = (
                    f"replace({column}::text, :old, :new)::jsonb"
                    if (table, column) in _JSON
                    else f"replace({column}, :old, :new)"
                )
                state = ", yjs_state = NULL" if table in _EDITOR_STATE else ""
                bind.execute(
                    sa.text(
                        f"UPDATE {table} SET {column} = {value}{state}"  # noqa: S608
                        " WHERE id = :id"
                    ),
                    {"old": old, "new": new, "id": row_id},
                )
            copied += 1

    # A file nothing shows has not been saved into anything.
    unshown = bind.execute(
        sa.text(
            "UPDATE uploads SET claimed_at = NULL WHERE initiative_id IS NULL"
            " AND claimed_at IS NOT NULL"
            " AND NOT EXISTS (SELECT 1 FROM _shown s WHERE s.filename = uploads.filename)"
        )
    ).rowcount
    logger.info(
        "uploads in %s: %s placed, %s copies, %s copy failures, %s unclaimed",
        schema,
        claimed,
        copied,
        failed,
        unshown,
    )


def _add_columns() -> None:
    op.add_column(
        "uploads",
        sa.Column(
            "initiative_id",
            sa.Integer(),
            sa.ForeignKey("initiatives.id"),
            nullable=True,
        ),
    )
    op.create_index("ix_uploads_initiative_id", "uploads", ["initiative_id"])
    op.create_check_constraint(
        "ck_uploads_initiative_claimed",
        "uploads",
        "initiative_id IS NULL OR claimed_at IS NOT NULL",
    )


def upgrade() -> None:
    bind = op.get_bind()
    run_for_each_guild_schema(bind, _add_columns)
    for schema in guild_schema_names(bind):
        if not schema.removeprefix("guild_").isdigit():
            continue
        # A migration carries no request context, so the owner's policies are
        # lifted while it reads and writes, and the tables' request triggers
        # (the freeze, change capture, search) are held while rows change.
        for table in _TABLES:
            op.execute(f"ALTER TABLE {schema}.{table} NO FORCE ROW LEVEL SECURITY")
            op.execute(f"ALTER TABLE {schema}.{table} DISABLE TRIGGER USER")
        try:
            _place(bind, schema)
        finally:
            for table in _TABLES:
                op.execute(f"ALTER TABLE {schema}.{table} ENABLE TRIGGER USER")
                op.execute(f"ALTER TABLE {schema}.{table} FORCE ROW LEVEL SECURITY")
    bind.execute(sa.text("SELECT set_config('search_path', 'public', true)"))


def _drop_columns() -> None:
    op.drop_constraint("ck_uploads_initiative_claimed", "uploads", type_="check")
    op.drop_index("ix_uploads_initiative_id", table_name="uploads")
    op.drop_column("uploads", "initiative_id")


def downgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _drop_columns)
