"""Unit tests for the storage backends (storage rebuild).

The local-backend tests are pure filesystem (no DB). The S3 tests drive
``S3Storage`` against an in-memory fake boto3 client — deterministic, no network
or object store needed — verifying the guild-prefix keying, the basename guard,
SSE params, and the serve adapter. Integration against a real S3-compatible
endpoint (e.g. a Garage instance) is left to manual/CI runs.
"""

import pytest
from botocore.exceptions import ClientError
from fastapi.responses import FileResponse, StreamingResponse

from app.services import storage as storage_module
from app.services.storage import (
    DualReadStorage,
    LocalFilesystemStorage,
    ReadableBlob,
    S3Storage,
    StorageBackend,
    build_upload_response,
    get_guild_storage,
    get_storage,
)


def test_write_read_roundtrip(tmp_path):
    storage = LocalFilesystemStorage(base_dir=str(tmp_path))
    storage.write("abc.txt", b"hello")
    resolved = storage.resolve_readable("abc.txt")
    assert resolved is not None
    assert resolved.read_bytes() == b"hello"
    assert storage.exists("abc.txt") is True


def test_delete(tmp_path):
    storage = LocalFilesystemStorage(base_dir=str(tmp_path))
    storage.write("x.bin", b"data")
    assert storage.delete("x.bin") is True
    assert storage.exists("x.bin") is False
    # Deleting a missing key is a no-op, reported as False.
    assert storage.delete("x.bin") is False


def test_copy(tmp_path):
    storage = LocalFilesystemStorage(base_dir=str(tmp_path))
    storage.write("src.bin", b"payload")
    assert storage.copy("src.bin", "dst.bin") is True
    resolved = storage.resolve_readable("dst.bin")
    assert resolved is not None and resolved.read_bytes() == b"payload"
    # Copying a missing source fails cleanly.
    assert storage.copy("missing.bin", "dst2.bin") is False


def test_resolve_missing_returns_none(tmp_path):
    storage = LocalFilesystemStorage(base_dir=str(tmp_path))
    assert storage.resolve_readable("nope.txt") is None


def test_path_traversal_is_contained(tmp_path):
    base = tmp_path / "uploads"
    storage = LocalFilesystemStorage(base_dir=str(base))
    # A sentinel that lives OUTSIDE the base dir must stay unreachable.
    outside = tmp_path / "secret.txt"
    outside.write_bytes(b"secret")
    # Keys are reduced to a basename, so a traversal attempt can never escape.
    assert storage.resolve_readable("../secret.txt") is None
    assert storage.exists("../secret.txt") is False


def test_empty_key_is_rejected(tmp_path):
    storage = LocalFilesystemStorage(base_dir=str(tmp_path))
    with pytest.raises(ValueError):
        storage.write("", b"data")
    assert storage.resolve_readable("") is None


def test_get_storage_returns_local_singleton():
    backend = get_storage()
    assert isinstance(backend, StorageBackend)
    # Process-wide singleton.
    assert get_storage() is backend


# --- S3Storage (in-memory fake boto3 client) ---------------------------------


class _FakeBody:
    """Mimics the boto3 StreamingBody.iter_chunks() interface."""

    def __init__(self, data: bytes) -> None:
        self._data = data

    def iter_chunks(self, chunk_size: int = 65536):
        for i in range(0, len(self._data), chunk_size):
            yield self._data[i : i + chunk_size]


