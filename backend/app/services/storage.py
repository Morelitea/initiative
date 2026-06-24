"""Pluggable blob storage backend.

Storage rebuild (see ``history/blob-storage-tenancy-design.md``): a single seam
over blob I/O so the local filesystem (FOSS / self-host / dev) and an
S3-compatible object store (cloud, or self-hosted MinIO) become interchangeable
behind one config flag — ``STORAGE_BACKEND=local|s3``.

The backend is *dumb about tenancy*: it operates on opaque object keys (today,
the stored filename — a UUID-hex basename). Tenancy is owned by the **resolver**
(:func:`get_guild_storage`), the storage twin of ``set_rls_context``: it hands
back a backend whose keys are namespaced to the guild (``guild_<id>/`` for S3 —
the object-store expression of the schema-per-guild boundary, and what the
per-request IAM prefix scopes to; design §6). Callers still pass the flat
filename and own the ``/uploads/{guild_id}/{filename}`` URL scheme.

Phases delivered here:
- ``LocalFilesystemStorage`` — today's behavior verbatim (flat ``UPLOADS_DIR``).
- ``S3Storage`` — boto3 against any S3-compatible endpoint; serves via streaming
  proxy (:func:`build_upload_response`) and can presign for opt-in offload.

``STORAGE_BACKEND`` defaults to ``local``; the S3 path is dormant until a bucket
is configured.
"""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Iterator, Protocol, runtime_checkable

from fastapi.responses import FileResponse, Response, StreamingResponse

from app.core.config import settings

if TYPE_CHECKING:  # botocore imported lazily at call time; type-only here
    from botocore.client import BaseClient

logger = logging.getLogger(__name__)

# Streaming proxy chunk size for S3 GetObject bodies.
_STREAM_CHUNK = 64 * 1024

# S3 error codes that mean "object/bucket not here" rather than a real failure.
_S3_MISSING_CODES = {"404", "NoSuchKey", "NoSuchBucket", "NotFound"}


@dataclass
class ReadableBlob:
    """A served blob, backend-agnostic.

    Local sets ``path`` (so the serve adapter keeps ``FileResponse`` sendfile +
    range support). S3 sets ``stream`` plus whatever metadata ``GetObject``
    returned (``content_type`` / ``content_length``).
    """

    path: Path | None = None
    stream: Iterator[bytes] | None = None
    content_type: str | None = None
    content_length: int | None = None


@runtime_checkable
class StorageBackend(Protocol):
    """Object-store contract. ``key`` is an opaque object name (a flat filename);
    the resolver applies any tenant prefix before the backend sees it."""

    def write(
        self, key: str, data: bytes, *, content_type: str | None = None
    ) -> None: ...

    def delete(self, key: str) -> bool: ...

    def copy(self, src_key: str, dst_key: str) -> bool: ...

    def exists(self, key: str) -> bool: ...

    def open_readable(self, key: str) -> ReadableBlob | None: ...

    def presign_get(
        self, key: str, *, ttl: int, filename: str | None = None
    ) -> str | None: ...


