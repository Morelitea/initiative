"""Unit tests for engine artifact bundling (selection exports: batch=N → zip)."""

import io
import zipfile

import pytest

from app.services.export.contract import RenderedArtifact
from app.services.export.engine import ExportError, _bundle, _dedupe_name

pytestmark = pytest.mark.unit


def _artifact(key: str, content: bytes = b"x", filename: str | None = None):
    return RenderedArtifact(
        key=key, content_type="application/pdf", content=content, filename=filename
    )


def test_single_artifact_passes_through_unwrapped():
    artifact = _artifact("report")
    assert _bundle([artifact], format="pdf", stem="document-2026-07-14") is artifact


def test_batch_zips_with_per_artifact_names():
    artifacts = [
        _artifact("alpha-2026-07-14", b"AAA"),
        # A named artifact (e.g. .lexical) keeps its own filename.
        _artifact("beta", b"BBB", filename="beta-2026-07-14.lexical"),
    ]
    bundle = _bundle(artifacts, format="pdf", stem="document-2026-07-14")
    assert bundle.content_type == "application/zip"
    assert bundle.filename == "document-2026-07-14.zip"
    archive = zipfile.ZipFile(io.BytesIO(bundle.content))
    assert set(archive.namelist()) == {
        "alpha-2026-07-14.pdf",
        "beta-2026-07-14.lexical",
    }
    assert archive.read("alpha-2026-07-14.pdf") == b"AAA"
    assert archive.read("beta-2026-07-14.lexical") == b"BBB"


def test_batch_dedupes_colliding_entry_names():
    """Two selected entities with the same title produce the same stem — both
    must survive in the archive, not silently overwrite."""
    artifacts = [
        _artifact("notes-2026-07-14", b"FIRST"),
        _artifact("notes-2026-07-14", b"SECOND"),
        _artifact("notes-2026-07-14", b"THIRD"),
    ]
    bundle = _bundle(artifacts, format="json", stem="document-2026-07-14")
    archive = zipfile.ZipFile(io.BytesIO(bundle.content))
    assert set(archive.namelist()) == {
        "notes-2026-07-14.json",
        "notes-2026-07-14 (2).json",
        "notes-2026-07-14 (3).json",
    }
    assert archive.read("notes-2026-07-14 (2).json") == b"SECOND"


def test_empty_batch_is_an_invalid_selection():
    with pytest.raises(ExportError):
        _bundle([], format="pdf", stem="s")


def test_dedupe_name_handles_extensionless_names():
    taken = {"data", "data (2)"}
    assert _dedupe_name("data", taken) == "data (3)"
    assert _dedupe_name("fresh", taken) == "fresh"