class FakeS3Client:
    """Minimal in-memory stand-in for a boto3 S3 client."""

    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], dict] = {}
        self.presigned: list[tuple] = []
        # Keys delete_objects should report as failed (not actually removed).
        self.delete_errors: set[str] = set()

    @staticmethod
    def _missing(op: str) -> ClientError:
        return ClientError({"Error": {"Code": "404", "Message": "Not Found"}}, op)

    def put_object(self, *, Bucket, Key, Body, **extra):
        self.objects[(Bucket, Key)] = {"Body": Body, "extra": extra}
        return {}

    def head_object(self, *, Bucket, Key):
        if (Bucket, Key) not in self.objects:
            raise self._missing("HeadObject")
        return {}

    def delete_object(self, *, Bucket, Key):
        self.objects.pop((Bucket, Key), None)
        return {}

    def copy_object(self, *, Bucket, Key, CopySource, **extra):
        src = (CopySource["Bucket"], CopySource["Key"])
        if src not in self.objects:
            raise self._missing("CopyObject")
        self.objects[(Bucket, Key)] = {
            "Body": self.objects[src]["Body"],
            "extra": extra,
        }
        return {}

    def get_object(self, *, Bucket, Key):
        if (Bucket, Key) not in self.objects:
            raise self._missing("GetObject")
        rec = self.objects[(Bucket, Key)]
        body = rec["Body"]
        return {
            "Body": _FakeBody(body),
            "ContentType": rec["extra"].get("ContentType"),
            "ContentLength": len(body),
        }

    def generate_presigned_url(self, op, *, Params, ExpiresIn):
        self.presigned.append((op, Params, ExpiresIn))
        disp = Params.get("ResponseContentDisposition", "")
        return f"https://s3.test/{Params['Key']}?exp={ExpiresIn}&disp={disp}"

    def list_objects_v2(self, *, Bucket, Prefix, ContinuationToken=None):
        keys = [k for (b, k) in self.objects if b == Bucket and k.startswith(Prefix)]
        return {"Contents": [{"Key": k} for k in keys], "IsTruncated": False}

    def delete_objects(self, *, Bucket, Delete):
        errors = []
        for obj in Delete["Objects"]:
            key = obj["Key"]
            if key in self.delete_errors:
                errors.append({"Key": key, "Code": "AccessDenied", "Message": "denied"})
                continue
            self.objects.pop((Bucket, key), None)
        return {"Errors": errors} if errors else {}


def _s3(prefix="guild_7/", kms_key_id=None):
    client = FakeS3Client()
    return client, S3Storage(
        bucket="bucket", client=client, prefix=prefix, kms_key_id=kms_key_id
    )


def test_s3_write_applies_guild_prefix_and_content_type():
    client, storage = _s3()
    storage.write("abc.png", b"img", content_type="image/png")
    # Keyed under the resolver-supplied guild prefix.
    assert ("bucket", "guild_7/abc.png") in client.objects
    assert client.objects[("bucket", "guild_7/abc.png")]["extra"]["ContentType"] == (
        "image/png"
    )
    # No KMS params unless configured.
    assert (
        "ServerSideEncryption"
        not in client.objects[("bucket", "guild_7/abc.png")]["extra"]
    )


def test_s3_write_adds_kms_sse_when_configured():
    client, storage = _s3(kms_key_id="arn:aws:kms:key/abc")
    storage.write("x.bin", b"data")
    extra = client.objects[("bucket", "guild_7/x.bin")]["extra"]
    assert extra["ServerSideEncryption"] == "aws:kms"
    assert extra["SSEKMSKeyId"] == "arn:aws:kms:key/abc"


def test_s3_key_reduces_to_basename():
    # A traversal-style key can never escape the guild prefix.
    client, storage = _s3()
    storage.write("../../etc/passwd", b"x")
    assert ("bucket", "guild_7/passwd") in client.objects


def test_s3_exists_and_delete():
    client, storage = _s3()
    assert storage.exists("a.txt") is False
    storage.write("a.txt", b"hi")
    assert storage.exists("a.txt") is True
    assert storage.delete("a.txt") is True
    assert storage.exists("a.txt") is False
    # Deleting a missing key reports False (parity with the local backend).
    assert storage.delete("a.txt") is False


def test_s3_copy_same_namespace():
    client, storage = _s3()
    storage.write("src.bin", b"payload")
    assert storage.copy("src.bin", "dst.bin") is True
    assert ("bucket", "guild_7/dst.bin") in client.objects
    # Copying a missing source fails cleanly.
    assert storage.copy("missing.bin", "dst2.bin") is False


def test_s3_open_readable_round_trip():
    _, storage = _s3()
    storage.write("doc.pdf", b"hello world", content_type="application/pdf")
    blob = storage.open_readable("doc.pdf")
    assert blob is not None
    assert blob.path is None
    assert blob.content_type == "application/pdf"
    assert blob.content_length == len(b"hello world")
    assert b"".join(blob.stream) == b"hello world"


def test_s3_open_readable_missing_returns_none():
    _, storage = _s3()
    assert storage.open_readable("nope.bin") is None


def test_s3_presign_get_includes_key_and_filename():
    client, storage = _s3()
    url = storage.presign_get("file.zip", ttl=90, filename="report.zip")
    assert "guild_7/file.zip" in url
    op, params, ttl = client.presigned[0]
    assert op == "get_object"
    assert ttl == 90
    assert "report.zip" in params["ResponseContentDisposition"]


