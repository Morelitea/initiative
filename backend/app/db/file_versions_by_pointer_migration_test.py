"""Migration 20261005_0457 points file documents and pictures at the version
they show. Loaded by path and run on a guild the test builds, the way
``upload_initiative_backfill_test`` runs its revision: down to the old shape,
rows written as an older release wrote them, and up again."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text

from app.models.tenant.document import DocumentType
from app.testing import (
    create_document,
    create_gallery,
    create_gallery_image,
    create_guild,
    create_initiative,
    create_user,
)

_MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "20261005_0457_file_versions_by_pointer.py"
)


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(_MIGRATION.stem, _MIGRATION)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def test_old_files_get_versions_types_and_pointers(
    session, tmp_path, monkeypatch
) -> None:
    """A file with versions points at its newest. A file an import wrote with
    no version gets version 1, typed by its name, or by its tool's fallback
    when no name types it. The downgrade puts the copied columns back."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "UPLOADS_DIR", str(tmp_path / "uploads"))
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    schema = f"guild_{guild.id}"
    initiative = await create_initiative(session, guild, user)
    versioned = await create_document(
        session,
        initiative,
        user,
        document_type=DocumentType.file,
        file_url="/uploads/1/brief.pdf",
        original_filename="brief.pdf",
    )
    named = await create_document(session, initiative, user)
    nameless = await create_document(session, initiative, user)
    picture = await create_gallery_image(
        session, await create_gallery(session, initiative, user), user
    )
    migration = _load()

    def run(step):
        def apply(sync_session) -> None:
            bind = sync_session.connection()
            bind.execute(
                text("SELECT set_config('search_path', :sp, true)"),
                {"sp": f"{schema}, public"},
            )
            with Operations.context(MigrationContext.configure(bind)):
                step()

        return apply

    await session.run_sync(run(migration._apply_downgrade))
    # Written as an import used to write them: a file and no version.
    for document, url, filename in (
        (named, "/uploads/1/k1", "notes.md"),
        (nameless, "/uploads/1/k2", "README"),
    ):
        await (await session.connection()).execute(
            text(
                f"UPDATE {schema}.documents SET document_type = 'file',"
                " file_url = :url, original_filename = :name WHERE id = :id"
            ),
            {"url": url, "name": filename, "id": document.id},
        )
    copied = (
        await (await session.connection()).execute(
            text(f"SELECT file_url FROM {schema}.documents WHERE id = :id"),
            {"id": versioned.id},
        )
    ).scalar()
    assert copied == "/uploads/1/brief.pdf"

    await session.run_sync(run(migration._apply_upgrade))
    rows = (
        await (await session.connection()).execute(
            text(
                f"SELECT d.id, v.version_number, v.file_content_type"
                f" FROM {schema}.documents d"
                f" JOIN {schema}.document_file_versions v ON v.id = d.current_version_id"
            )
        )
    ).all()
    assert {row.id: (row.version_number, row.file_content_type) for row in rows} == {
        versioned.id: (1, "application/pdf"),
        named.id: (1, "text/markdown"),
        nameless.id: (1, "text/plain"),
    }
    shown = (
        await (await session.connection()).execute(
            text(
                f"SELECT v.file_content_type FROM {schema}.gallery_images i"
                f" JOIN {schema}.gallery_image_versions v ON v.id = i.current_version_id"
                " WHERE i.id = :id"
            ),
            {"id": picture.id},
        )
    ).scalar()
    assert shown == "image/png"
    leftover = (
        await (await session.connection()).execute(
            text(
                "SELECT count(*) FROM information_schema.columns"
                " WHERE table_schema = :schema"
                " AND table_name IN ('documents', 'gallery_images')"
                " AND column_name IN ('file_url', 'file_content_type')"
            ),
            {"schema": schema},
        )
    ).scalar()
    assert leftover == 0
