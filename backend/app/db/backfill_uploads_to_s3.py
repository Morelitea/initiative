"""Backfill: copy existing local uploads into the configured S3 bucket.

The final step of the local→S3 migration (see
``history/blob-storage-tenancy-design.md`` §11). Run it with the ``S3_*`` settings
pointed at your object store **while the app is still on
``STORAGE_BACKEND=local``**: it copies every blob under
``UPLOADS_DIR/guild_<id>/`` to the S3 key ``guild_<id>/<file>``, setting the
content-type recorded on the ``uploads`` row (falling back to a guess from the
extension). It's **idempotent** — an object already present in S3 is skipped — so
it is safe to re-run and resume.

After it reports 0 failures, cut over: set ``STORAGE_BACKEND=s3`` (with
``S3_LOCAL_FALLBACK=true`` for a verification window, then turn it off).

    python -m app.db.backfill_uploads_to_s3 [--dry-run]
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import logging
import mimetypes
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.config import settings
from app.db import session as db_session
from app.db.schema_provisioning import guild_schema_name
from app.services.storage import StorageBackend, s3_guild_storage

logger = logging.getLogger(__name__)


@dataclass
class BackfillSummary:
    """Outcome of a backfill run, for the final log line / exit code."""

    copied: int = 0
    skipped: int = 0
    failed: int = 0
    hash_mismatches: int = 0
    failed_keys: list[str] = field(default_factory=list)


def backfill_guild_dir(
    guild_dir: Path,
    meta: dict[str, tuple[str | None, str | None]],
    dest: StorageBackend,
    summary: BackfillSummary,
    *,
    guild_id: int,
    dry_run: bool,
) -> None:
    """Copy one guild's local blobs into ``dest`` (S3). Pure of the DB.

    ``meta`` maps filename -> (content_type, content_hash) from the ``uploads``
    rows. Updates ``summary`` in place. Idempotent: an object already in ``dest``
    is skipped; a content_hash mismatch is treated as a failure (the blob is NOT
    copied) so corruption isn't propagated. ``dry_run`` skips only the write — the
    ``exists`` check still runs against ``dest``, so a dry run reports the real
    remaining work rather than re-counting already-copied files.
    """
    for path in sorted(guild_dir.iterdir()):
        if not path.is_file():
            continue
        key = path.name
        content_type, content_hash = meta.get(key, (None, None))
        if content_type is None:
            content_type = mimetypes.guess_type(key)[0]
        label = f"guild_{guild_id}/{key}"
        try:
            if dest.exists(key):
                summary.skipped += 1
                continue
            data = path.read_bytes()
            if content_hash and hashlib.sha256(data).hexdigest() != content_hash:
                logger.warning("content_hash mismatch for %s — not copying", label)
                summary.hash_mismatches += 1
                summary.failed += 1
                summary.failed_keys.append(label)
                continue
            if dry_run:
                logger.info(
                    "[dry-run] would copy %s (%d bytes, %s)",
                    label,
                    len(data),
                    content_type,
                )
                summary.copied += 1
                continue
            dest.write(key, data, content_type=content_type)
            summary.copied += 1
        except Exception:  # noqa: BLE001 — one bad blob must not abort the run
            logger.exception("failed to back up %s", label)
            summary.failed += 1
            summary.failed_keys.append(label)


async def _guild_upload_meta(
    conn: AsyncConnection, schema: str
) -> dict[str, tuple[str | None, str | None]]:
    """filename -> (content_type, content_hash) for a guild's uploads, or {} if
    the schema/table is absent."""
    exists = (
        await conn.execute(text("SELECT to_regclass(:t)"), {"t": f"{schema}.uploads"})
    ).scalar()
    if exists is None:
        return {}
    rows = (
        await conn.execute(
            text(f'SELECT filename, content_type, content_hash FROM "{schema}".uploads')
        )
    ).all()
    return {row[0]: (row[1], row[2]) for row in rows if row[0]}


async def backfill_uploads_to_s3(*, dry_run: bool = False) -> BackfillSummary:
    """Copy every guild's local blobs into S3. See module docstring."""
    summary = BackfillSummary()
    root = Path(settings.UPLOADS_DIR)
    engine = db_session.provisioning_engine  # superuser: reads every guild schema
    async with engine.connect() as conn:
        guild_ids = (
            (await conn.execute(text("SELECT id FROM public.guilds ORDER BY id")))
            .scalars()
            .all()
        )
        for gid in guild_ids:
            guild_dir = root / f"guild_{gid}"
            if not guild_dir.is_dir():
                continue
            meta = await _guild_upload_meta(conn, guild_schema_name(gid))
            # Always a real S3 backend, even on a dry run, so the exists() skip
            # check reflects what's already in the bucket.
            dest = s3_guild_storage(gid)
            backfill_guild_dir(
                guild_dir, meta, dest, summary, guild_id=gid, dry_run=dry_run
            )
    return summary


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(
        description="Copy existing local uploads into the configured S3 bucket."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report what would be copied (checking the bucket for already-present "
        "objects) without writing",
    )
    args = parser.parse_args()
    if not settings.S3_BUCKET:
        raise SystemExit(
            "S3_BUCKET (and the other S3_* settings) must point at your object "
            "store to run the backfill (a dry run queries the bucket too)."
        )
    summary = asyncio.run(backfill_uploads_to_s3(dry_run=args.dry_run))
    logger.info(
        "backfill complete: copied=%d skipped=%d failed=%d hash_mismatches=%d",
        summary.copied,
        summary.skipped,
        summary.failed,
        summary.hash_mismatches,
    )
    if summary.failed:
        logger.error(
            "backfill had %d failure(s): %s", summary.failed, summary.failed_keys
        )
        raise SystemExit(1)


if __name__ == "__main__":
    main()
