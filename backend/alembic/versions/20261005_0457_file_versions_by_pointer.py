"""File versions by pointer

A file document and a gallery picture each keep their uploads as numbered
versions. The parent row used to carry a copy of the newest version's file
columns as well; it now names that version instead:

* ``documents.current_version_id`` → ``document_file_versions.id``, and
* ``gallery_images.current_version_id`` → ``gallery_image_versions.id``,

both nullable (a document that is not a file has none) and indexed, with no
delete rule: a version the parent shows cannot be deleted until the parent
points elsewhere, and deleting the parent takes its versions with it.

The upgrade points every parent at its highest-numbered version. A parent
that carries a file but no version row (an import wrote some that way) first
gets one, numbered 1, made from the columns it carried. Then the copied
columns go: ``file_url``, ``file_content_type``, ``file_size`` and
``original_filename`` from both, and ``thumbnail_url``, ``width`` and
``height`` from ``gallery_images``.

Every version's ``file_content_type`` becomes NOT NULL: the type decides how
the file is shown, and it is always one its tool accepts. A version with no
type, or one its tool does not show, takes the type its original filename's
extension names, or failing that its stored name's, from the mapping as it
stands at this revision. One that no name types, or whose type is still not
one its tool shows, takes its tool's fallback (``text/plain`` for a document,
``image/png`` for a picture), so the upgrade always completes and every
version can be copied; the file still downloads under its own name.

The search triggers on both tables name the columns that go, so they are
dropped first; the search generation comment is cleared so the next boot
rebuilds them from the registry and re-sweeps the entries.

The downgrade puts the columns back, filled from the version each parent
points at, makes the version type nullable again and drops the pointers.
Version rows the upgrade made, and the types it gave, stay.

Guild-scoped: applied to ``guild_template`` and every ``guild_<id>``.

Revision ID: 20261005_0457
Revises: 20261005_0456
Create Date: 2026-10-05
"""

revision = "20261005_0457"
down_revision = "20261005_0456"
branch_labels = None
depends_on = None

from alembic import op  # noqa: E402
import sqlalchemy as sa  # noqa: E402
from app.db.guild_migrations import run_for_each_guild_schema  # noqa: E402

#: parent table -> its version table, and the parent's column there.
_VERSIONED = {
    "documents": ("document_file_versions", "document_id"),
    "gallery_images": ("gallery_image_versions", "gallery_image_id"),
}

#: The file columns each parent carried, all on its version table too.
_COPIED = {
    "documents": ("file_url", "file_content_type", "file_size", "original_filename"),
    "gallery_images": (
        "file_url",
        "thumbnail_url",
        "file_content_type",
        "file_size",
        "original_filename",
        "width",
        "height",
    ),
}

#: The search triggers on each parent, which name its indexed columns.
_SEARCH_TRIGGERS = {
    "documents": ("search_document_ins", "search_document_upd"),
    "gallery_images": ("search_gallery_image_ins", "search_gallery_image_upd"),
}

#: Asks the next boot to rebuild this guild's search triggers and re-sweep its
#: entries through the registry.
_CLEAR_SEARCH_GENERATION = "COMMENT ON TABLE search_entries IS NULL"

_TABLES = (*_VERSIONED, *(versions for versions, _ in _VERSIONED.values()))


def _first_versions(parent: str) -> str:
    """Version 1 for each parent that carries a file but has no version."""
    versions, fk = _VERSIONED[parent]
    columns = ", ".join(_COPIED[parent])
    carried = ", ".join(f"p.{column}" for column in _COPIED[parent])
    return (
        f"INSERT INTO {versions} ({fk}, version_number, {columns},"  # noqa: S608
        " created_by, created_at)"
        f" SELECT p.id, 1, {carried}, p.created_by, p.created_at FROM {parent} p"
        " WHERE p.file_url IS NOT NULL"
        f" AND NOT EXISTS (SELECT 1 FROM {versions} v WHERE v.{fk} = p.id)"
    )


def _point(parent: str) -> str:
    """Point each parent at its highest-numbered version."""
    versions, fk = _VERSIONED[parent]
    return (
        f"UPDATE {parent} AS p SET current_version_id = v.id"  # noqa: S608
        f" FROM (SELECT DISTINCT ON ({fk}) id, {fk} FROM {versions}"
        f" ORDER BY {fk}, version_number DESC) AS v"
        f" WHERE v.{fk} = p.id"
    )


def _copy_back(parent: str) -> str:
    """Fill a parent's file columns from the version it points at."""
    versions, _ = _VERSIONED[parent]
    columns = ", ".join(f"{column} = v.{column}" for column in _COPIED[parent])
    return (
        f"UPDATE {parent} AS p SET {columns} FROM {versions} AS v"  # noqa: S608
        " WHERE v.id = p.current_version_id"
    )


#: Extension -> type, as ``attachments.EXTENSION_TO_MIME`` stood at this
#: revision. Its types are exactly the ones a file document may hold.
_DOCUMENT_TYPES = {
    ".pdf": "application/pdf",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xls": "application/vnd.ms-excel",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".ppt": "application/vnd.ms-powerpoint",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".txt": "text/plain",
    ".html": "text/html",
    ".htm": "text/html",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
    ".md": "text/markdown",
    ".markdown": "text/markdown",
}

