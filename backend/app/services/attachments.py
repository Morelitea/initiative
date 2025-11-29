from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Set
from urllib.parse import urlparse
from uuid import uuid4

from app.core.config import settings

logger = logging.getLogger(__name__)

UPLOADS_URL_PREFIX = "/uploads/"


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
