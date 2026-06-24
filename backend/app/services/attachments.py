from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Set, Tuple
from urllib.parse import urlparse
from uuid import uuid4

from fastapi import UploadFile

from app.core.config import settings
from app.services.storage import get_storage

logger = logging.getLogger(__name__)

UPLOADS_URL_PREFIX = "/uploads/"

# Maximum file size for document uploads: 50 MB
MAX_DOCUMENT_FILE_SIZE = 50 * 1024 * 1024


class FileTooLargeError(Exception):
    """Raised when an uploaded file exceeds the allowed byte limit.

    Carries the limit so callers can build an accurate error response without
    re-deriving it.
    """

    def __init__(self, max_size: int) -> None:
        self.max_size = max_size
        super().__init__(f"File exceeds maximum size of {max_size} bytes")


class StorageQuotaExceededError(Exception):
    """Raised when an upload would push a guild over its ``max_storage_bytes``.

    Carries the limit, the current usage, and the incoming size so callers can
    build an accurate error response.
    """

    def __init__(self, *, limit: int, usage: int, incoming: int) -> None:
        self.limit = limit
        self.usage = usage
        self.incoming = incoming
        super().__init__(
            f"Upload of {incoming} bytes would exceed the guild storage limit "
            f"of {limit} bytes (current usage {usage})"
        )


async def read_upload_bounded(file: UploadFile, max_size: int) -> bytes:
    """Read an upload without buffering more than ``max_size`` bytes.

    Reads ``max_size + 1`` bytes so an over-limit body is detected from the
    single extra byte instead of materializing the whole payload in memory
    (which would let a large upload exhaust process memory). Returns the file
    bytes when within the limit; raises :class:`FileTooLargeError` otherwise.
    """
    contents = await file.read(max_size + 1)
    if len(contents) > max_size:
        raise FileTooLargeError(max_size)
    return contents


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
    # Keep the full ``/uploads/{guild_id}/{filename}`` path (only origin/query are
    # dropped): the guild segment is part of the canonical URL, so content
    # rewrites and dedup compare like-for-like. Disk ops take ``Path(url).name``,
    # which is the filename regardless of the guild segment.
    if not Path(path).name:
        return None
    return path


def delete_upload_by_url(url: str | None) -> None:
    normalized = normalize_upload_url(url)
    if not normalized:
        return
    get_storage().delete(Path(normalized).name)


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
    from sqlmodel import select

    from app.db.soft_delete_filter import select_including_deleted
    from app.models.tenant.document import Document, DocumentFileVersion, DocumentType
    from app.models.tenant.upload import Upload

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

    # Historical version blobs for the doomed file docs (the documents row
    # only mirrors the current version; older versions live in
    # document_file_versions). The version rows themselves cascade-delete with
    # the document; here we clean up their Upload rows + blobs.
    version_rows = await session.exec(
        select(DocumentFileVersion.file_url).where(
            DocumentFileVersion.document_id.in_(doomed_ids)
        )
    )
    for version_url in version_rows.all():
        if not version_url:
            continue
        file_urls_to_unlink.add(version_url)
        normalized = normalize_upload_url(version_url)
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

    storage = get_storage()
    source_name = Path(normalized).name
    if not storage.exists(source_name):
        logger.warning("Attempted to duplicate missing upload %s", source_name)
        return normalized

    extension = Path(source_name).suffix
    for _ in range(10):
        new_name = f"{uuid4().hex}{extension}"
        if storage.exists(new_name):
            continue
        if storage.copy(source_name, new_name):
            # Keep the source URL's ``/uploads/{guild_id}`` prefix — a duplicate
            # stays in the same guild — and swap only the filename segment.
            return f"{normalized.rsplit('/', 1)[0]}/{new_name}"
        logger.error("Failed to duplicate upload %s -> %s", source_name, new_name)
        return normalized
    logger.error(
        "Unable to allocate new filename for duplicated upload %s", source_name
    )
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
        raise ValueError(
            f"File exceeds maximum size of {MAX_DOCUMENT_FILE_SIZE // (1024 * 1024)} MB"
        )

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
            raise ValueError(
                "Unable to determine file type. Supported types: PDF, Word, Excel, PowerPoint, TXT, HTML, images, Markdown"
            )

    # Get extension for the detected MIME type
    extension = ALLOWED_DOCUMENT_MIME_TYPES.get(detected_mime, "")

    # If we have a filename, prefer its extension if it matches
    if filename:
        file_ext = Path(filename).suffix.lower()
        if (
            file_ext in EXTENSION_TO_MIME
            and EXTENSION_TO_MIME[file_ext] == detected_mime
        ):
            extension = file_ext

    return detected_mime, extension