def test_build_upload_response_local_is_file_response(tmp_path):
    f = tmp_path / "x.png"
    f.write_bytes(b"img")
    resp = build_upload_response(ReadableBlob(path=f), media_type="image/png")
    assert isinstance(resp, FileResponse)


def test_build_upload_response_stream_sets_type_and_length():
    blob = ReadableBlob(
        stream=iter([b"chunk"]), content_type="image/png", content_length=5
    )
    resp = build_upload_response(blob)
    assert isinstance(resp, StreamingResponse)
    assert resp.media_type == "image/png"
    assert resp.headers["Content-Length"] == "5"


def test_build_upload_response_stream_attachment_disposition():
    blob = ReadableBlob(stream=iter([b"z"]), content_type="application/pdf")
    resp = build_upload_response(blob, filename="r.pdf")
    assert isinstance(resp, StreamingResponse)
    assert 'attachment; filename="r.pdf"' in resp.headers["Content-Disposition"]


def test_build_upload_response_escapes_quote_in_filename():
    # A filename with a double-quote must not break out of the header value;
    # it falls back to RFC 5987 filename*= encoding.
    blob = ReadableBlob(stream=iter([b"z"]), content_type="application/pdf")
    resp = build_upload_response(blob, filename='report"final".pdf')
    disposition = resp.headers["Content-Disposition"]
    assert "filename*=utf-8''" in disposition
    assert '"final"' not in disposition  # the raw quote did not survive verbatim


def test_resolver_namespaces_by_guild_for_s3(monkeypatch):
    monkeypatch.setattr(storage_module.settings, "STORAGE_BACKEND", "s3")
    monkeypatch.setattr(storage_module.settings, "S3_BUCKET", "bucket")
    monkeypatch.setattr(storage_module.settings, "S3_KMS_KEY_ID", None)
    monkeypatch.setattr(storage_module, "_get_s3_client", lambda: FakeS3Client())

    scoped = get_guild_storage(42)
    assert isinstance(scoped, S3Storage)
    assert scoped._prefix == "guild_42/"
    assert scoped._bucket == "bucket"
    # There is no unscoped S3 backend (it would write at the bucket root, outside
    # any guild namespace), so get_storage() refuses under s3.
    with pytest.raises(NotImplementedError):
        get_storage()


def test_resolver_requires_bucket_for_s3(monkeypatch):
    monkeypatch.setattr(storage_module.settings, "STORAGE_BACKEND", "s3")
    monkeypatch.setattr(storage_module.settings, "S3_BUCKET", None)
    with pytest.raises(ValueError, match="S3_BUCKET"):
        get_guild_storage(1)


def test_resolver_local_honors_guild_prefix():
    # Default backend is local; it now namespaces by guild like S3.
    backend = get_guild_storage(99)
    assert isinstance(backend, LocalFilesystemStorage)
    assert backend._prefix == "guild_99/"


# --- S3Storage.delete_prefix -------------------------------------------------


def test_s3_delete_prefix_sweeps_namespace():
    client, storage = _s3()
    storage.write("a.bin", b"1")
    storage.write("b.bin", b"2")
    # An object in a *different* guild's namespace must survive.
    other = S3Storage(bucket="bucket", client=client, prefix="guild_8/")
    other.write("c.bin", b"3")

    removed = storage.delete_prefix()
    assert removed == 2
    assert ("bucket", "guild_7/a.bin") not in client.objects
    assert ("bucket", "guild_7/b.bin") not in client.objects
    assert ("bucket", "guild_8/c.bin") in client.objects  # untouched


def test_s3_delete_prefix_refuses_empty_prefix():
    _, storage = _s3(prefix="")
    with pytest.raises(ValueError, match="empty prefix"):
        storage.delete_prefix()


def test_s3_delete_prefix_counts_only_successful_deletes():
    client, storage = _s3()
    storage.write("a.bin", b"1")
    storage.write("b.bin", b"2")
    # Simulate S3 reporting one key as failed (object lock, perms, …).
    client.delete_errors.add("guild_7/b.bin")
    removed = storage.delete_prefix()
    # Only the successful delete is counted; the failed object remains.
    assert removed == 1
    assert ("bucket", "guild_7/b.bin") in client.objects
    assert ("bucket", "guild_7/a.bin") not in client.objects


