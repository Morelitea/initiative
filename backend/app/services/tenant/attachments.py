from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Set, Tuple
from urllib.parse import urlparse
from uuid import uuid4

from fastapi import UploadFile

from app.core.image_headers import read_image_header
from app.services.storage import get_guild_storage

logger = logging.getLogger(__name__)

UPLOADS_URL_PREFIX = "/uploads/"

#: What the stored name of a picture pasted into markdown — a task's
#: description, a comment — starts with. The server chooses every stored name,
#: so this is how an upload says it was pasted, and only an upload that says so
#: is ever deleted because the text stopped showing it. An image copied in from
#: a document or a gallery keeps its own name and is never touched.
PASTED_IMAGE_PREFIX = "pasted-"

#: An upload's address inside markdown: ``/uploads/{guild_id}/{filename}``,
#: optionally behind an origin.
_MARKDOWN_UPLOAD_URL = re.compile(r"(?:https?://[^\s()<>]+?)?/uploads/\d+/[\w.-]+")

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


def compute_content_hash(data: bytes) -> str:
    """SHA-256 hex of blob bytes — recorded on the ``uploads`` row for integrity
    verification (object-store migration) and future content dedup."""
    return hashlib.sha256(data).hexdigest()


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


def delete_blobs(guild_id: int, filenames: Iterable[str]) -> None:
    """Remove these stored files from the guild's storage.

    Call it with the names a release or purge returned, after the commit that
    removed their ``uploads`` rows, so a rolled-back write leaves the file.
    """
    storage = get_guild_storage(guild_id)
    for name in set(filenames):
        storage.delete(name)


def upload_names(urls: Iterable[str | None]) -> Set[str]:
    """The stored names these URLs address."""
    return {Path(n).name for n in (normalize_upload_url(u) for u in urls) if n}


async def purge_document_uploads(session, documents: Iterable[Any]) -> Set[str]:
    """Delete the uploads of documents about to be hard-purged.

    A file document's file, and every version of it, backs that document alone,
    so they go with it. What a document shows — pictures in its body, its
    featured image — goes only when nothing that stays shows it too; a trashed
    document still counts, since it may be restored.

    Caller must use a session that can DELETE from ``uploads``; caller commits,
    then deletes the blobs of the stored names returned.
    """
    from sqlmodel import select

    from app.models.tenant.document import Document, DocumentFileVersion, DocumentType

    doomed = list(documents)
    if not doomed:
        return set()
    doomed_ids = {d.id for d in doomed}

    versions = await session.exec(
        select(DocumentFileVersion.file_url).where(
            DocumentFileVersion.document_id.in_(doomed_ids)
        )
    )
    stored = upload_names(
        [d.file_url for d in doomed if d.document_type == DocumentType.file]
    ) | upload_names(versions.all())
    removed = await _drop_upload_rows(session, stored)

    shown: Set[str] = set()
    for d in doomed:
        shown |= extract_upload_urls(d.content)
        if d.featured_image_url:
            shown.add(d.featured_image_url)
    return removed | await release_uploads(
        session, shown, leaving={Document: doomed_ids}
    )


async def purge_gallery_image_uploads(session, images: Iterable[Any]) -> Set[str]:
    """Delete Upload rows + blobs for pictures about to be hard-purged.

    A picture's blobs back exactly one picture by construction — the file and
    the thumbnail of every version — so there is no orphan check to run: the
    version rows go with the picture (FK cascade), and this takes their
    ``Upload`` rows and the bytes behind them.

    Caller must use a session that can DELETE from ``uploads``; caller commits,
    then deletes the blobs of the stored names returned.
    """
    from sqlmodel import select

    from app.models.tenant.gallery import GalleryImageVersion

    doomed = list(images)
    if not doomed:
        return set()
    versions = await session.exec(
        select(GalleryImageVersion.file_url, GalleryImageVersion.thumbnail_url).where(
            GalleryImageVersion.gallery_image_id.in_({i.id for i in doomed})
        )
    )
    urls = [u for image in doomed for u in (image.file_url, image.thumbnail_url)]
    urls += [u for row in versions.all() for u in row]
    return await _drop_upload_rows(session, upload_names(urls))


