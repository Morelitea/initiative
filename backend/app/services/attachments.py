from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Set, Tuple
from urllib.parse import urlparse
from uuid import uuid4

from app.core.config import settings

logger = logging.getLogger(__name__)

UPLOADS_URL_PREFIX = "/uploads/"

# Maximum file size for document uploads: 50 MB
MAX_DOCUMENT_FILE_SIZE = 50 * 1024 * 1024

# Supported MIME types for document file uploads (based on react-doc-viewer support)
ALLOWED_DOCUMENT_MIME_TYPES: Dict[str, str] = {
    "application/pdf": ".pdf",
    "application/msword": ".doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.ms-excel": ".xls",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.ms-powerpoint": ".ppt",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
    "text/plain": ".txt",
    "text/html": ".html",
    # Images
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/svg+xml": ".svg",
    # Markdown
    "text/markdown": ".md",
}

# Extension to MIME type mapping for validation
EXTENSION_TO_MIME: Dict[str, str] = {
    ".pdf": "application/pdf",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xls": "application/vnd.ms-excel",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".ppt": "application/vnd.ms-powerpoint",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".txt": "text/plain",
    ".html": "text/html",
    ".htm": "text/html",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
    ".md": "text/markdown",
    ".markdown": "text/markdown",
}


def _uploads_dir() -> Path:
    path = Path(settings.UPLOADS_DIR)
    path.mkdir(parents=True, exist_ok=True)
    return path


def normalize_upload_url(url: str | None) -> str | None:
    if not url or not isinstance(url, str):
        return None
    url = url.strip()
    path = url
    if url.startswith("http://") or url.startswith("https://"):
        parsed = urlparse(url)
        path = parsed.path or ""
    if not path.startswith(UPLOADS_URL_PREFIX):
        return None
    filename = Path(path).name
    if not filename:
        return None
    return f"{UPLOADS_URL_PREFIX}{filename}"


def delete_upload_by_url(url: str | None) -> None:
    normalized = normalize_upload_url(url)
    if not normalized:
        return
    filename = Path(normalized).name
    target = _uploads_dir() / filename
    try:
        if target.exists() and target.is_file():
            target.unlink()
    except OSError as exc:
        logger.warning("Failed to delete upload %s: %s", target, exc)


def delete_uploads_by_urls(urls: Iterable[str]) -> None:
    seen: Set[str] = set()
    for url in urls:
        normalized = normalize_upload_url(url)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        delete_upload_by_url(normalized)