#: Extension -> type for the pictures a gallery shows, as
#: ``galleries.PICTURE_EXTENSIONS`` stood at this revision.
_PICTURE_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}

#: version table -> the types its files may be, by extension.
_TYPES = {
    "document_file_versions": _DOCUMENT_TYPES,
    "gallery_image_versions": _PICTURE_TYPES,
}

#: version table -> the type a file no name types is given.
_FALLBACK_TYPE = {
    "document_file_versions": "text/plain",
    "gallery_image_versions": "image/png",
}


def _allowed(versions: str) -> str:
    """The types a version table's files may be, as a SQL list."""
    return ", ".join(f"'{mime}'" for mime in sorted(set(_TYPES[versions].values())))


def _typed_by_extension(versions: str, column: str) -> str:
    """Give each version whose type is missing, or not one its tool shows,
    the type its ``column`` (a filename or a stored name) ends in, where that
    extension names one."""
    types = _TYPES[versions]
    pairs = ", ".join(f"('{ext}', '{mime}')" for ext, mime in types.items())
    allowed = _allowed(versions)
    return (
        f"UPDATE {versions} AS v SET file_content_type = t.mime"  # noqa: S608
        f" FROM (VALUES {pairs}) AS t(ext, mime)"
        " WHERE (v.file_content_type IS NULL"
        f" OR v.file_content_type NOT IN ({allowed}))"
        f" AND t.ext = lower(substring(v.{column} from '\\.[^./]*$'))"
    )


#: Parents that carried a file and point at no version once the backfill ran.
_UNPOINTED = (
    "SELECT (SELECT count(*) FROM documents"
    " WHERE file_url IS NOT NULL AND current_version_id IS NULL)"
    " + (SELECT count(*) FROM gallery_images WHERE current_version_id IS NULL)"
)


def _write(*statements: str, checks: tuple[tuple[str, str], ...] = ()) -> None:
    """Run DML on tables with FORCE row security and request triggers (the
    lifecycle freeze, change capture), lifting both for the writes and
    restoring them either way. Each of ``checks`` is a count of rows the
    writes left wrong, and what they are."""
    for table in _TABLES:
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE TRIGGER USER")
    try:
        for statement in statements:
            op.execute(statement)
        for check, what in checks:
            wrong = op.get_bind().execute(sa.text(check)).scalar()
            if wrong:
                raise RuntimeError(f"{wrong} {what}")
    finally:
        for table in _TABLES:
            op.execute(f"ALTER TABLE {table} ENABLE TRIGGER USER")
            op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")


def _drop_search_triggers() -> None:
    for parent, triggers in _SEARCH_TRIGGERS.items():
        for trigger in triggers:
            op.execute(f"DROP TRIGGER IF EXISTS {trigger} ON {parent}")


def upgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_upgrade)


def _apply_upgrade() -> None:
    _drop_search_triggers()
    for parent, (versions, _) in _VERSIONED.items():
        op.add_column(
            parent,
            sa.Column(
                "current_version_id",
                sa.Integer(),
                sa.ForeignKey(
                    f"{versions}.id", name=f"{parent}_current_version_id_fkey"
                ),
                nullable=True,
            ),
        )
        op.create_index(
            f"ix_{parent}_current_version_id",
            parent,
            ["current_version_id"],
            unique=False,
        )
    _write(
        *(_first_versions(parent) for parent in _VERSIONED),
        *(
            _typed_by_extension(versions, column)
            for versions in _TYPES
            for column in ("original_filename", "file_url")
        ),
        *(
            f"UPDATE {versions} SET file_content_type = '{fallback}'"  # noqa: S608
            " WHERE file_content_type IS NULL"
            f" OR file_content_type NOT IN ({_allowed(versions)})"
            for versions, fallback in _FALLBACK_TYPE.items()
        ),
        *(_point(parent) for parent in _VERSIONED),
        checks=((_UNPOINTED, "files point at no version"),),
    )
    for versions in _TYPES:
        op.alter_column(versions, "file_content_type", nullable=False)
    for parent, columns in _COPIED.items():
        for column in columns:
            op.drop_column(parent, column)
    op.execute(_CLEAR_SEARCH_GENERATION)


def downgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_downgrade)


def _file_columns() -> list[sa.Column]:
    return [
        sa.Column("file_url", sa.String(length=512), nullable=True),
        sa.Column("file_content_type", sa.String(length=128), nullable=True),
        sa.Column("file_size", sa.BigInteger(), nullable=True),
        sa.Column("original_filename", sa.String(length=255), nullable=True),
    ]


def _apply_downgrade() -> None:
    # Once a boot has rebuilt them, the search triggers name
    # ``current_version_id``, and a column a trigger names cannot be dropped.
    _drop_search_triggers()
    for column in _file_columns():
        op.add_column("documents", column)
    for column in (
        *_file_columns(),
        sa.Column("thumbnail_url", sa.String(length=512), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
    ):
        op.add_column("gallery_images", column)
    _write(*(_copy_back(parent) for parent in _VERSIONED))
    op.alter_column("gallery_images", "file_url", nullable=False)
    for versions in _TYPES:
        op.alter_column(versions, "file_content_type", nullable=True)
    for parent in _VERSIONED:
        op.drop_index(f"ix_{parent}_current_version_id", table_name=parent)
        op.drop_column(parent, "current_version_id")
    op.execute(_CLEAR_SEARCH_GENERATION)