def upload_urls_in_markdown(text: str | None) -> Set[str]:
    """Every upload a markdown body shows, normalized."""
    urls: Set[str] = set()
    for match in _MARKDOWN_UPLOAD_URL.findall(text or ""):
        normalized = normalize_upload_url(match)
        if normalized:
            urls.add(normalized)
    return urls


def _is_pasted(url: str) -> bool:
    return Path(url).name.startswith(PASTED_IMAGE_PREFIX)


#: How long a pasted picture waits to be saved before the sweep takes it. The
#: page that pasted it discards it as soon as it is left without saving; this
#: is for the tab that was closed instead, and is long enough that a draft left
#: open overnight still saves with its pictures.
UNCLAIMED_PASTED_IMAGE_GRACE = timedelta(hours=24)


def _upload_columns() -> tuple[tuple[type, str], ...]:
    """Every column a stored upload can be shown from: every column somebody
    writes in, and the file columns of documents and pictures."""
    from app.db.search_index import written_columns
    from app.models.tenant.document import Document, DocumentFileVersion
    from app.models.tenant.gallery import GalleryImage, GalleryImageVersion

    return (
        *(
            (model, column)
            for model, columns in written_columns().items()
            for column in columns
        ),
        (Document, "featured_image_url"),
        (Document, "file_url"),
        (DocumentFileVersion, "file_url"),
        (GalleryImage, "file_url"),
        (GalleryImage, "thumbnail_url"),
        (GalleryImageVersion, "file_url"),
        (GalleryImageVersion, "thumbnail_url"),
    )


#: The rows a caller is taking the pictures OUT of — they no longer count as
#: showing anything. Keyed by model.
Leaving = Mapping[type, Iterable[int]]


async def _still_shown(session, filename: str, *, leaving: Leaving) -> bool:
    """Whether anything stored — archived or in the trash included — other than
    the rows ``leaving`` shows this stored file."""
    from sqlalchemy import Text, cast

    from app.db.soft_delete_filter import select_including_deleted

    # LIKE wildcards in the name are escaped: a filename carries ``_``. The
    # name alone is matched — every stored name is unique — so an address
    # written with or without an origin is found either way.
    safe = filename.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    for model, column in _upload_columns():
        stmt = select_including_deleted(model.id).where(  # type: ignore[attr-defined]
            cast(getattr(model, column), Text).like(f"%{safe}%", escape="\\")
        )
        ids = set(leaving.get(model, ()))
        if ids:
            stmt = stmt.where(~model.id.in_(ids))  # type: ignore[attr-defined]
        if (await session.exec(stmt.limit(1))).first() is not None:
            return True
    return False


async def _drop_upload_rows(session, filenames: Set[str]) -> Set[str]:
    """Delete these ``uploads`` rows of the routed guild; returns the names
    that had one."""
    from sqlalchemy import delete as sa_delete

    from app.models.tenant.upload import Upload

    if not filenames:
        return set()
    result = await session.exec(
        sa_delete(Upload)
        .where(Upload.filename.in_(filenames))  # type: ignore[attr-defined]
        .returning(Upload.filename)
    )
    return set(result.scalars().all())


async def release_uploads(
    session, urls: Iterable[str | None], *, leaving: Leaving = {}
) -> Set[str]:
    """Delete the ``uploads`` rows of the files these URLs name that nothing
    stored shows any more.

    ``urls`` are what an edit took out, or what rows about to be purged (the
    ones in ``leaving``) show. A file goes only when no other row, archived or
    in the trash included, still shows it: a duplicated task shares its
    original's pictures, and a picture can be pasted from one body into another.

    Returns the stored names released, whose blobs the caller deletes with
    :func:`delete_blobs` once the rows are gone — after its commit, so a
    rolled-back write leaves the file.
    """
    names = {
        name
        for name in upload_names(urls)
        if not await _still_shown(session, name, leaving=leaving)
    }
    return await _drop_upload_rows(session, names)


