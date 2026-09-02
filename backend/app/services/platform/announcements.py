"""Which announcements a person is shown, and what they have done with them.

Two sources feed one list: the notices an operator wrote (``announcements``)
and the ones compiled into this version of the app
(``app.core.builtin_announcements``). They are merged here rather than in the
endpoint so the read path, the admin preview and the tests all agree on what
"live for this person" means.

Three questions, in order:

1. **Is it live?** Published, not scheduled for later, not expired.
2. **Is it for them?** The row's two audience filters — a minimum platform rung
   and "administers a guild somewhere". This is relevance, not confidentiality:
   an announcement is a notice about the product, and the thing that must not
   leak is a *draft*, which RLS handles.
3. **Have they finished with it?** Dismissals take it out of the queue once
   there are as many as the notice asked for (normally one); merely having
   seen it does not.

A notice with a ``trigger_route`` is returned like any other but is not queued
on sight — the client holds it until the reader opens a matching page. Route
matching lives there because the routes do.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional, Sequence

from sqlalchemy import case, func, or_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import delete, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.builtin_announcements import BUILTIN_ANNOUNCEMENTS, BuiltinAnnouncement
from app.core.capabilities import role_rank
from app.core.image_headers import read_image_header
from app.core.messages import AnnouncementMessages
from app.models.platform.announcement import (
    ANNOUNCEMENT_IMAGE_CONTENT_TYPES,
    ANNOUNCEMENT_IMAGE_MAX_DIMENSION,
    Announcement,
    AnnouncementImage,
    AnnouncementReadReceipt,
    db_announcement_key,
)
from app.models.platform.guild import GuildMembership, GuildRole
from app.models.platform.user import User, UserRole
from app.schemas.platform.announcement import (
    IMAGE_PATH_PREFIX,
    AnnouncementAdminRead,
    AnnouncementRead,
    AnnouncementSection,
    AnnouncementUpdate,
    AnnouncementWrite,
)

#: How long an uploaded picture nothing points at is kept before the pruner
#: takes it. Long enough to survive an editing session that uploads a
#: screenshot and saves the announcement an hour later.
ORPHAN_IMAGE_GRACE = timedelta(days=1)


class AnnouncementImageError(Exception):
    """An uploaded picture is not usable. Carries a message constant."""


# --- audience ----------------------------------------------------------------


def _audience_matches(
    *,
    min_platform_role: UserRole,
    guild_admins_only: bool,
    user: User,
    is_guild_admin: bool,
) -> bool:
    """Whether this reader is in the audience the author chose."""
    if role_rank(user.role) < role_rank(min_platform_role):
        return False
    if guild_admins_only and not is_guild_admin:
        return False
    return True


async def administers_a_guild(session: AsyncSession, *, user_id: int) -> bool:
    """Whether this account is an admin of at least one guild.

    One of the two audience filters. Deliberately "somewhere" rather than "in
    the guild you are looking at": an announcement has no guild context, and
    the notices that target admins are about the admin surface itself.
    """
    result = await session.exec(
        select(GuildMembership.guild_id)
        .where(
            GuildMembership.user_id == user_id,
            GuildMembership.role == GuildRole.admin,
        )
        .limit(1)
    )
    return result.first() is not None


# --- reading -----------------------------------------------------------------


def _is_live(
    published_at: Optional[datetime], expires_at: Optional[datetime], now: datetime
) -> bool:
    if published_at is None or published_at > now:
        return False
    return expires_at is None or expires_at > now


async def _receipts(
    session: AsyncSession, *, user_id: int
) -> dict[str, AnnouncementReadReceipt]:
    result = await session.exec(
        select(AnnouncementReadReceipt).where(
            AnnouncementReadReceipt.user_id == user_id
        )
    )
    return {row.announcement_key: row for row in result.all()}


def _to_read(announcement: Announcement) -> AnnouncementRead:
    return AnnouncementRead(
        key=db_announcement_key(announcement.id or 0),
        title=announcement.title,
        category=announcement.category,
        sections=[AnnouncementSection.model_validate(s) for s in announcement.sections],
        published_at=announcement.published_at,
        is_builtin=False,
        dismissals_required=announcement.dismissals_required,
        trigger_route=announcement.trigger_route,
    )


def to_admin_read(announcement: Announcement) -> AnnouncementAdminRead:
    """The full row, for the surface that writes them."""
    return AnnouncementAdminRead(
        key=db_announcement_key(announcement.id or 0),
        id=announcement.id,
        title=announcement.title,
        category=announcement.category,
        sections=[AnnouncementSection.model_validate(s) for s in announcement.sections],
        published_at=announcement.published_at,
        is_builtin=False,
        dismissals_required=announcement.dismissals_required,
        trigger_route=announcement.trigger_route,
        min_platform_role=UserRole(announcement.min_platform_role),
        guild_admins_only=announcement.guild_admins_only,
        expires_at=announcement.expires_at,
        created_by=announcement.created_by,
        created_at=announcement.created_at,
        updated_at=announcement.updated_at,
    )


def builtin_admin_read(builtin: BuiltinAnnouncement) -> AnnouncementAdminRead:
    """A compiled-in notice in the admin list's shape, marked uneditable."""
    return AnnouncementAdminRead(
        key=builtin.key,
        id=None,
        title=builtin.title,
        category=builtin.category,
        sections=list(builtin.sections),
        published_at=builtin.published_at,
        is_builtin=True,
        dismissals_required=builtin.dismissals_required,
        trigger_route=builtin.trigger_route,
        min_platform_role=builtin.min_platform_role,
        guild_admins_only=builtin.guild_admins_only,
        expires_at=builtin.expires_at,
    )


