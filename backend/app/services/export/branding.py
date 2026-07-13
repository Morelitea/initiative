"""Guild branding for PDF report headers: the guild name and icon.

Injected at the render choke points (inline export + worker replay), so every
PDF report carries a running header without each adapter threading it. The
icon lives on the guild row as a base64 data URI (``icon_base64``), decoded
here to bytes and staged into the Typst compile root as an inline asset (it is
not in guild storage, so the storage-backed asset path can't reach it).

Branding never fails an export: a missing/unreadable guild or an
undecodable/oversized/non-raster icon degrades to name-only or no header.
"""

from __future__ import annotations

import base64
import re
from dataclasses import replace

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.guild import Guild
from app.services.export.contract import RenderRequest

# Raster formats Typst renders reliably. SVG is deliberately excluded — a
# user-supplied vector icon is a needless parser surface in the trusted
# report, and the header only needs a small bitmap.
_MIME_EXT = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/gif": "gif",
    "image/webp": "webp",
}
_DATA_URI_RE = re.compile(r"^data:(?P<mime>[\w/+.-]+);base64,(?P<b64>.+)$", re.DOTALL)
# Icons are small; cap the decoded size so a pathological row can't bloat the
# compile input.
_MAX_ICON_BYTES = 3 * 1024 * 1024


async def apply_brand(request: RenderRequest, session: AsyncSession) -> RenderRequest:
    """Return ``request`` with the guild's name/icon added to every PDF item's
    payload (as ``brand``) and the icon bytes staged inline. Non-PDF requests
    and branding failures pass through unchanged."""
    if request.format != "pdf":
        return request
    brand, inline = await _load_brand(session, request.guild_id)
    if brand is None:
        return request
    batch = tuple(
        replace(
            item,
            data={**item.data, "brand": brand},
            assets_inline={**item.assets_inline, **inline},
        )
        for item in request.batch
    )
    return replace(request, batch=batch)


async def _load_brand(
    session: AsyncSession, guild_id: int
) -> tuple[dict | None, dict[str, bytes]]:
    try:
        row = (
            await session.exec(
                select(Guild.name, Guild.icon_base64).where(Guild.id == guild_id)
            )
        ).first()
    except Exception:
        # Never fail an export over branding (e.g. a routing role that can't
        # read the shared guild row).
        return None, {}
    if row is None:
        return None, {}
    name, icon_base64 = row
    brand: dict = {"name": name, "icon": None}
    decoded = _decode_icon(icon_base64)
    if decoded is None:
        return brand, {}
    filename, data = decoded
    brand["icon"] = filename
    return brand, {filename: data}


def _decode_icon(icon_base64: str | None) -> tuple[str, bytes] | None:
    """Decode a ``data:image/*;base64,…`` URI to ``(filename, bytes)``, or
    ``None`` if absent/malformed/non-raster/oversized."""
    if not icon_base64:
        return None
    match = _DATA_URI_RE.match(icon_base64.strip())
    if match is None:
        return None
    ext = _MIME_EXT.get(match.group("mime").lower())
    if ext is None:
        return None
    try:
        data = base64.b64decode(match.group("b64"), validate=True)
    except (ValueError, base64.binascii.Error):
        return None
    if not data or len(data) > _MAX_ICON_BYTES:
        return None
    return f"guild-icon.{ext}", data
