"""The listings this build ships with.

One JSON file per listing under ``app/marketplace_catalog/``, loaded and upserted
into the catalog at boot. No network, no config, nothing optional: a FOSS install
has a working marketplace out of the box, and a remote registry (later) adds to
the same tables through the same validator rather than a parallel path.

Seeding is idempotent and runs on the system engine. A file that fails validation
is logged and skipped — one malformed listing must not take the rest of the
catalog, or the boot, with it.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Iterator

from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.marketplace.catalog import CatalogError, upsert_listing

logger = logging.getLogger(__name__)

#: Where the shipped manifests live. Repo-relative, copied into the image.
CATALOG_DIR = Path(__file__).resolve().parent.parent.parent / "marketplace_catalog"

__all__ = ["CATALOG_DIR", "load_builtin_manifests", "seed_builtin_listings"]


def load_builtin_manifests(directory: Path | None = None) -> Iterator[dict[str, Any]]:
    """Every shipped manifest, in a stable order.

    Sorted by filename so a re-seed touches rows in the same order every time —
    which keeps a failure reproducible rather than depending on the filesystem.
    """
    root = directory or CATALOG_DIR
    if not root.is_dir():
        return
    for path in sorted(root.glob("*.json")):
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("marketplace: skipping unreadable listing %s: %s", path, exc)
            continue
        if not isinstance(manifest, dict):
            logger.warning("marketplace: skipping listing %s: not an object", path)
            continue
        yield manifest


async def seed_builtin_listings(
    session: AsyncSession, directory: Path | None = None
) -> int:
    """Upsert the shipped listings. Returns how many landed.

    Called from startup seeding on the system-engine session. Never raises: a bad
    manifest is a packaging bug to fix, not a reason to refuse to boot.
    """
    seeded = 0
    for manifest in load_builtin_manifests(directory):
        try:
            await upsert_listing(session, manifest, source="builtin")
            seeded += 1
        except CatalogError as exc:
            logger.warning("marketplace: skipping built-in listing: %s", exc)
    return seeded
