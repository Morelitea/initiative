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
        raise ValueError(f"Unsupported file type: {detected_mime}")

    # If we couldn't detect the MIME type, fall back to Content-Type header
    if not detected_mime:
        if content_type and content_type in ALLOWED_DOCUMENT_MIME_TYPES:
            detected_mime = content_type
        else:
            raise ValueError("Unable to determine file type. Supported types: PDF, Word, Excel, PowerPoint, TXT, HTML")

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
