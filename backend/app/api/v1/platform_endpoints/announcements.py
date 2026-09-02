"""The notices this deployment shows its people, and the surface that writes them.

Two audiences on one router, deliberately kept apart by path and by session:

* **Readers** (``GET /announcements``, ``…/{key}/seen``, ``…/{key}/dismiss``)
  run on ``UserSessionDep``, so a draft is invisible to them at the database
  rather than by a filter someone could forget. What they may record is their
  own receipt, and RLS confines that to their own rows.
* **Authors** (``/announcements/admin/…``) hold ``announcements.manage`` and
  run on the system engine, which is what can see a draft at all.

Pictures are served from ``/announcements/images/{sha256}`` and authenticated
the way ``/uploads/*`` is — an ``<img>`` carries the session cookie on web and
a short-lived uploads-scoped token in a native WebView.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Path, Response, UploadFile
from fastapi import status
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import (
    UploadUserDep,
    UserSessionDep,
    get_current_active_user,
    require_capability,
)
from app.core.capabilities import Capability
from app.db.session import get_admin_session
from app.core.messages import AnnouncementMessages
from app.models.platform.announcement import (
    ANNOUNCEMENT_IMAGE_MAX_BYTES,
    Announcement,
)
from app.models.platform.user import User
from app.schemas.platform.announcement import (
    AnnouncementAdminListResponse,
    AnnouncementAdminRead,
    AnnouncementImageRead,
    AnnouncementListResponse,
    AnnouncementUpdate,
    AnnouncementWrite,
)
from app.services.platform import announcements as announcements_service
from app.services.tenant.attachments import FileTooLargeError, read_upload_bounded

router = APIRouter()

# The system engine: the only role that can see a draft, and the one that holds
# the picture bytes.
AdminSessionDep = Annotated[AsyncSession, Depends(get_admin_session)]

#: ``db:<id>`` or ``builtin:<slug>`` — the two forms a receipt can name. Bounded
#: here so a malformed key is a 422 rather than a lookup.
AnnouncementKeyPath = Annotated[
    str,
    Path(
        min_length=3,
        max_length=120,
        pattern=r"^(db:[0-9]+|builtin:[A-Za-z0-9_.\-]+)$",
        description="Announcement key — 'db:<id>' or 'builtin:<slug>'.",
    ),
]

AuthorDep = Annotated[
    User, Depends(require_capability(Capability.ANNOUNCEMENTS_MANAGE))
]


# --- reading -----------------------------------------------------------------


@router.get("", response_model=AnnouncementListResponse)
async def list_announcements(
    session: UserSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    include_dismissed: bool = False,
) -> AnnouncementListResponse:
    """Live announcements for this reader, newest first.

    The archive page asks for the dismissed ones too; an expired notice is
    gone from both, which is what an end date is for.
    """
    items = await announcements_service.list_for_user(
        session, user=current_user, include_dismissed=include_dismissed
    )
    return AnnouncementListResponse(items=items)


async def _record(
    session: AsyncSession, user: User, key: str, *, dismissed: bool
) -> Response:
    if not await announcements_service.announcement_exists(session, key=key):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=AnnouncementMessages.NOT_FOUND,
        )
    await announcements_service.record_receipt(
        session, user_id=user.id, key=key, dismissed=dismissed
    )
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{key}/seen", status_code=status.HTTP_204_NO_CONTENT)
async def mark_seen(
    key: AnnouncementKeyPath,
    session: UserSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> Response:
    """Note that this announcement has been put in front of the reader."""
    return await _record(session, current_user, key, dismissed=False)


@router.post("/{key}/dismiss", status_code=status.HTTP_204_NO_CONTENT)
async def dismiss(
    key: AnnouncementKeyPath,
    session: UserSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> Response:
    """The reader is done with this one; stop queueing it."""
    return await _record(session, current_user, key, dismissed=True)


@router.get("/images/{sha256}", include_in_schema=False)
async def read_announcement_image(
    sha256: Annotated[str, Path(pattern=r"^[0-9a-f]{64}$")],
    current_user: UploadUserDep,
    session: AdminSessionDep,
) -> Response:
    """Serve one announcement picture.

    Any signed-in account may read one: an announcement's audience decides who
    is *shown* a notice, not who may fetch a screenshot whose 64-hex address
    they would have to have been given in the first place.
    """
    image = await announcements_service.read_image(session, sha256=sha256)
    if image is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=AnnouncementMessages.IMAGE_NOT_FOUND,
        )
    return Response(
        content=image.data,
        media_type=image.content_type,
        headers={
            # The digest is in the path, so these bytes are these bytes
            # forever.
            "Cache-Control": "private, max-age=31536000, immutable",
            "X-Content-Type-Options": "nosniff",
        },
    )


# --- authoring ---------------------------------------------------------------


@router.get("/admin", response_model=AnnouncementAdminListResponse)
async def list_all_announcements(
    session: AdminSessionDep,
    _author: AuthorDep,
) -> AnnouncementAdminListResponse:
    """Every announcement, drafts and compiled-in notices included."""
    return AnnouncementAdminListResponse(
        items=await announcements_service.list_all(session)
    )


@router.post(
    "/admin", response_model=AnnouncementAdminRead, status_code=status.HTTP_201_CREATED
)
async def create_announcement(
    payload: AnnouncementWrite,
    session: AdminSessionDep,
    author: AuthorDep,
) -> AnnouncementAdminRead:
    announcement = await announcements_service.create(
        session, payload=payload, author_id=author.id
    )
    await session.commit()
    await session.refresh(announcement)
    return announcements_service.to_admin_read(announcement)


@router.patch("/admin/{announcement_id}", response_model=AnnouncementAdminRead)
async def update_announcement(
    announcement_id: int,
    payload: AnnouncementUpdate,
    session: AdminSessionDep,
    _author: AuthorDep,
) -> AnnouncementAdminRead:
    announcement = await _load(session, announcement_id)
    await announcements_service.update(
        session, announcement=announcement, payload=payload
    )
    await announcements_service.prune_unreferenced_images(session)
    await session.commit()
    await session.refresh(announcement)
    return announcements_service.to_admin_read(announcement)


@router.delete("/admin/{announcement_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_announcement(
    announcement_id: int,
    session: AdminSessionDep,
    _author: AuthorDep,
) -> Response:
    announcement = await _load(session, announcement_id)
    await announcements_service.delete_announcement(session, announcement=announcement)
    await announcements_service.prune_unreferenced_images(session)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/admin/images",
    response_model=AnnouncementImageRead,
    status_code=status.HTTP_201_CREATED,
)
async def upload_announcement_image(
    session: AdminSessionDep,
    author: AuthorDep,
    file: UploadFile = File(...),
) -> AnnouncementImageRead:
    """Store one picture and return the URL a section should point at."""
    try:
        data = await read_upload_bounded(file, ANNOUNCEMENT_IMAGE_MAX_BYTES)
    except FileTooLargeError:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=AnnouncementMessages.IMAGE_TOO_LARGE,
        )
    try:
        image = await announcements_service.store_image(
            session, data=data, user_id=author.id
        )
    except announcements_service.AnnouncementImageError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    await session.commit()
    return AnnouncementImageRead(
        url=announcements_service.image_url(image.sha256),
        sha256=image.sha256,
        content_type=image.content_type,
        byte_size=image.byte_size,
        width=image.width,
        height=image.height,
    )


async def _load(session: AsyncSession, announcement_id: int) -> Announcement:
    announcement = (
        await session.exec(
            select(Announcement).where(Announcement.id == announcement_id)
        )
    ).one_or_none()
    if announcement is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=AnnouncementMessages.NOT_FOUND,
        )
    return announcement
