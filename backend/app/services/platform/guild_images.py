"""Guild icons and banners: who may see one, and how they are stored.

These are the only guild media a stranger can be shown. A listed guild's icon
and its banner's card rendition appear on its community-directory card, which
is served to any signed-in user; the full banner appears on the guild's own
front page, which is not. That asymmetry is the whole of this module:

    published variants (icon, card) — the guild listed itself, OR you belong
    the rest (full)                 — you belong
    neither                         — nothing exists as far as you are concerned

"belong" throughout includes a live PAM/break-glass grantee, who reaches the
guild for their window exactly as a member does. Which variants are published
is read from ``IMAGE_SPECS`` rather than restated here, so adding one is a
single edit in the registry.

The check runs on the system engine for the reason the directory itself does:
the caller is a stranger to the guild, so there is no guild-scoped role to read
it under, and ``public.guilds`` is scoped by RLS to the caller's own
memberships. The request path holds no grant on the image bytes at all — this
function is their only reader, which is why the rule lives here in one piece
rather than spread across the endpoints that serve it.
"""

from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import insert
from sqlmodel import delete, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.guild import Guild, GuildStatus
from app.models.platform.guild_image import (
    IMAGE_CONTENT_TYPES,
    IMAGE_SPECS,
    GuildImage,
    GuildImageVariant,
)

#: How far a rendition may drift from its nominal proportions before it is
#: refused. Wide enough for the rounding a browser's canvas does, narrow enough
#: that a differently-shaped image cannot be passed off as one of these.
_RATIO_TOLERANCE = 0.02


class GuildImageError(Exception):
    """An uploaded image is not what it claims. Carries a message constant."""


@dataclass(frozen=True)
class Rendition:
    """One validated rendition, ready to store."""

    variant: GuildImageVariant
    data: bytes
    content_type: str

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.data).hexdigest()


# --- reading -----------------------------------------------------------------


async def may_read_image(
    session: AsyncSession,
    *,
    guild_id: int,
    user_id: int,
    variant: GuildImageVariant,
) -> bool:
    """Whether ``user_id`` has somewhere to see this variant.

    Membership is checked first because it answers for every variant and is the
    common case. The listing legs are the directory's own filters — opted in,
    active, and a directory to be listed in — asked again here rather than
    inherited from whatever page produced the URL, so a guild that un-lists
    itself stops serving its card immediately.
    """
    from app.services.platform import access_grants as access_grants_service
    from app.services.platform import guilds as guilds_service

    membership = await guilds_service.get_membership(
        session, guild_id=guild_id, user_id=user_id
    )
    if membership is not None:
        # A suspended guild is unreadable to its own members, matching the
        # uploads route and the guild-context resolver.
        guild = await session.get(Guild, guild_id)
        return guild is not None and guild.status != GuildStatus.suspended.value

    grant = await access_grants_service.get_live_grant(
        session, user_id=user_id, guild_id=guild_id
    )
    if grant is not None:
        # PAM deliberately overrides lifecycle status, as everywhere else.
        return True

    if not IMAGE_SPECS[variant].published:
        return False
    return await _is_listed(session, guild_id=guild_id)


async def _is_listed(session: AsyncSession, *, guild_id: int) -> bool:
    """Whether this guild is currently showing a card in the directory."""
    from app.services.platform import app_settings as app_settings_service

    if not await app_settings_service.community_directory_enabled(session):
        return False
    guild = await session.get(Guild, guild_id)
    return (
        guild is not None
        and bool(guild.is_community)
        and guild.status == GuildStatus.active.value
    )


async def read_image(
    session: AsyncSession, *, guild_id: int, sha256: str
) -> GuildImage | None:
    """The guild's image with these exact bytes, or None.

    Addressed by digest rather than by variant so a URL minted for an image
    that has since been replaced resolves to nothing, instead of serving
    different bytes under a cache key the browser was told is immutable.
    """
    return (
        await session.exec(
            select(GuildImage).where(
                GuildImage.guild_id == guild_id,
                GuildImage.sha256 == sha256,
            )
        )
    ).first()