def save_document_file(content: bytes, extension: str, guild_id: int) -> str:
    """Save document file content to the uploads directory.

    Args:
        content: File content bytes
        extension: File extension (including dot)
        guild_id: Guild the file belongs to — encoded into the URL path so the
            served media self-describes its guild (e.g. /uploads/7/abc123.pdf).

    Returns:
        URL path to the uploaded file (e.g., /uploads/7/abc123.pdf)
    """
    safe_extension = extension if extension.startswith(".") else f".{extension}"
    filename = f"{uuid4().hex}{safe_extension}"

    get_storage().write(filename, content)

    return f"{UPLOADS_URL_PREFIX}{guild_id}/{filename}"


async def get_guild_storage_usage(session) -> int:
    """Total stored blob bytes for the active guild — ``SUM(uploads.size_bytes)``.

    Runs under the guild-routed RLS session, so the sum is scoped to the active
    guild's schema.
    """
    from sqlalchemy import func
    from sqlmodel import select

    from app.models.tenant.upload import Upload

    return (
        await session.exec(select(func.coalesce(func.sum(Upload.size_bytes), 0)))
    ).one()


async def get_upload_bytes_for_urls(session, urls: Iterable[str]) -> int:
    """Total stored size of the uploads referenced by ``urls`` (matched by
    filename) — ``SUM(uploads.size_bytes)`` over those rows.

    Used to size a clone's incoming bytes before any blob is copied: a copy is the
    same size as its source, so this is the storage a duplicate will add. Runs
    under the guild-routed RLS session. Legacy blobs without an ``uploads`` row
    contribute 0.
    """
    from sqlalchemy import func
    from sqlmodel import select

    from app.models.tenant.upload import Upload

    filenames = {
        Path(normalized).name
        for url in urls
        if (normalized := normalize_upload_url(url))
    }
    if not filenames:
        return 0
    return (
        await session.exec(
            select(func.coalesce(func.sum(Upload.size_bytes), 0)).where(
                Upload.filename.in_(filenames)
            )
        )
    ).one()


# Advisory-lock namespace for per-guild storage-quota admission. A large fixed
# tag (ASCII "STOR") so the two-int key (namespace, guild_id) can't collide with
# the (user_id, guild_id) advisory locks used elsewhere (user ids are small).
_QUOTA_LOCK_NAMESPACE = 0x53544F52  # 1397114706


async def enforce_storage_quota(session, *, guild_id: int, incoming_bytes: int) -> None:
    """Reject an upload that would exceed the guild's ``max_storage_bytes``.

    NULL / absent limit means unlimited (the default), so this is a no-op until a
    quota is set on the guild. The limit lives on the shared ``guilds`` row; the
    usage (``SUM(uploads.size_bytes)``) is read from the active guild's schema, so
    this must run under the guild-routed RLS session.

    Must be called within the SAME transaction that then inserts the ``uploads``
    row and commits. When a limit is set, it takes a transaction-scoped advisory
    lock keyed on the guild before reading usage, so the check and the insert that
    follows cannot interleave with a concurrent upload — without it, two uploads
    to a near-full guild could each read the pre-upload usage and collectively
    exceed the limit (a TOCTOU race). The lock releases on commit/rollback;
    uploads to other guilds are unaffected.
    """
    from sqlalchemy import text
    from sqlmodel import select

    from app.models.platform.guild import Guild

    limit = (
        await session.exec(select(Guild.max_storage_bytes).where(Guild.id == guild_id))
    ).one_or_none()
    if limit is None:
        return
    # Serialize concurrent uploads for this guild for the remainder of the
    # transaction so the usage check + the row insert that follows are atomic
    # w.r.t. other uploads to the same guild.
    await session.exec(
        text("SELECT pg_advisory_xact_lock(:ns, :gid)"),
        params={"ns": _QUOTA_LOCK_NAMESPACE, "gid": int(guild_id)},
    )
    usage = await get_guild_storage_usage(session)
    if usage + incoming_bytes > limit:
        raise StorageQuotaExceededError(
            limit=limit, usage=usage, incoming=incoming_bytes
        )