async def list_for_user(
    session: AsyncSession,
    *,
    user: User,
    include_dismissed: bool = False,
    now: Optional[datetime] = None,
) -> list[AnnouncementRead]:
    """Every live announcement this person is in the audience for.

    Newest first, so a queue that shows one at a time leads with the news
    rather than with the backlog. ``include_dismissed`` is what the archive
    page turns on: a notice already dealt with is still one this reader was
    told and may want to re-read. An *expired* one is not — an end date
    retires a notice everywhere, and the row is unreadable on this path once
    it passes.
    """
    now = now or datetime.now(timezone.utc)
    is_guild_admin = await administers_a_guild(session, user_id=user.id)
    receipts = await _receipts(session, user_id=user.id)

    rows = (
        await session.exec(
            select(Announcement).where(
                Announcement.published_at.is_not(None),  # ty: ignore[unresolved-attribute]
                Announcement.published_at <= now,
                or_(
                    Announcement.expires_at.is_(None),  # ty: ignore[unresolved-attribute]
                    Announcement.expires_at > now,
                ),
            )
        )
    ).all()

    items: list[AnnouncementRead] = []
    for row in rows:
        if not _audience_matches(
            min_platform_role=UserRole(row.min_platform_role),
            guild_admins_only=row.guild_admins_only,
            user=user,
            is_guild_admin=is_guild_admin,
        ):
            continue
        items.append(_to_read(row))

    for builtin in BUILTIN_ANNOUNCEMENTS:
        if not _is_live(builtin.published_at, builtin.expires_at, now):
            continue
        if not _audience_matches(
            min_platform_role=builtin.min_platform_role,
            guild_admins_only=builtin.guild_admins_only,
            user=user,
            is_guild_admin=is_guild_admin,
        ):
            continue
        items.append(builtin.to_read())

    visible: list[AnnouncementRead] = []
    for item in items:
        receipt = receipts.get(item.key)
        if receipt is not None:
            item.dismissed_at = receipt.dismissed_at
            item.dismiss_count = receipt.dismiss_count
            if receipt.dismiss_count >= item.dismissals_required:
                if not include_dismissed:
                    continue
        visible.append(item)

    visible.sort(
        key=lambda a: a.published_at or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    return visible


async def announcement_exists(session: AsyncSession, *, key: str) -> bool:
    """Whether ``key`` names something a receipt may be recorded against.

    Checked before writing one so the table cannot be filled with keys that
    mean nothing. Draft and expired rows count: a reader who was shown a
    notice may still dismiss it after it stops being live.
    """
    for builtin in BUILTIN_ANNOUNCEMENTS:
        if builtin.key == key:
            return True
    announcement = await _load_by_key(session, key=key)
    return announcement is not None


async def _load_by_key(session: AsyncSession, *, key: str) -> Optional[Announcement]:
    prefix = "db:"
    if not key.startswith(prefix):
        return None
    try:
        announcement_id = int(key[len(prefix) :])
    except ValueError:
        return None
    return await session.get(Announcement, announcement_id)


async def record_receipt(
    session: AsyncSession,
    *,
    user_id: int,
    key: str,
    dismissed: bool,
    now: Optional[datetime] = None,
) -> AnnouncementReadReceipt:
    """Note that this person has seen — or is done with — this announcement.

    A sighting is idempotent: seeing something twice does not move its
    ``seen_at``, and never undoes a dismissal. A *dismissal* is counted rather
    than flagged, because a notice may ask to be acknowledged more than once —
    the count is what ``list_for_user`` compares against the announcement's
    ``dismissals_required``, and it is capped there so a client that posts
    twice cannot run it away.

    Written as a single upsert rather than read-then-write because two tabs
    dismissing the same notice at once is an ordinary thing to do: separate
    statements would either collide on the primary key (both finding no row)
    or lose an increment (both reading the same count). ``LEAST`` applies the
    cap inside the same statement that does the increment.
    """
    now = now or datetime.now(timezone.utc)
    required = await dismissals_required_for(session, key=key)

    values = {
        "user_id": user_id,
        "announcement_key": key,
        "seen_at": now,
        "dismissed_at": now if dismissed else None,
        "dismiss_count": 1 if dismissed else 0,
    }
    statement = pg_insert(AnnouncementReadReceipt).values(**values)
    table = statement.excluded
    if dismissed:
        counted = func.least(
            AnnouncementReadReceipt.__table__.c.dismiss_count + 1, required
        )
        statement = statement.on_conflict_do_update(
            index_elements=["user_id", "announcement_key"],
            set_={
                "dismiss_count": counted,
                # The stamp moves only when the count did; a dismissal past
                # what was asked for is not a new acknowledgement.
                "dismissed_at": case(
                    (
                        AnnouncementReadReceipt.__table__.c.dismiss_count < required,
                        table.dismissed_at,
                    ),
                    else_=AnnouncementReadReceipt.__table__.c.dismissed_at,
                ),
            },
        )
    else:
        # Being shown something again is not news.
        statement = statement.on_conflict_do_nothing(
            index_elements=["user_id", "announcement_key"]
        )
    await session.exec(statement)

    receipt = await session.get(AnnouncementReadReceipt, (user_id, key))
    if receipt is not None:
        # The upsert wrote behind the identity map's back; read the row as the
        # database now has it.
        await session.refresh(receipt)
    return receipt  # ty: ignore[invalid-return-type]


async def dismissals_required_for(session: AsyncSession, *, key: str) -> int:
    """How many acknowledgements the notice behind ``key`` asks for."""
    for builtin in BUILTIN_ANNOUNCEMENTS:
        if builtin.key == key:
            return builtin.dismissals_required
    announcement = await _load_by_key(session, key=key)
    return announcement.dismissals_required if announcement is not None else 1


# --- authoring ---------------------------------------------------------------


async def list_all(session: AsyncSession) -> list[AnnouncementAdminRead]:
    """Everything an author can see: drafts, scheduled, live and expired."""
    rows = (await session.exec(select(Announcement))).all()
    items = [to_admin_read(row) for row in rows]
    items.extend(builtin_admin_read(b) for b in BUILTIN_ANNOUNCEMENTS)
    items.sort(
        key=lambda a: (
            a.published_at or a.created_at or datetime.min.replace(tzinfo=timezone.utc)
        ),
        reverse=True,
    )
    return items


async def create(
    session: AsyncSession, *, payload: AnnouncementWrite, author_id: int
) -> Announcement:
    now = datetime.now(timezone.utc)
    announcement = Announcement(
        title=payload.title,
        category=payload.category.value,
        sections=[s.model_dump(mode="json") for s in payload.sections],
        min_platform_role=payload.min_platform_role.value,
        guild_admins_only=payload.guild_admins_only,
        published_at=payload.published_at,
        expires_at=payload.expires_at,
        dismissals_required=payload.dismissals_required,
        trigger_route=payload.trigger_route,
        created_by=author_id,
        created_at=now,
        updated_at=now,
    )
    session.add(announcement)
    await session.flush()
    return announcement


async def update(
    session: AsyncSession, *, announcement: Announcement, payload: AnnouncementUpdate
) -> Announcement:
    if payload.title is not None:
        announcement.title = payload.title
    if payload.category is not None:
        announcement.category = payload.category.value
    if payload.sections is not None:
        announcement.sections = [s.model_dump(mode="json") for s in payload.sections]
    if payload.min_platform_role is not None:
        announcement.min_platform_role = payload.min_platform_role.value
    if payload.guild_admins_only is not None:
        announcement.guild_admins_only = payload.guild_admins_only
    if payload.dismissals_required is not None:
        announcement.dismissals_required = payload.dismissals_required
    if payload.clear_trigger_route:
        announcement.trigger_route = None
    elif payload.trigger_route is not None:
        announcement.trigger_route = payload.trigger_route
    if payload.clear_published_at:
        announcement.published_at = None
    elif payload.published_at is not None:
        announcement.published_at = payload.published_at
    if payload.clear_expires_at:
        announcement.expires_at = None
    elif payload.expires_at is not None:
        announcement.expires_at = payload.expires_at
    announcement.updated_at = datetime.now(timezone.utc)
    session.add(announcement)
    await session.flush()
    return announcement


async def delete_announcement(
    session: AsyncSession, *, announcement: Announcement
) -> None:
    """Remove the notice and every receipt naming it."""
    key = db_announcement_key(announcement.id or 0)
    await session.exec(
        delete(AnnouncementReadReceipt).where(
            AnnouncementReadReceipt.announcement_key == key
        )
    )
    await session.delete(announcement)
    await session.flush()


# --- pictures ----------------------------------------------------------------


def image_url(sha256: str) -> str:
    return f"{IMAGE_PATH_PREFIX}{sha256}"


def _referenced_digests(sections: Iterable[dict]) -> set[str]:
    digests: set[str] = set()
    for section in sections:
        url = (section or {}).get("image_url")
        if isinstance(url, str) and url.startswith(IMAGE_PATH_PREFIX):
            digests.add(url[len(IMAGE_PATH_PREFIX) :])
    return digests


async def store_image(
    session: AsyncSession, *, data: bytes, user_id: int
) -> AnnouncementImage:
    """Validate an uploaded picture and keep it, or return the one already here.

    The format is read from the bytes rather than believed from the part's
    header, for the reason every other upload path here does it: the header is
    the client's claim, and what gets served back is decided by what the file
    actually is.
    """
    header = read_image_header(data)
    if header is None or header.content_type not in ANNOUNCEMENT_IMAGE_CONTENT_TYPES:
        raise AnnouncementImageError(AnnouncementMessages.IMAGE_UNSUPPORTED_TYPE)
    if (
        header.width > ANNOUNCEMENT_IMAGE_MAX_DIMENSION
        or header.height > ANNOUNCEMENT_IMAGE_MAX_DIMENSION
    ):
        raise AnnouncementImageError(AnnouncementMessages.IMAGE_TOO_LARGE)
    digest = hashlib.sha256(data).hexdigest()
    existing = await session.get(AnnouncementImage, digest)
    if existing is not None:
        # The same bytes are kept once, and re-uploading them is somebody
        # putting this picture here *now* — so the clock the pruner reads
        # restarts. Without this, re-using a screenshot older than the grace
        # period would hand back a URL the very next sweep deletes.
        existing.created_at = datetime.now(timezone.utc)
        session.add(existing)
        await session.flush()
        return existing

    image = AnnouncementImage(
        sha256=digest,
        content_type=header.content_type,
        byte_size=len(data),
        width=header.width,
        height=header.height,
        data=data,
        created_by=user_id,
        created_at=datetime.now(timezone.utc),
    )
    session.add(image)
    await session.flush()
    return image


async def read_image(
    session: AsyncSession, *, sha256: str
) -> Optional[AnnouncementImage]:
    return await session.get(AnnouncementImage, sha256)


async def prune_unreferenced_images(
    session: AsyncSession, *, now: Optional[datetime] = None
) -> int:
    """Drop pictures no announcement points at any more.

    Run after an announcement is saved or deleted. The grace period is what
    keeps it from taking a screenshot uploaded moments ago into an
    announcement still being written.
    """
    now = now or datetime.now(timezone.utc)
    cutoff = now - ORPHAN_IMAGE_GRACE

    referenced: set[str] = set()
    rows = (await session.exec(select(Announcement.sections))).all()
    for sections in rows:
        referenced |= _referenced_digests(sections or [])
    for builtin in BUILTIN_ANNOUNCEMENTS:
        referenced |= _referenced_digests(
            [s.model_dump(mode="json") for s in builtin.sections]
        )

    stale: Sequence[AnnouncementImage] = (
        await session.exec(
            select(AnnouncementImage).where(AnnouncementImage.created_at < cutoff)
        )
    ).all()
    removed = 0
    for image in stale:
        if image.sha256 in referenced:
            continue
        await session.delete(image)
        removed += 1
    if removed:
        await session.flush()
    return removed
