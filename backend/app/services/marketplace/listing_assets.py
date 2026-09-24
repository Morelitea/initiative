"""The pictures a shared item uses, on their way out and back in.

An item's pictures live in its community's storage, where only that community
reaches them. A listing cannot point there. So sharing carries each picture
into the catalogue's own media (``media``), digest-pinned, and the listing
names it by the path it is served from; installing copies each one into the
installing community's storage, as that member's upload, and names it there.

Two kinds of reference are carried:

* **An upload URL anywhere in the envelope** — ``/uploads/<guild>/<file>`` in
  an editor body's image node, or a whiteboard's picture.
* **A gallery picture**, which names its file by storage key.

A picture that cannot be carried — not a raster image, larger than a listing
takes, or gone from storage — is simply not carried; the publish profile then
drops what still points at it, as it drops every upload URL a listing holds.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.tools import Tool
from app.services.marketplace import media

__all__ = [
    "MAX_ASSET_BYTES",
    "MAX_ASSETS",
    "MAX_ASSETS_TOTAL_BYTES",
    "carry_uploads",
    "land_assets",
    "media_paths_in",
]

#: The largest picture a listing carries.
MAX_ASSET_BYTES = 5 * 1024 * 1024
#: How many pictures one listing carries.
MAX_ASSETS = 60
#: What they may come to together.
MAX_ASSETS_TOTAL_BYTES = 32 * 1024 * 1024

_EXTENSIONS = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
}


def _walk_strings(value: Any, visit: Callable[[str], None]) -> None:
    if isinstance(value, str):
        visit(value)
    elif isinstance(value, dict):
        for child in value.values():
            _walk_strings(child, visit)
    elif isinstance(value, list):
        for child in value:
            _walk_strings(child, visit)


def _replace_strings(value: Any, replacements: dict[str, str]) -> Any:
    if isinstance(value, str):
        return replacements.get(value, value)
    if isinstance(value, dict):
        return {
            key: _replace_strings(child, replacements) for key, child in value.items()
        }
    if isinstance(value, list):
        return [_replace_strings(child, replacements) for child in value]
    return value


def media_paths_in(envelope: Any) -> list[str]:
    """Every catalogue media path an envelope names, first-seen order."""
    found: list[str] = []

    def visit(value: str) -> None:
        if media.digest_of(value) is not None and value not in found:
            found.append(value)

    _walk_strings(envelope, visit)
    return found


def _gallery_keys(tool: Tool, envelope: dict[str, Any]) -> list[str]:
    if tool is not Tool.gallery:
        return []
    keys = [
        image.get("storage_key")
        for image in envelope.get("images") or []
        if isinstance(image, dict)
    ]
    keys.append(envelope.get("cover"))
    return [key for key in keys if isinstance(key, str) and key]


def _read_blob(storage: Any, key: str) -> bytes | None:
    """A stored file's bytes, or ``None`` when it is gone or too large to
    carry."""
    blob = storage.open_readable(key)
    if blob is None:
        return None
    if blob.content_length is not None and blob.content_length > MAX_ASSET_BYTES:
        return None
    if blob.path is not None:
        data = Path(blob.path).read_bytes()
    else:
        data = blob.stream.read()
    return data if len(data) <= MAX_ASSET_BYTES else None


async def carry_uploads(
    catalog_session: AsyncSession,
    *,
    tool: Tool,
    envelope: dict[str, Any],
    guild_id: int,
) -> dict[str, Any]:
    """``envelope`` with each picture it uses kept in the catalogue and named
    by its media path.

    ``catalog_session`` writes the catalogue (the system engine). The keys
    read here come from the item's own export, which the member's session has
    already authorized, and from this guild's namespace only.
    """
    from app.services.storage import get_guild_storage
    from app.services.tenant.attachments import (
        extract_upload_urls,
        guild_id_from_upload_url,
        replace_upload_urls,
    )

    storage = get_guild_storage(guild_id)
    urls = [
        url
        for url in sorted(extract_upload_urls(envelope))
        if guild_id_from_upload_url(url) == guild_id
    ]
    wanted = [(url, Path(url).name) for url in urls]
    wanted += [(key, key) for key in _gallery_keys(tool, envelope) if "/" not in key]

    kept: dict[str, str] = {}
    total = 0
    for reference, key in wanted:
        if reference in kept or len(kept) >= MAX_ASSETS:
            continue
        data = await asyncio.to_thread(_read_blob, storage, key)
        if data is None or total + len(data) > MAX_ASSETS_TOTAL_BYTES:
            continue
        content_type = media.image_type_of(data)
        if content_type is None:
            continue
        total += len(data)
        kept[reference] = await media.store_media(
            catalog_session, data, content_type=content_type
        )

    # Upload URLs are matched however they were written (a body may hold an
    # absolute one); a gallery's keys are exact.
    carried = replace_upload_urls(
        envelope, {url: path for url, path in kept.items() if url in urls}
    )
    if tool is Tool.gallery:
        carried = _rekey_gallery(carried, kept)
    return carried


def _rekey_gallery(envelope: dict[str, Any], keys: dict[str, str]) -> dict[str, Any]:
    """A gallery with each picture's key and its cover mapped through ``keys``,
    and anything unmapped left blank for the importer to count as missing."""
    rekeyed = dict(envelope)
    rekeyed["images"] = [
        {**image, "storage_key": keys.get(image.get("storage_key") or "", "")}
        if isinstance(image, dict)
        else image
        for image in envelope.get("images") or []
    ]
    rekeyed["cover"] = keys.get(envelope.get("cover") or "")
    return rekeyed


async def land_assets(
    session: AsyncSession,
    *,
    tool: Tool,
    envelope: dict[str, Any],
    guild_id: int,
    user_id: int,
) -> dict[str, Any]:
    """``envelope`` with each picture it names copied into this guild's
    storage, as ``user_id``'s upload, and named there.

    The copies count against the guild's storage like any upload, and the
    whole install is refused if they do not fit. A path naming nothing the
    catalogue keeps is left as it is; the importer treats the picture as
    missing.
    """
    from app.db import session as db_session
    from app.models.tenant.upload import Upload
    from app.services.storage import get_guild_storage
    from app.services.tenant.attachments import (
        compute_content_hash,
        enforce_storage_quota,
    )

    paths = media_paths_in(envelope)
    if not paths:
        return envelope

    # The catalogue's media is read on the system engine: a guild-routed
    # session holds no grant on it.
    kept: dict[str, tuple[bytes, str]] = {}
    async with db_session.SystemSessionLocal() as catalog:
        for path in paths:
            digest = media.digest_of(path)
            found = await media.read_media(catalog, digest) if digest else None
            if found is not None:
                kept[path] = found

    await enforce_storage_quota(
        session,
        guild_id=guild_id,
        incoming_bytes=sum(len(data) for data, _ in kept.values()),
    )

    storage = get_guild_storage(guild_id)
    to_url: dict[str, str] = {}
    to_key: dict[str, str] = {}
    for path, (data, content_type) in kept.items():
        key = f"{uuid4().hex}{_EXTENSIONS.get(content_type, '')}"
        await asyncio.to_thread(storage.write, key, data, content_type=content_type)
        session.add(
            Upload(
                filename=key,
                created_by=user_id,
                size_bytes=len(data),
                content_type=content_type,
                content_hash=compute_content_hash(data),
            )
        )
        to_url[path] = f"/uploads/{guild_id}/{key}"
        to_key[path] = key
    await session.flush()

    if tool is Tool.gallery:
        # A gallery names its pictures by key, everything else by URL.
        return _rekey_gallery(envelope, to_key)
    return _replace_strings(envelope, to_url)