class LocalFilesystemStorage:
    """Stores objects as flat files under ``UPLOADS_DIR``.

    ``key`` is the stored filename. Keys are reduced to a basename before they
    touch the filesystem, so a key can never escape the base directory — this
    centralizes the path-traversal guard the two serve endpoints previously
    duplicated. The base dir is created on demand.

    The guild prefix the resolver carries for S3 is intentionally ignored here:
    the local layout stays flat (the guild rides in the URL), so existing
    self-host installs keep working byte-for-byte across the upgrade.
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

    def write(self, key: str, data: bytes, *, content_type: str | None = None) -> None:
        # content_type is meaningless on a filesystem (inferred at serve time);
        # accepted for protocol parity with S3 and ignored.
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
        """Filesystem path for a key, or None. Retained for local-only callers."""
        target = self._safe_path(key)
        if target is None or not target.is_file():
            return None
        return target

    def open_readable(self, key: str) -> ReadableBlob | None:
        target = self.resolve_readable(key)
        return ReadableBlob(path=target) if target is not None else None

    def presign_get(
        self, key: str, *, ttl: int, filename: str | None = None
    ) -> str | None:
        # A filesystem has no signed URLs; local content is always proxy-served.
        return None


class S3Storage:
    """S3-compatible object store (AWS S3, MinIO, R2, …) via boto3.

    Dumb about tenancy: it reads/writes keys within the ``(bucket, client,
    prefix)`` the resolver handed it. ``prefix`` is the guild namespace
    (``guild_<id>/``); the resolver owns it. Keys are reduced to a basename
    before the prefix is applied, mirroring the local traversal guard.
    """

    def __init__(
        self,
        *,
        bucket: str,
        client: "BaseClient",
        prefix: str = "",
        kms_key_id: str | None = None,
    ) -> None:
        self._bucket = bucket
        self._client = client
        self._prefix = prefix
        self._kms_key_id = kms_key_id

    def _object_key(self, key: str) -> str:
        name = Path(key).name
        if not name:
            raise ValueError(f"Invalid storage key: {key!r}")
        return f"{self._prefix}{name}"

    def _sse_params(self) -> dict[str, str]:
        if self._kms_key_id:
            return {"ServerSideEncryption": "aws:kms", "SSEKMSKeyId": self._kms_key_id}
        return {}

    def _head(self, object_key: str) -> bool:
        from botocore.exceptions import ClientError

        try:
            self._client.head_object(Bucket=self._bucket, Key=object_key)
            return True
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in _S3_MISSING_CODES:
                return False
            raise

    def write(self, key: str, data: bytes, *, content_type: str | None = None) -> None:
        extra = self._sse_params()
        if content_type:
            extra["ContentType"] = content_type
        self._client.put_object(
            Bucket=self._bucket, Key=self._object_key(key), Body=data, **extra
        )

    def delete(self, key: str) -> bool:
        object_key = self._object_key(key)
        # head first so the bool return matches local semantics (missing -> False);
        # delete_object itself is idempotent.
        if not self._head(object_key):
            return False
        self._client.delete_object(Bucket=self._bucket, Key=object_key)
        return True

    def copy(self, src_key: str, dst_key: str) -> bool:
        src = self._object_key(src_key)
        dst = self._object_key(dst_key)
        if not self._head(src):
            return False
        # Server-side copy — no bytes through the app (design §7 / tier migration).
        self._client.copy_object(
            Bucket=self._bucket,
            Key=dst,
            CopySource={"Bucket": self._bucket, "Key": src},
            **self._sse_params(),
        )
        return True

    def exists(self, key: str) -> bool:
        return self._head(self._object_key(key))

    def open_readable(self, key: str) -> ReadableBlob | None:
        from botocore.exceptions import ClientError

        try:
            obj = self._client.get_object(
                Bucket=self._bucket, Key=self._object_key(key)
            )
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in _S3_MISSING_CODES:
                return None
            raise
        return ReadableBlob(
            stream=obj["Body"].iter_chunks(chunk_size=_STREAM_CHUNK),
            content_type=obj.get("ContentType"),
            content_length=obj.get("ContentLength"),
        )

    def presign_get(
        self, key: str, *, ttl: int, filename: str | None = None
    ) -> str | None:
        params: dict[str, str] = {"Bucket": self._bucket, "Key": self._object_key(key)}
        if filename:
            params["ResponseContentDisposition"] = f'attachment; filename="{filename}"'
        return self._client.generate_presigned_url(
            "get_object", Params=params, ExpiresIn=ttl
        )


def build_upload_response(
    blob: ReadableBlob,
    *,
    headers: dict[str, str] | None = None,
    media_type: str | None = None,
    filename: str | None = None,
) -> Response:
    """Adapt a :class:`ReadableBlob` into a Starlette response.

    Local blobs become a ``FileResponse`` (sendfile + range, media type inferred
    from the path as before). S3 blobs stream via ``StreamingResponse`` using the
    content-type recorded on the object. ``filename`` forces an attachment
    download; otherwise the response is inline. The serve endpoints keep owning
    their security headers (CSP / nosniff / Content-Disposition) and pass them in.
    """
    headers = dict(headers or {})
    if blob.path is not None:
        if filename is not None:
            return FileResponse(
                blob.path,
                filename=filename,
                media_type=media_type or None,
                headers=headers,
            )
        return FileResponse(blob.path, media_type=media_type or None, headers=headers)

    media = media_type or blob.content_type or "application/octet-stream"
    if blob.content_length is not None and "Content-Length" not in headers:
        headers["Content-Length"] = str(blob.content_length)
    if filename is not None and "Content-Disposition" not in headers:
        headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    return StreamingResponse(blob.stream or iter(()), media_type=media, headers=headers)


_local_backend: LocalFilesystemStorage | None = None
_s3_client: "BaseClient | None" = None


def _backend_name() -> str:
    return (settings.STORAGE_BACKEND or "local").lower()


def _local() -> LocalFilesystemStorage:
    global _local_backend
    if _local_backend is None:
        _local_backend = LocalFilesystemStorage()
    return _local_backend


def _get_s3_client() -> "BaseClient":
    global _s3_client
    if _s3_client is None:
        import boto3
        from botocore.config import Config

        config_kwargs: dict = {"signature_version": "s3v4"}
        if settings.S3_USE_PATH_STYLE:
            # MinIO and most non-AWS stores require path-style addressing.
            config_kwargs["s3"] = {"addressing_style": "path"}

        client_kwargs: dict = {
            "region_name": settings.S3_REGION,
            "config": Config(**config_kwargs),
        }
        if settings.S3_ENDPOINT_URL:
            client_kwargs["endpoint_url"] = settings.S3_ENDPOINT_URL
        # Explicit keys for MinIO/dev; on AWS leave unset so the ambient chain
        # (IRSA / instance role / env) supplies credentials.
        if settings.S3_ACCESS_KEY_ID and settings.S3_SECRET_ACCESS_KEY:
            client_kwargs["aws_access_key_id"] = settings.S3_ACCESS_KEY_ID
            client_kwargs["aws_secret_access_key"] = settings.S3_SECRET_ACCESS_KEY

        _s3_client = boto3.client("s3", **client_kwargs)
    return _s3_client


def _require_bucket() -> str:
    if not settings.S3_BUCKET:
        raise ValueError("STORAGE_BACKEND='s3' requires S3_BUCKET to be set")
    return settings.S3_BUCKET


def _make(prefix: str) -> StorageBackend:
    name = _backend_name()
    if name == "local":
        return _local()
    if name == "s3":
        return S3Storage(
            bucket=_require_bucket(),
            client=_get_s3_client(),
            prefix=prefix,
            kms_key_id=settings.S3_KMS_KEY_ID,
        )
    raise ValueError(f"Unsupported STORAGE_BACKEND={name!r} (expected 'local' or 's3')")


def get_storage() -> StorageBackend:
    """Return the base (unscoped) backend, selected by ``STORAGE_BACKEND``.

    Use :func:`get_guild_storage` for guild content; this stays for the
    identity/public plane and back-compat.
    """
    return _make("")


def get_guild_storage(guild_id: int) -> StorageBackend:
    """Return a content-plane backend scoped to ``guild_id`` (the resolver).

    Local: flat ``UPLOADS_DIR`` (the guild rides in the URL; no behavior change).
    S3: keys are namespaced under ``guild_<id>/`` — the object-store twin of the
    schema-per-guild boundary, and exactly what the per-request IAM prefix scopes
    to (design §6). Pooled-cloud per-request STS downscope plugs in here; today
    the resolver uses the ambient credential (works for MinIO, siloed IRSA, dev).
    """
    return _make(f"guild_{int(guild_id)}/")
