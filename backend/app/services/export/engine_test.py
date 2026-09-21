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


# ---------------------------------------------------------------------------
# The streaming seam: aggregate exports assemble one artifact at a time
# ---------------------------------------------------------------------------


def _request(*keys: str):
    from app.services.export.contract import RenderItem, RenderRequest

    return RenderRequest(
        guild_id=1,
        template_id="data-table",
        format="zip",
        batch=tuple(RenderItem(key=k, data={}) for k in keys),
    )


async def test_render_artifacts_uses_a_backends_own_stream(monkeypatch):
    """A backend that streams is asked to stream — that is what keeps peak
    memory at one artifact rather than the whole batch."""
    from app.services.export import engine

    eager_calls = []

    class Streaming:
        async def render_stream(self, req):
            for item in req.batch:
                yield _artifact(item.key, item.key.encode())

        async def render(self, req):  # pragma: no cover - must not be reached
            eager_calls.append(req)
            return []

    monkeypatch.setattr(engine, "get_backend", lambda: Streaming())
    produced = [a.key async for a in engine.render_artifacts(_request("a", "b"))]
    assert produced == ["a", "b"]
    assert eager_calls == []


async def test_render_artifacts_falls_back_to_an_eager_backend(monkeypatch):
    """A second RenderBackend implementation stays a drop-in: without a
    streaming path, the batch renders eagerly and yields the same artifacts."""
    from app.services.export import engine

    class Eager:
        async def render(self, req):
            return [_artifact(item.key, item.key.encode()) for item in req.batch]

    monkeypatch.setattr(engine, "get_backend", lambda: Eager())
    produced = [a.key async for a in engine.render_artifacts(_request("a", "b"))]
    assert produced == ["a", "b"]


# ---------------------------------------------------------------------------
# Download vs delivery: where a finished archive goes
# ---------------------------------------------------------------------------


def test_delivery_is_not_configured_by_default():
    """Unset means an over-size export is refused, not produced with nowhere
    to put it."""
    from app.services.export import delivery

    assert delivery.destination_root() is None
    assert delivery.is_configured() is False


def test_delivery_lands_under_a_per_community_directory(tmp_path, monkeypatch):
    from app.core.config import settings
    from app.services.export import delivery

    monkeypatch.setattr(settings, "EXPORT_DESTINATION_DIR", str(tmp_path))
    source = tmp_path / "scratch.zip"
    source.write_bytes(b"archive-bytes")

    ref = delivery.deliver(source, guild_id=7, filename="guild-2026-09-20-3.zip")

    landed = tmp_path / "guild_7" / "guild-2026-09-20-3.zip"
    assert ref == str(landed)
    assert landed.read_bytes() == b"archive-bytes"
    # Copied, not moved: the source is a temp file the caller still owns and
    # may be on a different filesystem from the destination mount.
    assert source.exists()


def test_delivery_keeps_a_name_inside_the_community_directory(tmp_path, monkeypatch):
    """The filename is built by the engine, never user text — the basename is
    taken anyway, so a name lands in the community's own directory."""
    from app.core.config import settings
    from app.services.export import delivery

    monkeypatch.setattr(settings, "EXPORT_DESTINATION_DIR", str(tmp_path))
    source = tmp_path / "scratch.zip"
    source.write_bytes(b"x")

    ref = delivery.deliver(source, guild_id=1, filename="../../elsewhere.zip")

    assert ref == str(tmp_path / "guild_1" / "elsewhere.zip")
    assert (tmp_path / "guild_1" / "elsewhere.zip").exists()
    assert not (tmp_path / "elsewhere.zip").exists()
