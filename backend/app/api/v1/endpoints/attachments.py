from __future__ import annotations

import imghdr
from pathlib import Path
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

from app.api.deps import GuildContext, RLSSessionDep, get_current_active_user, get_guild_membership
from app.core.messages import AttachmentMessages
from app.core.config import settings
from app.models.upload import Upload
from app.models.user import User
from app.schemas.attachment import AttachmentUploadResponse

router = APIRouter()

ImageUploadUser = Annotated[User, Depends(get_current_active_user)]
GuildContextDep = Annotated[GuildContext, Depends(get_guild_membership)]


def _ensure_upload_dir() -> Path:
    upload_path = Path(settings.UPLOADS_DIR)
    upload_path.mkdir(parents=True, exist_ok=True)
    return upload_path


@router.post("/", response_model=AttachmentUploadResponse, status_code=status.HTTP_201_CREATED)
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

    contents = await file.read()
    if not contents:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=AttachmentMessages.FILE_EMPTY,
        )

    # SVG is XML-based so imghdr can't detect it; check content type and magic bytes
    is_svg = file.content_type == "image/svg+xml" or contents.lstrip()[:4] in (b"<?xm", b"<svg")
    detected_format = "svg" if is_svg else imghdr.what(None, contents)
    if detected_format is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=AttachmentMessages.INVALID_IMAGE,
        )

    original_suffix = Path(file.filename or "").suffix.lower()
    extension = original_suffix or f".{detected_format}"
    safe_extension = extension if extension.startswith(".") else f".{extension}"
    filename = f"{uuid4().hex}{safe_extension}"

    upload_dir = _ensure_upload_dir()
    destination = upload_dir / filename
    destination.write_bytes(contents)

    upload = Upload(
        filename=filename,
        guild_id=guild_context.guild_id,
        uploader_user_id=current_user.id,
        size_bytes=len(contents),
    )
    session.add(upload)
    await session.commit()

    return AttachmentUploadResponse(
        filename=file.filename or filename,
        url=f"/uploads/{filename}",
        content_type=file.content_type or f"image/{detected_format}",
        size=len(contents),
    )
