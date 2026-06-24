"""Pluggable blob storage backend.

Phase 1 of the blob-storage rebuild (see
``history/blob-storage-tenancy-design.md``): introduce a single seam over file
I/O so the local filesystem (FOSS / self-host / dev) and a future S3 backend
(cloud) become interchangeable. This phase implements ``LocalFilesystemStorage``
only and preserves the existing flat ``UPLOADS_DIR/<filename>`` layout exactly —
no behavior change.

The backend is *dumb about tenancy*: it operates on opaque object keys (today,
the stored filename — a UUID-hex basename). Callers own guild/ownership routing
and the ``/uploads/{guild_id}/{filename}`` URL scheme. The S3 backend will slot
in behind :func:`get_storage` (per the design doc) without touching call sites;
its ``{guild_id}/{filename}`` keying and streaming/presigned serving are later
phases.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Protocol, runtime_checkable

from app.core.config import settings

logger = logging.getLogger(__name__)


@runtime_checkable
class StorageBackend(Protocol):
    """Object-store contract. ``key`` is an opaque object name.

    ``resolve_readable`` is filesystem-shaped on purpose for this phase (the two
    serve endpoints build a ``FileResponse`` from the returned path). The S3
    backend will instead expose streaming/presigned serving, and the serve
    endpoints will adapt at that point.
    """

    def write(self, key: str, data: bytes) -> None: ...

    def delete(self, key: str) -> bool: ...

    def copy(self, src_key: str, dst_key: str) -> bool: ...

    def exists(self, key: str) -> bool: ...

    def resolve_readable(self, key: str) -> Path | None: ...


class LocalFilesystemStorage:
    """Stores objects as flat files under ``UPLOADS_DIR``.

    ``key`` is the stored filename. Keys are reduced to a basename before they
    touch the filesystem, so a key can never escape the base directory — this
    centralizes the path-traversal guard the two serve endpoints previously
    duplicated. The base dir is created on demand (matching the prior
    ``_uploads_dir()`` / ``_ensure_upload_dir()`` behavior).
    """

    def __init__(self, base_dir: str | None = None) -> None:
        self._base_dir = base_dir

    def _dir(self) -> Path:
        path = Path(self._base_dir or settings.UPLOADS_DIR)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _safe_path(self, key: str) -> Path | None:
        name = Path(key).name
        if not name:
            return None
        base = self._dir()
        try:
            target = (base / name).resolve()
            target.relative_to(base.resolve())
        except ValueError:
            return None
        return target

    def write(self, key: str, data: bytes) -> None:
        target = self._safe_path(key)
        if target is None:
            raise ValueError(f"Invalid storage key: {key!r}")
        target.write_bytes(data)

    def delete(self, key: str) -> bool:
        target = self._safe_path(key)
        if target is None:
            return False
        try:
            if target.exists() and target.is_file():
                target.unlink()
                return True
        except OSError as exc:
            logger.warning("Failed to delete blob %s: %s", target, exc)
        return False

    def copy(self, src_key: str, dst_key: str) -> bool:
        src = self._safe_path(src_key)
        dst = self._safe_path(dst_key)
        if src is None or dst is None or not src.exists():
            return False
        try:
            shutil.copy2(src, dst)
            return True
        except OSError as exc:
            logger.error("Failed to copy blob %s -> %s: %s", src, dst, exc)
            return False

    def exists(self, key: str) -> bool:
        target = self._safe_path(key)
        return bool(target and target.is_file())

    def resolve_readable(self, key: str) -> Path | None:
        target = self._safe_path(key)
        if target is None or not target.is_file():
            return None
        return target


_backend: StorageBackend | None = None


def get_storage() -> StorageBackend:
    """Return the process-wide storage backend, selected by ``STORAGE_BACKEND``.

    Only ``local`` is implemented in this phase; the S3 backend slots in here
    (per the design doc) without touching call sites.
    """
    global _backend
    if _backend is None:
        _backend = _build_storage(settings.STORAGE_BACKEND)
    return _backend


def _build_storage(backend_name: str | None) -> StorageBackend:
    name = (backend_name or "local").lower()
    if name == "local":
        return LocalFilesystemStorage()
    raise ValueError(
        f"Unsupported STORAGE_BACKEND={name!r} (only 'local' is implemented "
        "in this phase)"
    )
