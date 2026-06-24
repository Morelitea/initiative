"""Unit tests for the local storage backend (Phase 1 of the storage rebuild).

Pure filesystem behavior — no DB. Verifies the round-trip ops the call sites
rely on and the path-traversal containment that the serve endpoints delegate to
``resolve_readable``.
"""

import pytest

from app.services.storage import LocalFilesystemStorage, StorageBackend, get_storage


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