def image_url(guild_id: int, sha256: str) -> str:
    """The serving URL for one image.

    A platform path, not ``/g/{guild_id}/…``: these are public-plane identity,
    and the caller they are served to may hold no guild context at all.
    """
    return f"/api/v1/guilds/{guild_id}/image/{sha256}"


async def image_urls(
    session: AsyncSession,
    guild_ids: list[int] | set[int],
    *variants: GuildImageVariant,
) -> dict[int, dict[GuildImageVariant, str]]:
    """``guild_id -> {variant: URL}`` across many guilds, in one query.

    Projected to the digest alone. A list payload names images; it never
    carries them, so this must not drag a page's worth of bytes through the ORM
    to build a page's worth of strings.
    """
    ids = [int(value) for value in guild_ids]
    if not ids or not variants:
        return {}
    wanted = [variant.value for variant in variants]
    rows = await session.exec(
        select(GuildImage.guild_id, GuildImage.variant, GuildImage.sha256).where(
            GuildImage.guild_id.in_(ids),
            GuildImage.variant.in_(wanted),
        )
    )
    found: dict[int, dict[GuildImageVariant, str]] = {}
    for guild_id, variant, digest in rows:
        found.setdefault(guild_id, {})[GuildImageVariant(variant)] = image_url(
            guild_id, digest
        )
    return found


async def image_urls_for(
    session: AsyncSession, guild_id: int, *variants: GuildImageVariant
) -> dict[GuildImageVariant, str]:
    """One guild's URLs, keyed by variant; missing variants are simply absent."""
    return (await image_urls(session, [guild_id], *variants)).get(guild_id, {})


# --- writing -----------------------------------------------------------------


async def set_images(
    session: AsyncSession,
    *,
    guild_id: int,
    user_id: int,
    renditions: list[Rendition],
) -> dict[GuildImageVariant, str]:
    """Replace exactly the variants named by ``renditions``. Returns their URLs.

    Only those variants are touched: setting a guild's icon leaves its banner
    alone, and the two banner renditions are replaced together so a guild is
    never left showing a new card over an old front page.

    Written as statements rather than through the ORM, and in that order: a row
    here is only ever created or dropped, never edited — the primary key is
    (guild, variant), so "replace" means the old row leaves before the new one
    arrives. Handing both to the unit of work would let it reorder them, or
    reconcile them into an UPDATE, which is a statement this table grants
    nobody.
    """
    await clear_images(
        session,
        guild_id=guild_id,
        variants=[rendition.variant for rendition in renditions],
    )
    now = datetime.now(timezone.utc)
    urls: dict[GuildImageVariant, str] = {}
    rows = []
    for rendition in renditions:
        digest = rendition.sha256
        rows.append(
            {
                "guild_id": guild_id,
                "variant": rendition.variant.value,
                "sha256": digest,
                "content_type": rendition.content_type,
                "byte_size": len(rendition.data),
                "data": rendition.data,
                "created_by": user_id,
                "created_at": now,
            }
        )
        urls[rendition.variant] = image_url(guild_id, digest)
    if rows:
        await session.exec(insert(GuildImage).values(rows))
    return urls


async def clear_images(
    session: AsyncSession,
    *,
    guild_id: int,
    variants: list[GuildImageVariant],
) -> int:
    """Remove the named variants of this guild's images. Returns how many.

    One statement, and deliberately not the ORM's load-then-delete: the rows
    hold the pictures, so loading them in order to throw them away would pull a
    third of a megabyte through the process for nothing.
    """
    if not variants:
        return 0
    result = await session.exec(
        delete(GuildImage).where(
            GuildImage.guild_id == guild_id,
            GuildImage.variant.in_([variant.value for variant in variants]),
        )
    )
    return int(result.rowcount or 0)


# --- validating what arrived --------------------------------------------------