async def purge_document_uploads(session, documents: Iterable[Any]) -> None:
    """Delete Upload rows + filesystem blobs for documents about to be hard-purged.

    Handles both shapes:
    - ``document_type == "file"`` — Document and its sibling Upload row are
      a 1:1 binding (the Upload was created at the same moment the Document
      was created via POST /documents/upload). Always cleans up.
    - ``document_type == "native"`` — embedded URLs in ``content`` JSONB and
      ``featured_image_url`` may be shared across multiple documents. Runs
      an orphan check; only removes Upload + blob when no OTHER non-purged
      document still references the URL. Soft-deleted-but-not-purged
      documents still pin uploads (the user might restore them).

    Caller must use a session that can DELETE from ``uploads`` — typically
    ``AdminSessionDep`` for the auto-purge worker, or an admin-role
    ``RLSSessionDep`` for the manual "Delete Now" action. Caller commits.
    """
    from sqlalchemy import delete as sa_delete, or_, text

    from app.db.soft_delete_filter import select_including_deleted
    from app.models.document import Document, DocumentType
    from app.models.upload import Upload

    docs_list = list(documents)
    if not docs_list:
        return

    doomed_ids = {d.id for d in docs_list}

    # 1. File-type docs: 1:1 cleanup (no orphan check needed — the file
    #    backs exactly one document by construction).
    file_url_filenames: Set[str] = set()
    file_urls_to_unlink: Set[str] = set()
    for d in docs_list:
        if d.document_type == DocumentType.file and d.file_url:
            file_urls_to_unlink.add(d.file_url)
            normalized = normalize_upload_url(d.file_url)
            if normalized:
                file_url_filenames.add(Path(normalized).name)

    if file_url_filenames:
        await session.exec(
            sa_delete(Upload).where(Upload.filename.in_(file_url_filenames))
        )

    # 2. Native-doc embedded URLs: orphan-check before deletion.
    embedded_urls: Set[str] = set()
    for d in docs_list:
        if d.document_type == DocumentType.native:
            embedded_urls.update(extract_upload_urls(d.content))
            if d.featured_image_url:
                normalized = normalize_upload_url(d.featured_image_url)
                if normalized:
                    embedded_urls.add(normalized)

    orphan_urls: Set[str] = set()
    if embedded_urls:
        for url in embedded_urls:
            normalized = normalize_upload_url(url)
            if not normalized:
                continue
            # Escape LIKE wildcards in the URL before interpolating —
            # filenames legitimately contain ``_`` (treated as "any single
            # char" by LIKE) and could in theory contain ``%`` too. Without
            # this, the orphan check matches unintended URLs and leaves
            # blobs behind. ESCAPE '\\' opts in to backslash escaping.
            safe = (
                normalized.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            )
            stmt = (
                select_including_deleted(Document.id)
                .where(
                    or_(
                        text(
                            "documents.content::text LIKE :pattern ESCAPE '\\'"
                        ).bindparams(pattern=f"%{safe}%"),
                        Document.featured_image_url == normalized,
                    )
                )
                .where(~Document.id.in_(doomed_ids))
                .limit(1)
            )
            result = await session.exec(stmt)
            if result.one_or_none() is None:
                orphan_urls.add(normalized)

        if orphan_urls:
            orphan_filenames = {Path(u).name for u in orphan_urls}
            await session.exec(
                sa_delete(Upload).where(Upload.filename.in_(orphan_filenames))
            )

    # 3. Filesystem blobs — best-effort, after the rows are deleted so the
    #    invariant "Upload row exists ⇒ blob exists" holds in any
    #    intermediate state.
    delete_uploads_by_urls(file_urls_to_unlink | orphan_urls)


def extract_upload_urls(payload: Any) -> Set[str]:
    urls: Set[str] = set()

    def _walk(value: Any) -> None:
        if isinstance(value, str):
            normalized = normalize_upload_url(value)
            if normalized:
                urls.add(normalized)
        elif isinstance(value, dict):
            for item in value.values():
                _walk(item)
        elif isinstance(value, list):
            for item in value:
                _walk(item)

    _walk(payload)
    return urls


def duplicate_upload(url: str | None) -> str | None:
    normalized = normalize_upload_url(url)
    if not normalized:
        return None

    source_path = _uploads_dir() / Path(normalized).name
    if not source_path.exists():
        logger.warning("Attempted to duplicate missing upload %s", source_path)
        return normalized

    extension = source_path.suffix
    for _ in range(10):
        new_name = f"{uuid4().hex}{extension}"
        destination = _uploads_dir() / new_name
        if destination.exists():
            continue
        try:
            shutil.copy2(source_path, destination)
            return f"{UPLOADS_URL_PREFIX}{destination.name}"
        except OSError as exc:
            logger.error("Failed to duplicate upload %s -> %s: %s", source_path, destination, exc)
            return normalized
    logger.error("Unable to allocate new filename for duplicated upload %s", source_path)
    return normalized


def duplicate_uploads(urls: Iterable[str]) -> Dict[str, str]:
    mapping: Dict[str, str] = {}
    for url in urls:
        normalized = normalize_upload_url(url)
        if not normalized or normalized in mapping:
            continue
        duplicated = duplicate_upload(normalized)
        if duplicated and duplicated != normalized:
            mapping[normalized] = duplicated
    return mapping


