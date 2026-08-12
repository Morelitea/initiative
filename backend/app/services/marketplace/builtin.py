"""The listings this build ships with.

One JSON file per listing under ``app/marketplace_catalog/``, loaded and upserted
into the catalog at boot. No network: a FOSS install has a working marketplace
out of the box, and a remote registry (later) adds to the same tables through the
same validator rather than a parallel path.

Seeding is idempotent and runs on the system engine. A file that fails validation
is logged and skipped — one malformed listing must not take the rest of the
catalog, or the boot, with it.

Most of what ships applies everywhere. One listing does not: an app that opens
the deployment's own embed surface exists only where an operator configured one,
so seeding asks that question per manifest and withdraws anything the deployment
can no longer serve. That is the mechanism behind "a self-hosted install without
the configuration never sees the app" — it is absent from the catalog rather than
present and broken.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Iterator, Mapping

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.services.marketplace.catalog import (
    CatalogError,
    upsert_listing,
    withdraw_listing,
)

logger = logging.getLogger(__name__)

#: Where the shipped manifests live. Repo-relative, copied into the image.
CATALOG_DIR = Path(__file__).resolve().parent.parent.parent / "marketplace_catalog"

__all__ = [
    "CATALOG_DIR",
    "deployment_serves",
    "load_builtin_manifests",
    "seed_builtin_listings",
]


def deployment_serves(definition: Mapping[str, Any]) -> bool:
    """Whether this deployment can actually serve a listing with this body.

    Unconditional for everything except an embed on the deployment's own
    advanced-tool slot, which needs somewhere to point the iframe.

    That one setting, and not the signing key alongside it: the same URL is what
    reveals the initiative-level surface, so gating this one differently would
    show an operator one half of the same tool and hide the other. A URL without
    its key is a misconfiguration the boot log already names, and the app says so
    when opened rather than going missing from the catalog.
    """
    if definition.get("app_kind") != "embed":
        return True
    if definition.get("embed_target") == "advanced_tool":
        return bool(settings.ADVANCED_TOOL_URL)
    return False


def _deployment_naming(manifest: dict[str, Any]) -> dict[str, Any]:
    """The manifest as this deployment presents it.

    An advanced-tool embed is whatever the operator calls it — the same name the
    initiative-level surface already uses — so the catalog shows that rather than
    a generic one. Everything else is published as written.
    """
    definition = manifest.get("definition")
    if not isinstance(definition, Mapping):
        return manifest
    if definition.get("embed_target") != "advanced_tool":
        return manifest
    if not settings.ADVANCED_TOOL_NAME:
        return manifest
    return {**manifest, "name": settings.ADVANCED_TOOL_NAME}


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
    """Upsert the shipped listings this deployment serves. Returns how many landed.

    Called from startup seeding on the system-engine session. Never raises: a bad
    manifest is a packaging bug to fix, not a reason to refuse to boot.

    A listing this deployment cannot serve is withdrawn rather than skipped — an
    operator who removes the configuration an app depends on has taken it away,
    and the catalog has to stop offering it on the next boot rather than keep a
    row nobody can use. Guilds that already installed it keep their app.
    """
    seeded = 0
    for manifest in load_builtin_manifests(directory):
        definition = manifest.get("definition")
        if isinstance(definition, Mapping) and not deployment_serves(definition):
            uid = str(manifest.get("uid", ""))
            if uid and await withdraw_listing(session, uid):
                logger.info(
                    "marketplace: withdrew %s — this deployment no longer serves it",
                    manifest.get("public_id", uid),
                )
            continue
        try:
            await upsert_listing(
                session, _deployment_naming(manifest), source="builtin"
            )
            seeded += 1
        except CatalogError as exc:
            logger.warning("marketplace: skipping built-in listing: %s", exc)
    return seeded
