"""Unit tests for the legacy flat-upload relocation (file-move logic only).

``relocate_flat_uploads`` is pure (filesystem + a filename->guild map), so these
run without a database. The DB-backed map builder and the boot orchestration are
covered by integration runs.
"""

from app.db.local_upload_migration import _legacy_flat_files, relocate_flat_uploads


def test_relocate_moves_flat_files_into_guild_dirs(tmp_path):
    (tmp_path / "a.png").write_bytes(b"1")
    (tmp_path / "b.png").write_bytes(b"2")
    # A pre-existing per-guild dir must be left alone by the scan.
    (tmp_path / "guild_9").mkdir()
    (tmp_path / "guild_9" / "kept.png").write_bytes(b"keep")

    moved, unmatched = relocate_flat_uploads(tmp_path, {"a.png": 5, "b.png": 6})

    assert (moved, unmatched) == (2, 0)
    assert (tmp_path / "guild_5" / "a.png").read_bytes() == b"1"
    assert (tmp_path / "guild_6" / "b.png").read_bytes() == b"2"
    assert not (tmp_path / "a.png").exists()
    assert not (tmp_path / "b.png").exists()
    # The already-prefixed file is untouched.
    assert (tmp_path / "guild_9" / "kept.png").read_bytes() == b"keep"


def test_relocate_leaves_unmatched_files_in_place(tmp_path):
    (tmp_path / "orphan.png").write_bytes(b"x")
    moved, unmatched = relocate_flat_uploads(tmp_path, {})  # no uploads row
    assert (moved, unmatched) == (0, 1)
    assert (tmp_path / "orphan.png").exists()  # not destroyed


def test_relocate_is_idempotent_when_dest_exists(tmp_path):
    (tmp_path / "a.png").write_bytes(b"new")
    dest_dir = tmp_path / "guild_5"
    dest_dir.mkdir()
    (dest_dir / "a.png").write_bytes(b"already")

    moved, unmatched = relocate_flat_uploads(tmp_path, {"a.png": 5})

    assert (moved, unmatched) == (1, 0)
    # Existing destination wins; the stray flat duplicate is dropped.
    assert (dest_dir / "a.png").read_bytes() == b"already"
    assert not (tmp_path / "a.png").exists()


def test_legacy_flat_files_ignores_subdirs(tmp_path):
    (tmp_path / "flat.png").write_bytes(b"1")
    (tmp_path / "guild_1").mkdir()
    (tmp_path / "guild_1" / "nested.png").write_bytes(b"2")
    flat = _legacy_flat_files(tmp_path)
    assert [p.name for p in flat] == ["flat.png"]


def test_legacy_flat_files_missing_root(tmp_path):
    assert _legacy_flat_files(tmp_path / "nope") == []
