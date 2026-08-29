"""Storing, serving and removing the picture on a user's profile.

The bytes live in ``public.user_avatars`` and are addressed by their own
digest, so a profile payload carries a URL rather than the image and the
browser fetches each picture exactly once. See
``history/user-avatars-design.md``.

Validation is header-only — format and dimensions are read out of the first
bytes and the body is capped before it is buffered — so nothing here decodes an
image. ``app.core.image_headers`` explains why.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone

from typing import TYPE_CHECKING

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import delete, select

from app.core.config import API_V1_STR
from app.core.image_headers import read_image_header
from app.core.messages import UserMessages
from app.models.platform.user_avatar import (
    AVATAR_ASPECT_TOLERANCE,
    AVATAR_CONTENT_TYPES,
    AVATAR_MAX_BYTES,
    AVATAR_MAX_DIMENSION,
    UserAvatar,
)

if TYPE_CHECKING:  # pragma: no cover
    from app.models.platform.user import User

#: Where an avatar is served from. Same-origin by construction and addressed by
#: the digest of the bytes, so the URL is stable and cacheable forever.
AVATAR_URL_PREFIX = f"{API_V1_STR}/users/"

_HEX_DIGITS = frozenset("0123456789abcdef")
_DIGEST_LENGTH = 64


class AvatarRejected(Exception):
    """An upload that will not be stored, carrying the code naming why.

    A domain error rather than an ``HTTPException`` so the service stays
    callable from somewhere that is not a request; the endpoint maps ``code``
    onto the response.
    """

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class ValidatedAvatar:
    """An upload that passed every check, ready to store."""

    data: bytes
    sha256: str
    content_type: str
    width: int
    height: int

    @property
    def byte_size(self) -> int:
        return len(self.data)


def avatar_url(user_id: int, sha256: str) -> str:
    """The serving path for one stored avatar."""
    return f"{AVATAR_URL_PREFIX}{user_id}/avatar/{sha256}"


def is_avatar_url(value: str) -> bool:
    """Whether ``value`` is a path this API serves rather than an external one.

    The write side of ``avatar_url`` means "a picture hosted somewhere else", so
    a read payload handed back unchanged must not be stored as though it were.
    """
    return value.startswith(AVATAR_URL_PREFIX)


def is_valid_digest(value: str) -> bool:
    return len(value) == _DIGEST_LENGTH and all(c in _HEX_DIGITS for c in value)


def validate_avatar(data: bytes) -> ValidatedAvatar:
    """Check an uploaded image and describe it, or raise ``AvatarRejected``.

    The content type recorded is the one the header proves, never the one the
    client claimed, because it is served back in a ``Content-Type``.
    """
    if not data:
        raise AvatarRejected(UserMessages.AVATAR_INVALID_IMAGE)
    if len(data) > AVATAR_MAX_BYTES:
        raise AvatarRejected(UserMessages.AVATAR_TOO_LARGE)

    header = read_image_header(data)
    if header is None or header.content_type not in AVATAR_CONTENT_TYPES:
        raise AvatarRejected(UserMessages.AVATAR_INVALID_IMAGE)

    if header.width > AVATAR_MAX_DIMENSION or header.height > AVATAR_MAX_DIMENSION:
        raise AvatarRejected(UserMessages.AVATAR_TOO_LARGE_DIMENSIONS)

    longest = max(header.width, header.height)
    if abs(header.width - header.height) / longest > AVATAR_ASPECT_TOLERANCE:
        raise AvatarRejected(UserMessages.AVATAR_NOT_SQUARE)

    return ValidatedAvatar(
        data=data,
        sha256=hashlib.sha256(data).hexdigest(),
        content_type=header.content_type,
        width=header.width,
        height=header.height,
    )


async def get_avatar(session: AsyncSession, *, user_id: int) -> UserAvatar | None:
    return (
        await session.exec(select(UserAvatar).where(UserAvatar.user_id == user_id))
    ).first()


async def store_avatar(
    session: AsyncSession, *, user: "User", avatar: ValidatedAvatar
) -> str:
    """Write ``avatar`` as the user's picture, replacing any it had.

    One row per user, so a replacement overwrites in place and there is never
    an orphan set of bytes to sweep. Returns the stored digest.

    ``users.avatar_url`` is set to the serving path in the same transaction.
    That column already meant "where this user's picture is", and an uploaded
    picture and a linked external one were already alternatives — so recording
    ours there keeps every payload that carries a user able to name the image
    without a second query, and leaves exactly one field for a client to read.
    """
    # Upsert rather than read-then-write: the row is keyed by user alone, so
    # two uploads landing together (a double-click, two tabs) would otherwise
    # both find nothing and both insert. Last writer wins, which is what
    # "replace my picture" means.
    values = {
        "user_id": user.id,
        "sha256": avatar.sha256,
        "content_type": avatar.content_type,
        "byte_size": avatar.byte_size,
        "width": avatar.width,
        "height": avatar.height,
        "data": avatar.data,
        "created_at": datetime.now(timezone.utc),
    }
    statement = pg_insert(UserAvatar).values(**values)
    await session.exec(
        statement.on_conflict_do_update(
            index_elements=[UserAvatar.user_id],
            set_={k: v for k, v in values.items() if k != "user_id"},
        )
    )
    user.avatar_url = avatar_url(user.id, avatar.sha256)
    session.add(user)
    await session.flush()
    return values["sha256"]


async def delete_avatar(
    session: AsyncSession, *, user_id: int, user: "User | None" = None
) -> bool:
    """Remove the user's picture. True when there was one.

    The bytes are destroyed rather than soft-deleted: this is also the
    moderation path, and retaining the offending image would defeat it.

    Clears ``users.avatar_url`` when it points at the row being removed, so the
    pair cannot drift into naming bytes that are gone. An externally hosted
    picture is left alone — it is a different thing, and callers that mean to
    take that down as well say so themselves.
    """
    result = await session.exec(delete(UserAvatar).where(UserAvatar.user_id == user_id))
    if user is not None and user.avatar_url and is_avatar_url(user.avatar_url):
        user.avatar_url = None
        session.add(user)
    return bool(result.rowcount)


async def resolve_avatar_urls(
    session: AsyncSession, user_ids: list[int]
) -> dict[int, str]:
    """Map user id -> serving URL for those of ``user_ids`` that have a picture.

    One query for the whole set: the callers are list payloads, where a lookup
    per row would be the N+1 this change exists to avoid. ``data`` is left out
    of the projection, so the bytes are never detoasted to build a URL.
    """
    if not user_ids:
        return {}
    rows = (
        await session.exec(
            select(UserAvatar.user_id, UserAvatar.sha256).where(
                UserAvatar.user_id.in_(set(user_ids))
            )
        )
    ).all()
    return {user_id: avatar_url(user_id, digest) for user_id, digest in rows}
