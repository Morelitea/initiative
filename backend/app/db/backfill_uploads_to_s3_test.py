"""Unit tests for the local->S3 backfill's per-guild copy logic.

``backfill_guild_dir`` is pure of the DB (a tmp dir + a filename->metadata map +
a destination backend), so these run without a database. The DB-backed guild
iteration is a thin shell over it.
"""

from botocore.exceptions import ClientError

from app.db.backfill_uploads_to_s3 import BackfillSummary, backfill_guild_dir


class _FakeDest:
    """Minimal StorageBackend stub — backfill_guild_dir only calls exists/write."""

    def __init__(self) -> None:
        self.written: dict[str, tuple[bytes, str | None]] = {}

    def exists(self, key: str) -> bool:
        return key in self.written

    def write(self, key: str, data: bytes, *, content_type: str | None = None) -> None:
        self.written[key] = (data, content_type)


def test_backfill_copies_with_content_type_from_meta(tmp_path):
    gd = tmp_path / "guild_5"
    gd.mkdir()
    (gd / "a.png").write_bytes(b"img")
    (gd / "b.dat").write_bytes(b"x")
    dest = _FakeDest()
    meta = {"a.png": ("image/png", None)}  # b.dat has no row
    summary = BackfillSummary()

    backfill_guild_dir(gd, meta, dest, summary, guild_id=5, dry_run=False)

    assert summary.copied == 2
    assert summary.failed == 0
    assert dest.written["a.png"] == (b"img", "image/png")
    # No row -> content_type guessed from the extension (".dat" is unknown -> None).
    assert dest.written["b.dat"][1] is None


def test_backfill_guesses_content_type_from_extension(tmp_path):
    gd = tmp_path / "guild_5"
    gd.mkdir()
    (gd / "doc.pdf").write_bytes(b"%PDF")
    dest = _FakeDest()
    summary = BackfillSummary()

    backfill_guild_dir(gd, {}, dest, summary, guild_id=5, dry_run=False)

    assert dest.written["doc.pdf"][1] == "application/pdf"


def test_backfill_skips_already_present(tmp_path):
    gd = tmp_path / "guild_5"
    gd.mkdir()
    (gd / "a.png").write_bytes(b"img")
    dest = _FakeDest()
    dest.written["a.png"] = (b"already", "image/png")  # pretend it's in S3
    summary = BackfillSummary()

    backfill_guild_dir(gd, {}, dest, summary, guild_id=5, dry_run=False)

    assert summary.skipped == 1
    assert summary.copied == 0
    assert dest.written["a.png"][0] == b"already"  # not overwritten


def test_backfill_hash_mismatch_is_not_copied(tmp_path):
    gd = tmp_path / "guild_5"
    gd.mkdir()
    (gd / "c.bin").write_bytes(b"actual-bytes")
    dest = _FakeDest()
    meta = {"c.bin": (None, "00deadbeef")}  # wrong hash
    summary = BackfillSummary()

    backfill_guild_dir(gd, meta, dest, summary, guild_id=5, dry_run=False)

    assert summary.hash_mismatches == 1
    assert summary.failed == 1
    assert "c.bin" not in dest.written  # corruption not propagated


def test_backfill_dry_run_checks_dest_and_writes_nothing(tmp_path):
    gd = tmp_path / "guild_5"
    gd.mkdir()
    (gd / "a.png").write_bytes(b"img")
    (gd / "b.png").write_bytes(b"img2")
    dest = _FakeDest()
    dest.written["a.png"] = (b"x", "image/png")  # already in S3
    summary = BackfillSummary()

    backfill_guild_dir(gd, {}, dest, summary, guild_id=5, dry_run=True)

    # The exists() skip check runs in dry-run too, so already-copied files aren't
    # re-counted — the report reflects the real remaining work.
    assert summary.skipped == 1
    assert summary.copied == 1
    assert "b.png" not in dest.written  # dry-run writes nothing


class _ForbiddenHeadDest(_FakeDest):
    """A store whose credentials lack s3:ListBucket: HeadObject on a missing key
    raises 403 (Forbidden) instead of returning 404, but writes still work."""

    def exists(self, key: str) -> bool:
        raise ClientError(
            {"Error": {"Code": "403"}, "ResponseMetadata": {"HTTPStatusCode": 403}},
            "HeadObject",
        )


def test_backfill_tolerates_403_head_and_uploads(tmp_path):
    """A 403 on the existence check (missing s3:ListBucket) must not abort the
    migration — the object is uploaded anyway, not recorded as a failure."""
    gd = tmp_path / "guild_5"
    gd.mkdir()
    (gd / "a.png").write_bytes(b"img")
    dest = _ForbiddenHeadDest()
    summary = BackfillSummary()

    backfill_guild_dir(gd, {}, dest, summary, guild_id=5, dry_run=False)

    assert summary.failed == 0
    assert summary.copied == 1
    assert dest.written["a.png"][0] == b"img"


class _BrokenHeadDest(_FakeDest):
    """A non-403 HeadObject error (e.g. wrong endpoint) is a real failure."""

    def exists(self, key: str) -> bool:
        raise ClientError(
            {"Error": {"Code": "500"}, "ResponseMetadata": {"HTTPStatusCode": 500}},
            "HeadObject",
        )


def test_backfill_non_403_head_error_is_a_failure(tmp_path):
    gd = tmp_path / "guild_5"
    gd.mkdir()
    (gd / "a.png").write_bytes(b"img")
    dest = _BrokenHeadDest()
    summary = BackfillSummary()

    backfill_guild_dir(gd, {}, dest, summary, guild_id=5, dry_run=False)

    assert summary.failed == 1
    assert summary.copied == 0
    assert "a.png" not in dest.written