async def release_pasted_images(
    session, urls: Iterable[str], *, leaving: Leaving
) -> Set[str]:
    """:func:`release_uploads`, for the pictures pasted into a task description
    or a comment (see :data:`PASTED_IMAGE_PREFIX`) — the only uploads a markdown
    body owns."""
    return await release_uploads(
        session, [u for u in urls if _is_pasted(u)], leaving=leaving
    )


async def discard_pasted_image(session, filename: str, *, user_id: int) -> str | None:
    """Delete a picture its uploader pasted and then did not save.

    Only a pasted picture (see :data:`PASTED_IMAGE_PREFIX`), only one the
    asking person uploaded, and only while nothing saved shows it — so a page
    discarding what it pasted cannot take a picture that did get saved, or
    anybody else's. Returns the stored name when it was deleted, for the caller
    to remove the blob after its commit; ``None`` when it stays.
    """
    from sqlmodel import select

    from app.models.tenant.upload import Upload

    name = Path(filename).name
    if name != filename or not name.startswith(PASTED_IMAGE_PREFIX):
        return None
    upload = (
        await session.exec(
            select(Upload).where(Upload.filename == name, Upload.created_by == user_id)
        )
    ).first()
    if upload is None or await _still_shown(session, name, leaving={}):
        return None
    await _drop_upload_rows(session, {name})
    return name


async def release_unclaimed_pasted_images(session, *, now: datetime) -> Set[str]:
    """Delete pictures pasted longer ago than the grace period that nothing
    shows — the ones a closed tab never got to discard.

    Runs in one routed guild with authority to delete uploads (the trash
    sweep). Returns the stored names released; the caller commits and then
    removes the blobs.
    """
    from sqlmodel import select

    from app.models.tenant.upload import Upload

    rows = await session.exec(
        select(Upload.filename)
        .where(Upload.filename.startswith(PASTED_IMAGE_PREFIX))  # type: ignore[attr-defined]
        .where(Upload.created_at < now - UNCLAIMED_PASTED_IMAGE_GRACE)
    )
    return await _drop_upload_rows(
        session,
        {
            name
            for name in rows.all()
            if not await _still_shown(session, name, leaving={})
        },
    )


async def purge_pasted_images(session, doomed: Iterable[Any]) -> Set[str]:
    """Delete the pictures pasted into tasks and comments about to be
    hard-purged, unless something that stays still shows them.

    Caller must use a session that can DELETE from ``uploads``; caller commits,
    then deletes the blobs of the stored names returned.
    """
    from app.models.tenant.comment import Comment
    from app.models.tenant.task import Task

    urls: Set[str] = set()
    leaving: dict[type, set[int]] = {Task: set(), Comment: set()}
    for row in doomed:
        if isinstance(row, Task):
            urls |= upload_urls_in_markdown(row.description)
            leaving[Task].add(row.id)
        elif isinstance(row, Comment):
            urls |= upload_urls_in_markdown(row.content)
            leaving[Comment].add(row.id)
    return await release_pasted_images(session, urls, leaving=leaving)


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


async def copy_uploads(
    session, urls: Iterable[str | None], *, guild_id: int, created_by: int
) -> Dict[str, str]:
    """Copy the guild's stored files these URLs name into new files, recorded
    like any other upload, and return each source URL's copy.

    Only files this guild stores are copied — anything else stays as it was
    written. The copies count against the storage quota, checked for all of
    them before a byte is written. Caller commits.
    """
    from sqlmodel import select

    from app.models.tenant.upload import Upload

    by_name = {Path(u).name: u for u in (normalize_upload_url(u) for u in urls) if u}
    if not by_name:
        return {}
    sources = (
        await session.exec(select(Upload).where(Upload.filename.in_(by_name)))  # type: ignore[attr-defined]
    ).all()
    if not sources:
        return {}
    await enforce_storage_quota(
        session,
        guild_id=guild_id,
        incoming_bytes=sum(source.size_bytes or 0 for source in sources),
    )
    storage = get_guild_storage(guild_id)
    copies: Dict[str, str] = {}
    for source in sources:
        name = new_upload_filename(
            Path(source.filename).suffix,
            prefix=PASTED_IMAGE_PREFIX if _is_pasted(source.filename) else "",
        )
        if not await asyncio.to_thread(storage.copy, source.filename, name):
            logger.error("Failed to copy upload %s -> %s", source.filename, name)
            continue
        session.add(
            Upload(
                filename=name,
                created_by=created_by,
                size_bytes=source.size_bytes,
                content_type=source.content_type,
                content_hash=source.content_hash,
            )
        )
        copies[by_name[source.filename]] = f"{UPLOADS_URL_PREFIX}{guild_id}/{name}"
    return copies


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


