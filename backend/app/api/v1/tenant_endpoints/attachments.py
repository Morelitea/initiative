from __future__ import annotations

from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

from app.api.deps import (
    GuildContext,
    RLSSessionDep,
    get_current_active_user,
    get_guild_membership,
)
from app.core.image_headers import read_image_header
from app.core.messages import AttachmentMessages
from app.models.tenant.upload import Upload
from app.models.platform.user import User
from app.schemas.tenant.attachment import AttachmentUploadResponse
from app.services.tenant.attachments import (
    FileTooLargeError,
    StorageQuotaExceededError,
    compute_content_hash,
    enforce_storage_quota,
    read_upload_bounded,
)
from app.services import storage_config
from app.services.storage import get_guild_storage

router = APIRouter()

MAX_IMAGE_BYTES = 10 * 1024 * 1024

#: What a document image may be, and the suffix its stored copy takes. The four
#: raster formats ``read_image_header`` identifies, plus the three this endpoint
#: allows on top of them: TIFF and ICO, which it does not read, and SVG, which
#: is markup rather than a raster and so is served as a download.
_SUFFIXES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/tiff": ".tiff",
    "image/x-icon": ".ico",
    "image/svg+xml": ".svg",
}

#: How far into a file the SVG root element may sit — past a byte-order mark, an
#: XML declaration, comments and a doctype. Generous for an editor's preamble,
#: bounded so the check stays a slice of the head rather than a scan of 10 MB.
_SVG_HEAD_BYTES = 1024

#: What may follow the root element's name: whitespace before an attribute, or
#: the end of an empty or opening tag. Anything else is a different element
#: whose name happens to start with the same three letters.
_ROOT_NAME_ENDS = (b" ", b"\t", b"\r", b"\n", b">", b"/")

ImageUploadUser = Annotated[User, Depends(get_current_active_user)]
GuildContextDep = Annotated[GuildContext, Depends(get_guild_membership)]


def _past_the_prolog(head: bytes) -> bytes:
    """Drop what an XML document may carry before its root element — a
    byte-order mark, whitespace, the declaration, comments and a doctype —
    and return what is left of ``head``."""
    head = head.lstrip(b"\xef\xbb\xbf").lstrip()
    while True:
        if head.startswith(b"<?"):
            end, skip = head.find(b"?>"), 2
        elif head.startswith(b"<!--"):
            end, skip = head.find(b"-->"), 3
        elif head.startswith(b"<!"):
            end, skip = head.find(b">"), 1
        else:
            return head
        if end < 0:
            # The construct runs past the slice being read; nothing to return.
            return b""
        head = head[end + skip :].lstrip()


def _opens_an_svg(contents: bytes) -> bool:
    """Whether the file's root element is ``<svg>``.

    Raster signatures are checked before this, so the question here is only
    whether markup is an SVG rather than something else — and the answer is
    read from a bounded slice of the head, not from a parse of the body.
    """
    head = _past_the_prolog(contents[:_SVG_HEAD_BYTES])
    if head[:1] != b"<":
        return False
    name = head[1:5].lower()
    return name[:3] == b"svg" and name[3:4] in _ROOT_NAME_ENDS


def _detect_content_type(contents: bytes) -> str | None:
    """Identify an upload from its bytes, or ``None`` if it is not an image.

    The client's ``Content-Type`` and filename are not consulted — the rule the
    gallery, avatar, guild-image and announcement paths already follow, and a
    mislabelled PNG is still a PNG. What comes back is what the stored row, the
    stored name and the served response all describe the file as.
    """
    header = read_image_header(contents)
    if header is not None:
        return header.content_type
    if contents[:4] in (b"II\x2a\x00", b"MM\x00\x2a"):
        return "image/tiff"
    if contents[:4] == b"\x00\x00\x01\x00":
        return "image/x-icon"
    if _opens_an_svg(contents):
        return "image/svg+xml"
    return None


@router.post(
    "/", response_model=AttachmentUploadResponse, status_code=status.HTTP_201_CREATED
)
async def upload_attachment(
    current_user: ImageUploadUser,
    session: RLSSessionDep,
    guild_context: GuildContextDep,
    file: UploadFile = File(...),
) -> AttachmentUploadResponse:
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=AttachmentMessages.IMAGE_ONLY,
        )

    try:
        contents = await read_upload_bounded(file, MAX_IMAGE_BYTES)
    except FileTooLargeError:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=AttachmentMessages.TOO_LARGE,
        )
    if not contents:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=AttachmentMessages.FILE_EMPTY,
        )

    content_type = _detect_content_type(contents)
    if content_type is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=AttachmentMessages.INVALID_IMAGE,
        )

    # The stored name carries the detected format, so the suffix the serve path
    # reads and the type recorded on the row describe the same bytes.
    filename = f"{uuid4().hex}{_SUFFIXES[content_type]}"

    try:
        await enforce_storage_quota(
            session, guild_id=guild_context.guild_id, incoming_bytes=len(contents)
        )
    except StorageQuotaExceededError:
        raise HTTPException(
            status_code=status.HTTP_507_INSUFFICIENT_STORAGE,
            detail=AttachmentMessages.STORAGE_QUOTA_EXCEEDED,
        )

    # Pick up a backend/credential change saved in another worker before writing,
    # so the blob lands in the configured store (TTL-gated; usually a no-op).
    await storage_config.ensure_storage_config_fresh(session)
    get_guild_storage(guild_context.guild_id).write(
        filename, contents, content_type=content_type
    )

    upload = Upload(
        filename=filename,
        created_by=current_user.id,
        size_bytes=len(contents),
        content_type=content_type,
        content_hash=compute_content_hash(contents),
    )
    session.add(upload)
    await session.commit()

    return AttachmentUploadResponse(
        filename=file.filename or filename,
        # Guild in the path so the served media self-describes its guild.
        url=f"/uploads/{guild_context.guild_id}/{filename}",
        content_type=content_type,
        size=len(contents),
    )