# --- LocalFilesystemStorage prefix + delete_prefix ---------------------------


def test_local_prefix_writes_under_guild_dir(tmp_path):
    storage = LocalFilesystemStorage(base_dir=str(tmp_path), prefix="guild_3/")
    storage.write("img.png", b"data")
    assert (tmp_path / "guild_3" / "img.png").read_bytes() == b"data"
    # Round-trips through the prefixed namespace.
    assert storage.open_readable("img.png").path == tmp_path / "guild_3" / "img.png"


def test_local_delete_prefix_removes_dir_and_counts(tmp_path):
    storage = LocalFilesystemStorage(base_dir=str(tmp_path), prefix="guild_3/")
    storage.write("a.png", b"1")
    storage.write("b.png", b"2")
    removed = storage.delete_prefix()
    assert removed == 2
    assert not (tmp_path / "guild_3").exists()
    # Missing dir -> 0, no error.
    assert storage.delete_prefix() == 0


def test_local_delete_prefix_refuses_empty_prefix(tmp_path):
    storage = LocalFilesystemStorage(base_dir=str(tmp_path))  # prefix=""
    with pytest.raises(ValueError, match="empty prefix"):
        storage.delete_prefix()


def test_purge_guild_blobs_local(tmp_path, monkeypatch):
    monkeypatch.setattr(storage_module.settings, "STORAGE_BACKEND", "local")
    monkeypatch.setattr(storage_module.settings, "UPLOADS_DIR", str(tmp_path))
    storage_module._local_backends.clear()
    get_guild_storage(5).write("x.png", b"data")
    assert (tmp_path / "guild_5" / "x.png").exists()
    removed = storage_module.purge_guild_blobs(5)
    assert removed == 1
    assert not (tmp_path / "guild_5").exists()
    storage_module._local_backends.clear()


# --- DualReadStorage (local->S3 cutover fallback) ----------------------------


def _dual(tmp_path):
    client = FakeS3Client()
    s3 = S3Storage(bucket="bucket", client=client, prefix="guild_7/")
    local = LocalFilesystemStorage(base_dir=str(tmp_path), prefix="guild_7/")
    return client, s3, local, DualReadStorage(primary=s3, fallback=local)


def test_dualread_write_goes_to_primary_only(tmp_path):
    client, _, local, dual = _dual(tmp_path)
    dual.write("x.png", b"data", content_type="image/png")
    assert ("bucket", "guild_7/x.png") in client.objects
    assert not (tmp_path / "guild_7" / "x.png").exists()


def test_dualread_read_falls_back_to_local_then_prefers_s3(tmp_path):
    _, s3, local, dual = _dual(tmp_path)
    # Un-backfilled blob: only on local -> served from local (path).
    local.write("old.png", b"local-bytes")
    blob = dual.open_readable("old.png")
    assert blob is not None and blob.path is not None
    assert blob.path.read_bytes() == b"local-bytes"
    # Backfilled blob: present in S3 -> served from S3 (stream) even if absent local.
    s3.write("new.png", b"s3-bytes", content_type="image/png")
    blob2 = dual.open_readable("new.png")
    assert blob2 is not None and blob2.stream is not None
    assert b"".join(blob2.stream) == b"s3-bytes"


def test_dualread_exists_checks_both(tmp_path):
    _, s3, local, dual = _dual(tmp_path)
    local.write("a", b"1")
    s3.write("b", b"2")
    assert dual.exists("a") is True
    assert dual.exists("b") is True
    assert dual.exists("missing") is False


def test_dualread_delete_removes_from_both(tmp_path):
    _, s3, local, dual = _dual(tmp_path)
    s3.write("d", b"1")
    local.write("d", b"1")
    assert dual.delete("d") is True
    assert dual.exists("d") is False


def test_dualread_delete_prefix_sums_both(tmp_path):
    _, s3, local, dual = _dual(tmp_path)
    s3.write("a", b"1")
    s3.write("b", b"2")
    local.write("c", b"3")
    assert dual.delete_prefix() == 3


def test_dualread_copy_cross_store(tmp_path):
    client, _, local, dual = _dual(tmp_path)
    # Source only on local (not yet backfilled): copy reads local, writes to S3.
    local.write("src.bin", b"payload")
    assert dual.copy("src.bin", "dst.bin") is True
    assert ("bucket", "guild_7/dst.bin") in client.objects
