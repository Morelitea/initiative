from __future__ import annotations

from pathlib import Path
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

from app.api.deps import (
    GuildContext,
    RLSSessionDep,
    get_current_active_user,
    get_guild_membership,
)
from app.core.messages import AttachmentMessages
from app.models.tenant.upload import Upload
from app.models.platform.user import User
from app.schemas.tenant.attachment import AttachmentUploadResponse
from app.services.attachments import (
    FileTooLargeError,
    StorageQuotaExceededError,
    compute_content_hash,
    enforce_storage_quota,
    read_upload_bounded,
)
from app.services.storage import get_guild_storage

router = APIRouter()

MAX_IMAGE_BYTES = 10 * 1024 * 1024

# Magic-byte detection yields a short format token; map it to a real MIME type
# for the rare case the client omits Content-Type. The image-only guard normally
# rejects a missing Content-Type first, so this is defense-in-depth -- but it must
# still emit valid MIME types (e.g. image/svg+xml, not image/svg).
_FORMAT_TO_MIME = {
    "png": "image/png",
    "jpeg": "image/jpeg",
    "gif": "image/gif",
    "webp": "image/webp",
    "tiff": "image/tiff",
    "svg": "image/svg+xml",
    "ico": "image/x-icon",
}

ImageUploadUser = Annotated[User, Depends(get_current_active_user)]
GuildContextDep = Annotated[GuildContext, Depends(get_guild_membership)]


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
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=AttachmentMessages.TOO_LARGE,
        )
    if not contents:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=AttachmentMessages.FILE_EMPTY,
        )

    # Detect image format from magic bytes (imghdr was removed in Python 3.13)
    is_svg = file.content_type == "image/svg+xml" or contents.lstrip()[:4] in (
        b"<?xm",
        b"<svg",
    )
    detected_format: str | None = None
    if is_svg:
        detected_format = "svg"
    elif contents[:8] == b"\x89PNG\r\n\x1a\n":
        detected_format = "png"
    elif contents[:2] == b"\xff\xd8":
        detected_format = "jpeg"
    elif contents[:6] in (b"GIF87a", b"GIF89a"):
        detected_format = "gif"
    elif contents[:4] == b"RIFF" and contents[8:12] == b"WEBP":
        detected_format = "webp"
    elif contents[:4] in (b"II\x2a\x00", b"MM\x00\x2a"):
        detected_format = "tiff"
    elif contents[:4] == b"\x00\x00\x01\x00":
        detected_format = "ico"
    if detected_format is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=AttachmentMessages.INVALID_IMAGE,
        )

    original_suffix = Path(file.filename or "").suffix.lower()
    extension = original_suffix or f".{detected_format}"
    safe_extension = extension if extension.startswith(".") else f".{extension}"
    filename = f"{uuid4().hex}{safe_extension}"

    try:
        await enforce_storage_quota(
            session, guild_id=guild_context.guild_id, incoming_bytes=len(contents)
        )
    except StorageQuotaExceededError:
        raise HTTPException(
            status_code=status.HTTP_507_INSUFFICIENT_STORAGE,
            detail=AttachmentMessages.STORAGE_QUOTA_EXCEEDED,
        )

    resolved_content_type = file.content_type or _FORMAT_TO_MIME[detected_format]
    get_guild_storage(guild_context.guild_id).write(
        filename, contents, content_type=resolved_content_type
    )

    upload = Upload(
        filename=filename,
        guild_id=guild_context.guild_id,
        uploader_user_id=current_user.id,
        size_bytes=len(contents),
        content_type=resolved_content_type,
        content_hash=compute_content_hash(contents),
    )
    session.add(upload)
    await session.commit()

    return AttachmentUploadResponse(
        filename=file.filename or filename,
        # Guild in the path so the served media self-describes its guild.
        url=f"/uploads/{guild_context.guild_id}/{filename}",
        content_type=resolved_content_type,
        size=len(contents),
    )