def new_upload_filename(extension: str, *, prefix: str = "") -> str:
    """A fresh stored name: ``prefix``, a random hex id, then ``extension``
    (with or without its dot; empty for none)."""
    if extension and not extension.startswith("."):
        extension = f".{extension}"
    return f"{prefix}{uuid4().hex}{extension}"


async def store_upload(
    session,
    *,
    guild_id: int,
    filename: str,
    data: bytes,
    content_type: str | None,
    created_by: int,
) -> str:
    """Write ``data`` to the guild's storage as ``filename`` and record it in
    ``uploads``. Returns the served URL, ``/uploads/{guild_id}/{filename}``.

    Every upload a person or an import brings into a guild is stored here.
    The ``uploads`` row is what the serve route requires and what the storage
    quota is summed from; the caller owns naming, validation, the quota check
    and the commit.
    """
    from app.models.tenant.upload import Upload

    await asyncio.to_thread(
        get_guild_storage(guild_id).write,
        filename,
        data,
        content_type=content_type or "application/octet-stream",
    )
    session.add(
        Upload(
            filename=filename,
            created_by=created_by,
            size_bytes=len(data),
            content_type=content_type,
            content_hash=compute_content_hash(data),
        )
    )
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


# Advisory-lock namespace for per-guild storage-quota admission. A large fixed
# tag (ASCII "STOR") so the two-int key (namespace, guild_id) can't collide with
# the (user_id, guild_id) advisory locks used elsewhere (user ids are small).
_QUOTA_LOCK_NAMESPACE = 0x53544F52  # 1397114706


async def storage_left(session, *, guild_id: int) -> int | None:
    """What the guild's ``max_storage_bytes`` still allows, or ``None`` when it
    has no limit. A reading for planning, not a reservation: the write that
    follows still goes through :func:`enforce_storage_quota`. Runs under the
    guild-routed RLS session, like the usage it reads."""
    from sqlmodel import select

    from app.models.platform.guild_administration import GuildAdministration

    limit = (
        await session.exec(
            select(GuildAdministration.max_storage_bytes).where(
                GuildAdministration.guild_id == guild_id
            )
        )
    ).one_or_none()
    if limit is None:
        return None
    return max(0, limit - await get_guild_storage_usage(session))


async def enforce_storage_quota(session, *, guild_id: int, incoming_bytes: int) -> None:
    """Reject an upload that would exceed the guild's ``max_storage_bytes``.

    NULL / absent limit means unlimited (the default), so this is a no-op until a
    quota is set on the guild. The limit lives on the shared
    ``guild_administration`` row (read-only to every request-path role); the
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

    from app.models.platform.guild_administration import GuildAdministration

    limit = (
        await session.exec(
            select(GuildAdministration.max_storage_bytes).where(
                GuildAdministration.guild_id == guild_id
            )
        )
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


#: How far into a file the SVG root element may sit — past a byte-order mark, an
#: XML declaration, comments and a doctype. Generous for an editor's preamble,
#: bounded so the check stays a slice of the head rather than a scan of 10 MB.
_SVG_HEAD_BYTES = 1024

#: What may follow the root element's name: whitespace before an attribute, or
#: the end of an empty or opening tag. Anything else is a different element
#: whose name happens to start with the same three letters.
_ROOT_NAME_ENDS = (b" ", b"\t", b"\r", b"\n", b">", b"/")


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


def detect_document_image_type(contents: bytes) -> str | None:
    """Identify a document image from its bytes, or ``None`` if it is not one.

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
