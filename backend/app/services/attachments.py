from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Iterable, Set
from urllib.parse import urlparse

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