def validate_rendition(
    variant: GuildImageVariant, data: bytes, declared_content_type: str | None
) -> Rendition:
    """Check one uploaded rendition and return it ready to store.

    Four things are established here, and the declared content type is not one
    of them — it is a claim by the client, so the format is read from the bytes
    and the claim is discarded:

    * the bytes are PNG, JPEG, WebP, or GIF. Notably not SVG: these are
      rendered rather than downloaded, so the force-download handling that
      makes an SVG attachment safe has nothing to apply to.
    * they are no bigger than the variant's cap.
    * they are no larger than the variant's nominal size — a "card" carrying
      the full banner would defeat the point of having two.
    * they are the variant's shape, within a rounding tolerance.
    """
    from app.core.messages import GuildMessages

    spec = IMAGE_SPECS[variant]
    if not data:
        raise GuildImageError(GuildMessages.IMAGE_EMPTY)
    if len(data) > spec.max_bytes:
        raise GuildImageError(GuildMessages.IMAGE_TOO_LARGE)

    probed = probe_image(data)
    if probed is None or probed[0] not in IMAGE_CONTENT_TYPES:
        raise GuildImageError(GuildMessages.IMAGE_INVALID)
    content_type, width, height = probed
    del declared_content_type  # the bytes decide, not the client

    if width > spec.width or height > spec.height:
        raise GuildImageError(GuildMessages.IMAGE_WRONG_SIZE)
    if height <= 0:
        raise GuildImageError(GuildMessages.IMAGE_INVALID)
    if abs(width / height - spec.aspect) > spec.aspect * _RATIO_TOLERANCE:
        raise GuildImageError(GuildMessages.IMAGE_WRONG_RATIO)

    return Rendition(variant=variant, data=data, content_type=content_type)


def probe_image(data: bytes) -> tuple[str, int, int] | None:
    """``(content_type, width, height)`` read from an image header, or None.

    Header parsing rather than decoding: the formats a guild image may be in
    all state their dimensions in the first few dozen bytes, so this needs no
    image library and hands no uploaded pixels to one.
    """
    if data[:8] == b"\x89PNG\r\n\x1a\n" and data[12:16] == b"IHDR":
        width, height = struct.unpack(">II", data[16:24])
        return "image/png", int(width), int(height)
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return _probe_webp(data)
    if data[:6] in (b"GIF87a", b"GIF89a") and len(data) >= 10:
        width, height = struct.unpack("<HH", data[6:10])
        return "image/gif", int(width), int(height)
    if data[:2] == b"\xff\xd8":
        return _probe_jpeg(data)
    return None


def _probe_webp(data: bytes) -> tuple[str, int, int] | None:
    """WebP dimensions, across the three chunk layouts the format allows."""
    chunk = data[12:16]
    if chunk == b"VP8X" and len(data) >= 30:
        width = int.from_bytes(data[24:27], "little") + 1
        height = int.from_bytes(data[27:30], "little") + 1
        return "image/webp", width, height
    if chunk == b"VP8 " and len(data) >= 30:
        width = struct.unpack("<H", data[26:28])[0] & 0x3FFF
        height = struct.unpack("<H", data[28:30])[0] & 0x3FFF
        return "image/webp", width, height
    if chunk == b"VP8L" and len(data) >= 25:
        bits = int.from_bytes(data[21:25], "little")
        width = (bits & 0x3FFF) + 1
        height = ((bits >> 14) & 0x3FFF) + 1
        return "image/webp", width, height
    return None


#: JPEG frame markers that carry the image dimensions. The others are skipped.
_JPEG_SOF = {
    0xC0,
    0xC1,
    0xC2,
    0xC3,
    0xC5,
    0xC6,
    0xC7,
    0xC9,
    0xCA,
    0xCB,
    0xCD,
    0xCE,
    0xCF,
}


def _probe_jpeg(data: bytes) -> tuple[str, int, int] | None:
    """Walk a JPEG's segment chain to its start-of-frame marker."""
    index = 2
    length = len(data)
    while index + 3 < length:
        if data[index] != 0xFF:
            return None
        marker = data[index + 1]
        # Standalone markers carry no length field.
        if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
            index += 2
            continue
        segment = struct.unpack(">H", data[index + 2 : index + 4])[0]
        if marker in _JPEG_SOF:
            if index + 9 > length:
                return None
            height, width = struct.unpack(">HH", data[index + 5 : index + 9])
            return "image/jpeg", int(width), int(height)
        index += 2 + segment
    return None
