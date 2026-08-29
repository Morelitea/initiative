"""The picture a user uploaded of themselves.

A name and a face are public information in this product: an avatar is served
to anyone holding its URL, with no membership check, so it lives in ``public``
beside the identity it belongs to rather than in any guild schema. An avatar
crosses guilds by definition — one user is in many — which is also why the
bytes are here and not in the object store: every S3 key is namespaced under a
guild, so there is nowhere else for them to go. ``MarketplaceMedia`` and the
guild banner are here for the same reason.

**Its own table rather than a ``bytea`` column on ``users``.** The ORM names
every mapped column in ``select(User)``, and naming a ``bytea`` column is
exactly what makes Postgres reassemble it out of TOAST — so a column here would
put the whole image on every user load in the app: auth, membership checks,
every join. ``users`` is far too hot for that.

One row per user. Who may write it is decided by the row policies (own-row) and
by ``app.services.platform.user_avatars`` for the moderation path, not here.
"""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import ConfigDict
from sqlalchemy import Column, DateTime, ForeignKey, Integer, LargeBinary, String
from sqlmodel import Field, SQLModel

#: Avatars render at 24-40px in lists and around 128px on the profile page, so
#: this covers 2x DPI everywhere with room to spare. The settings page resizes
#: to it, the upload endpoint checks against it, and the frontend states it.
AVATAR_MAX_DIMENSION = 256

#: Per-image byte ceiling, checked before the body is buffered.
AVATAR_MAX_BYTES = 64 * 1024

#: How far from square an upload may be before it is refused. A canvas resize
#: lands exactly on 1:1; the tolerance is for images prepared elsewhere.
AVATAR_ASPECT_TOLERANCE = 0.02

#: Raster only, and no SVG: an avatar is rendered rather than downloaded, so
#: the force-download escape hatch that makes an SVG attachment safe does not
#: apply here.
AVATAR_CONTENT_TYPES: frozenset[str] = frozenset(
    {"image/webp", "image/png", "image/jpeg"}
)


class UserAvatar(SQLModel, table=True):
    __tablename__ = "user_avatars"
    __allow_unmapped__ = True
    model_config = ConfigDict(arbitrary_types_allowed=True)

    # CASCADE: a deleted user takes their picture with them, through the same
    # cascade that removes their notifications and tokens.
    user_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        )
    )
    # Digest of these exact bytes. It is the last path segment of the serving
    # URL, so the URL changes whenever the picture does and the response can be
    # cached for as long as the browser likes.
    sha256: str = Field(sa_column=Column(String(64), nullable=False))
    content_type: str = Field(sa_column=Column(String(64), nullable=False))
    byte_size: int = Field(sa_column=Column(Integer, nullable=False))
    width: int = Field(sa_column=Column(Integer, nullable=False))
    height: int = Field(sa_column=Column(Integer, nullable=False))
    data: bytes = Field(sa_column=Column(LargeBinary, nullable=False))
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
