"""Guild branding for PDF report headers: the guild name and icon.

Injected at the render choke points (inline export + worker replay), so every
PDF report carries a running header without each adapter threading it. The
icon is a row in ``public.guild_images``, read here as bytes and staged into
the Typst compile root as an inline asset (it is not in guild storage, so the
storage-backed asset path can't reach it).

The bytes come from a session of this module's own, on the system engine: the
image tables grant the request path the digest and nothing else, and the
routed session an export runs under is a request-path session. The guild is
not in question by the time this runs — the export was authorized against it —
so what this adds is the ability to read one guild's own icon, nothing wider.

Branding never fails an export: a missing/unreadable guild or an
oversized/non-raster icon degrades to name-only or no header.
"""

from __future__ import annotations

from dataclasses import replace

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.guild import Guild
from app.models.platform.guild_image import GuildImage, GuildImageVariant
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
# Icons are small; cap the size so a pathological row can't bloat the
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
        name = (
            await session.exec(select(Guild.name).where(Guild.id == guild_id))
        ).first()
    except Exception:
        # Never fail an export over branding (e.g. a routing role that can't
        # read the shared guild row).
        return None, {}
    if name is None:
        return None, {}
    brand: dict = {"name": name, "icon": None}
    icon = await _load_icon(guild_id)
    if icon is None:
        return brand, {}
    filename, data = icon
    brand["icon"] = filename
    return brand, {filename: data}


async def _load_icon(guild_id: int) -> tuple[str, bytes] | None:
    """``(filename, bytes)`` for the guild's icon, or ``None``.

    On its own system-engine session, because the routed session an export runs
    under is granted the icon's digest and not its bytes. Scoped to the one
    guild the export is already for.
    """
    from app.db.session import AdminSessionLocal

    try:
        async with AdminSessionLocal() as admin_session:
            row = (
                await admin_session.exec(
                    select(GuildImage.content_type, GuildImage.data).where(
                        GuildImage.guild_id == guild_id,
                        GuildImage.variant == GuildImageVariant.icon.value,
                    )
                )
            ).first()
    except Exception:
        return None
    if row is None:
        return None
    return icon_asset(*row)


def icon_asset(
    content_type: str | None, data: bytes | None
) -> tuple[str, bytes] | None:
    """``(filename, bytes)`` for a stored icon, or ``None`` if it is no use here.

    Typst needs a filename with an extension it recognises, and the report is
    better off with no header than with a vector it has to parse or a blob that
    dwarfs the document.
    """
    ext = _MIME_EXT.get((content_type or "").lower())
    if ext is None or not data or len(data) > _MAX_ICON_BYTES:
        return None
    return f"guild-icon.{ext}", data
