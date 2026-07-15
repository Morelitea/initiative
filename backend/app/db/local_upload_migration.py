"""One-time relocation of legacy flat local uploads into per-guild dirs.

Earlier local-filesystem builds stored every blob flat at ``UPLOADS_DIR/<file>``.
The storage backend now namespaces a guild's blobs under
``UPLOADS_DIR/guild_<id>/<file>`` (matching the S3 ``guild_<id>/`` layout), so a
pre-existing install's flat files must be moved once.

This runs at startup (see ``app.main`` lifespan), is **local-only**,
**idempotent**, and **self-disabling**: once the uploads root has no top-level
flat files it returns immediately without touching the database. Only file
locations change — the ``uploads`` rows and the ``/uploads/{guild_id}/{file}``
URLs are untouched.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from sqlalchemy import text

from app.core.config import settings
from app.db import session as db_session
from app.db.schema_provisioning import guild_role_name, guild_schema_name

logger = logging.getLogger(__name__)


def _legacy_flat_files(root: Path) -> list[Path]:
    """Regular files directly under the uploads root (the pre-prefix layout).

    Per-guild dirs (``guild_<id>/``) are subdirectories, so they're skipped — only
    loose files at the top level are legacy blobs awaiting relocation.
    """
    if not root.is_dir():
        return []
    return [p for p in root.iterdir() if p.is_file()]


def relocate_flat_uploads(
    root: Path, filename_to_guild: dict[str, int]
) -> tuple[int, int]:
    """Move legacy flat files into ``root/guild_<id>/``. Pure filesystem + a map.

    Returns ``(moved, unmatched)``. Idempotent: a destination that already exists
    means the file was migrated before, so the stray flat copy is dropped. A file
    whose name isn't in the map (no ``uploads`` row) is left in place and counted
    as unmatched, so nothing is silently destroyed.
    """
    moved = 0
    unmatched = 0
    for f in _legacy_flat_files(root):
        guild_id = filename_to_guild.get(f.name)
        if guild_id is None:
            unmatched += 1
            continue
        dest_dir = root / f"guild_{guild_id}"
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / f.name
        if dest.exists():
            f.unlink(missing_ok=True)  # already relocated; drop the duplicate
        else:
            shutil.move(str(f), str(dest))
        moved += 1
    return moved, unmatched


async def _build_filename_guild_map() -> dict[str, int]:
    """Map every guild's ``uploads.filename`` -> guild id (filenames are UUIDs,
    so they're globally unique and never collide across guilds)."""
    engine = db_session.admin_engine  # system engine; guild schemas via SET ROLE
    mapping: dict[str, int] = {}
    async with engine.connect() as conn:
        # Pooled connection: shed any guild role a previous checkout assumed.
        await conn.execute(text("SELECT set_config('role', 'none', false)"))
        guild_ids = (
            (await conn.execute(text("SELECT id FROM public.guilds ORDER BY id")))
            .scalars()
            .all()
        )
        for gid in guild_ids:
            schema = guild_schema_name(gid)
            # Existence check via pg_catalog (needs no schema USAGE —
            # to_regclass would raise: name resolution requires USAGE, and
            # the system login holds none until it assumes the guild role).
            exists = (
                await conn.execute(
                    text(
                        "SELECT 1 FROM pg_tables "
                        "WHERE schemaname = :s AND tablename = 'uploads'"
                    ),
                    {"s": schema},
                )
            ).scalar()
            if exists is None:  # schema missing/partial — skip
                continue
            # Assume the guild's own role for the schema read (the system
            # login holds no standing guild-schema access).
            await conn.execute(
                text("SELECT set_config('role', :r, false)"),
                {"r": guild_role_name(gid)},
            )
            rows = (
                (
                    await conn.execute(  # nosemgrep
                        # schema = guild_schema_name(int) — injection-safe.
                        text(f'SELECT filename FROM "{schema}".uploads')  # noqa: S608
                    )
                )
                .scalars()
                .all()
            )
            for filename in rows:
                if filename:
                    mapping[filename] = gid
    return mapping


async def migrate_local_uploads_to_guild_prefix() -> None:
    """Relocate any legacy flat uploads into their ``guild_<id>/`` subdir.

    No-op unless ``STORAGE_BACKEND=local`` and the uploads root still holds
    top-level flat files. Safe to run on every boot.
    """
    if (settings.STORAGE_BACKEND or "local").lower() != "local":
        return
    root = Path(settings.UPLOADS_DIR)
    if not _legacy_flat_files(root):
        return  # already migrated / nothing to relocate
    mapping = await _build_filename_guild_map()
    moved, unmatched = relocate_flat_uploads(root, mapping)
    if unmatched:
        logger.warning(
            "local upload migration: relocated %d file(s) into guild_<id>/ dirs; "
            "%d had no uploads row and were left in place",
            moved,
            unmatched,
        )
    else:
        logger.info(
            "local upload migration: relocated %d file(s) into guild_<id>/ dirs",
            moved,
        )