def replace_upload_urls(payload: Any, replacements: Mapping[str, str]) -> Any:
    if not replacements:
        return payload

    def _walk(value: Any) -> Any:
        if isinstance(value, str):
            normalized = normalize_upload_url(value)
            if normalized and normalized in replacements:
                return replacements[normalized]
            return value
        if isinstance(value, dict):
            return {key: _walk(child) for key, child in value.items()}
        if isinstance(value, list):
            return [_walk(item) for item in value]
        return value

    return _walk(payload)


def detect_mime_type(content: bytes, filename: str | None = None) -> str | None:
    """Detect MIME type using python-magic, with fallback to extension.

    Returns the detected MIME type or None if detection fails.
    """
    try:
        import magic
        detected = magic.from_buffer(content, mime=True)
        if detected:
            return detected
    except Exception as exc:
        logger.warning("Failed to detect MIME type with magic: %s", exc)

    # Fallback to extension-based detection
    if filename:
        ext = Path(filename).suffix.lower()
        if ext in EXTENSION_TO_MIME:
            return EXTENSION_TO_MIME[ext]

    return None


def validate_document_file(
    content: bytes,
    filename: str | None,
    content_type: str | None,
) -> Tuple[str, str]:
    """Validate an uploaded document file.

    Args:
        content: File content bytes
        filename: Original filename
        content_type: Content-Type header from upload

    Returns:
        Tuple of (validated_mime_type, extension)

    Raises:
        ValueError: If validation fails
    """
    if len(content) > MAX_DOCUMENT_FILE_SIZE:
        raise ValueError(f"File exceeds maximum size of {MAX_DOCUMENT_FILE_SIZE // (1024 * 1024)} MB")

    if not content:
        raise ValueError("Uploaded file is empty")

    # Detect actual MIME type
    detected_mime = detect_mime_type(content, filename)

    if detected_mime and detected_mime not in ALLOWED_DOCUMENT_MIME_TYPES:
        # Magic returned an unrecognized type — fall back to extension if it
        # maps to an allowed type (e.g. magic returns text/x-markdown for .md)
        if filename:
            file_ext = Path(filename).suffix.lower()
            ext_mime = EXTENSION_TO_MIME.get(file_ext)
            if ext_mime and ext_mime in ALLOWED_DOCUMENT_MIME_TYPES:
                detected_mime = ext_mime
            else:
                raise ValueError(f"Unsupported file type: {detected_mime}")
        else:
            raise ValueError(f"Unsupported file type: {detected_mime}")

    # If we couldn't detect the MIME type, fall back to Content-Type header
    if not detected_mime:
        if content_type and content_type in ALLOWED_DOCUMENT_MIME_TYPES:
            detected_mime = content_type
        else:
            raise ValueError("Unable to determine file type. Supported types: PDF, Word, Excel, PowerPoint, TXT, HTML, images, Markdown")

    # Get extension for the detected MIME type
    extension = ALLOWED_DOCUMENT_MIME_TYPES.get(detected_mime, "")

    # If we have a filename, prefer its extension if it matches
    if filename:
        file_ext = Path(filename).suffix.lower()
        if file_ext in EXTENSION_TO_MIME and EXTENSION_TO_MIME[file_ext] == detected_mime:
            extension = file_ext

    return detected_mime, extension


def save_document_file(content: bytes, extension: str) -> str:
    """Save document file content to the uploads directory.

    Args:
        content: File content bytes
        extension: File extension (including dot)

    Returns:
        URL path to the uploaded file (e.g., /uploads/abc123.pdf)
    """
    safe_extension = extension if extension.startswith(".") else f".{extension}"
    filename = f"{uuid4().hex}{safe_extension}"

    upload_dir = _uploads_dir()
    destination = upload_dir / filename
    destination.write_bytes(content)

    return f"{UPLOADS_URL_PREFIX}{filename}"
