"""The images a guild is known by: its icon, and its banner.

Guild identity, not guild content — the same class of thing as the guild's name
and description, and in ``public`` for the same reason those are: a guild that
lists itself in the community directory shows its card to people who are not in
it and hold no role that could read a ``guild_<id>`` schema.

Stored as bytes here rather than in the guild blob store because the public
plane has no object store to put them in: every S3 key is namespaced under a
guild, which is exactly the boundary these have to cross.
(``MarketplaceMedia`` is here for the same reason.) They therefore do not count
against the guild's storage quota.

One row per (guild, variant) — see :class:`GuildImageVariant`. Who may read
which is decided by ``app.services.platform.guild_images``, not here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import ConfigDict
from sqlalchemy import Column, DateTime, ForeignKey, Integer, LargeBinary, String
from sqlmodel import Field, SQLModel


class GuildImageVariant(str, Enum):
    """The images a guild can have, and the renditions they are stored as.

    ``icon`` is the mark it is known by in a switcher, a card, a wizard. The
    two banner renditions come from one uploaded picture: ``full`` is what the
    guild's own front page shows, and ``card`` is the strip on its
    community-directory card — served to strangers and appearing up to sixty
    times on one page, which is why it is a separate, much smaller rendition
    rather than the full one scaled down in the browser.
    """

    icon = "icon"
    card = "card"
    full = "full"


@dataclass(frozen=True)
class ImageSpec:
    """What a variant must be, and who it may be shown to.

    ``published`` is the half that is not about pixels: it says this variant is
    part of what a guild publishes by listing itself in the directory, and so
    may be served to someone who is not in the guild. The front-page banner is
    not — a stranger has no front page to see it on.
    """

    width: int
    height: int
    max_bytes: int
    published: bool

    @property
    def aspect(self) -> float:
        return self.width / self.height


#: The single source of truth for each variant's geometry, weight, and
#: audience. The settings page resizes to it, the upload endpoint checks
#: against it, and the authorization check reads ``published`` from it.
IMAGE_SPECS: dict[GuildImageVariant, ImageSpec] = {
    GuildImageVariant.icon: ImageSpec(256, 256, 64 * 1024, published=True),
    GuildImageVariant.card: ImageSpec(1040, 260, 60 * 1024, published=True),
    GuildImageVariant.full: ImageSpec(2400, 600, 350 * 1024, published=False),
}

#: The renditions one banner upload produces, in the order they are stored.
BANNER_VARIANTS: tuple[GuildImageVariant, ...] = (
    GuildImageVariant.full,
    GuildImageVariant.card,
)

#: Raster only, and no SVG: these are rendered rather than downloaded, so the
#: force-download handling that makes an SVG attachment safe has nothing to
#: apply to.
IMAGE_CONTENT_TYPES: frozenset[str] = frozenset(
    {"image/webp", "image/png", "image/jpeg", "image/gif"}
)


class GuildImage(SQLModel, table=True):
    __tablename__ = "guild_images"
    __allow_unmapped__ = True
    model_config = ConfigDict(arbitrary_types_allowed=True)

    # CASCADE: a deleted guild takes its images with it, through the same
    # cascade off ``public.guilds`` that removes its memberships and invites.
    guild_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("guilds.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        )
    )
    variant: str = Field(sa_column=Column(String(8), primary_key=True, nullable=False))
    # Digest of these exact bytes. It is the last path segment of the serving
    # URL, so the URL changes whenever the image does and the response can be
    # cached for as long as the browser likes.
    sha256: str = Field(sa_column=Column(String(64), nullable=False))
    content_type: str = Field(sa_column=Column(String(64), nullable=False))
    byte_size: int = Field(sa_column=Column(Integer, nullable=False))
    data: bytes = Field(sa_column=Column(LargeBinary, nullable=False))
    created_by: Optional[int] = Field(
        default=None,
        sa_column=Column(Integer, ForeignKey("users.id"), nullable=True),
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
