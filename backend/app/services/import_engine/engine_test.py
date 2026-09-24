"""Staged payloads round-trip through either storage backend."""

import pytest

from app.services import storage as storage_module
from app.services.import_engine import engine as import_engine
from app.services.storage import LocalFilesystemStorage, S3Storage
from app.services.storage_test import FakeS3Client

pytestmark = pytest.mark.unit

_PAYLOAD = b"PK\x03\x04" + bytes(range(256)) * 600  # spans several read chunks


def test_staged_payload_reads_back_from_s3(monkeypatch):
    backend = S3Storage(bucket="bucket", client=FakeS3Client(), prefix="guild_7/")
    monkeypatch.setattr(storage_module, "get_guild_storage", lambda _guild: backend)

    ref = import_engine.stage_payload(7, _PAYLOAD, suffix="zip")

    assert import_engine.read_payload(7, ref) == _PAYLOAD


def test_staged_payload_reads_back_from_local_storage(monkeypatch, tmp_path):
    backend = LocalFilesystemStorage(base_dir=str(tmp_path))
    monkeypatch.setattr(storage_module, "get_guild_storage", lambda _guild: backend)

    ref = import_engine.stage_payload(7, _PAYLOAD, suffix="zip")

    assert import_engine.read_payload(7, ref) == _PAYLOAD


def test_missing_payload_reads_as_none(monkeypatch):
    backend = S3Storage(bucket="bucket", client=FakeS3Client(), prefix="guild_7/")
    monkeypatch.setattr(storage_module, "get_guild_storage", lambda _guild: backend)

    assert import_engine.read_payload(7, "imports/gone.zip") is None
