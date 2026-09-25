"""Unit tests for the attachments service helpers."""

import pytest
from fastapi import UploadFile

from app.services.tenant.attachments import (
    FileTooLargeError,
    read_upload_bounded,
)


class _CountingUpload:
    """Minimal UploadFile stand-in that records how many bytes were requested.

    ``read_upload_bounded`` must ask for exactly ``max_size + 1`` bytes so an
    over-limit body is detected without buffering the whole payload.
    """

    def __init__(self, body: bytes) -> None:
        self._body = body
        self.requested: int | None = None

    async def read(self, size: int = -1) -> bytes:
        self.requested = size
        if size < 0:
            return self._body
        return self._body[:size]


async def test_read_upload_bounded_returns_bytes_within_limit() -> None:
    upload = _CountingUpload(b"hello")
    result = await read_upload_bounded(upload, max_size=10)  # type: ignore[arg-type]
    assert result == b"hello"
    # Reads at most one byte past the cap, never the whole stream unbounded.
    assert upload.requested == 11


async def test_read_upload_bounded_accepts_exactly_at_limit() -> None:
    upload = _CountingUpload(b"abcdef")
    result = await read_upload_bounded(upload, max_size=6)  # type: ignore[arg-type]
    assert result == b"abcdef"


async def test_read_upload_bounded_rejects_over_limit() -> None:
    upload = _CountingUpload(b"abcdefg")  # 7 bytes, cap is 6
    with pytest.raises(FileTooLargeError) as exc:
        await read_upload_bounded(upload, max_size=6)  # type: ignore[arg-type]
    assert exc.value.max_size == 6
    # Only the cap + 1 sentinel byte was requested, not the full body.
    assert upload.requested == 7


async def test_read_upload_bounded_works_with_real_uploadfile() -> None:
    import io

    upload = UploadFile(filename="x.bin", file=io.BytesIO(b"X" * 100))
    with pytest.raises(FileTooLargeError):
        await read_upload_bounded(upload, max_size=50)


def test_a_description_s_pictures_are_read_out_of_its_markdown():
    from app.services.tenant.attachments import upload_urls_in_markdown

    text = (
        "Before ![a](/uploads/9/task-abc_1.png) and "
        "![b](https://example.com/uploads/9/task-def.jpg), "
        "a link [c](/uploads/9/doc.pdf) and /api/v1/uploads-nope"
    )

    assert upload_urls_in_markdown(text) == {
        "/uploads/9/task-abc_1.png",
        "/uploads/9/task-def.jpg",
        "/uploads/9/doc.pdf",
    }
    assert upload_urls_in_markdown(None) == set()


class _RecordingStorage:
    def __init__(self) -> None:
        self.writes: list[tuple[str, bytes, str | None]] = []

    def write(self, key: str, data: bytes, *, content_type: str | None = None):
        self.writes.append((key, data, content_type))


class _RecordingSession:
    def __init__(self) -> None:
        self.added: list = []

    def add(self, row) -> None:
        self.added.append(row)


@pytest.mark.parametrize(
    ("content_type", "written_as"),
    [("image/png", "image/png"), (None, "application/octet-stream")],
)
async def test_store_upload_writes_the_bytes_and_records_them(
    monkeypatch, content_type, written_as
) -> None:
    """The bytes land under the given name and the row describes them. A file
    whose type an import could not name is written as octet-stream, and its
    row keeps no type rather than claiming one."""
    from app.services.tenant import attachments

    storage = _RecordingStorage()
    monkeypatch.setattr(attachments, "get_guild_storage", lambda _guild: storage)
    session = _RecordingSession()

    url = await attachments.store_upload(
        session,
        guild_id=7,
        filename="abc.png",
        data=b"bytes",
        content_type=content_type,
        created_by=3,
    )

    assert url == "/uploads/7/abc.png"
    assert storage.writes == [("abc.png", b"bytes", written_as)]
    [row] = session.added
    assert (row.filename, row.created_by, row.size_bytes, row.content_type) == (
        "abc.png",
        3,
        5,
        content_type,
    )
    assert row.content_hash == attachments.compute_content_hash(b"bytes")


@pytest.mark.parametrize(
    ("extension", "prefix", "shape"),
    [
        (".pdf", "", r"[0-9a-f]{32}\.pdf"),
        ("pdf", "", r"[0-9a-f]{32}\.pdf"),
        ("", "", r"[0-9a-f]{32}"),
        (".png", "pasted-", r"pasted-[0-9a-f]{32}\.png"),
    ],
)
def test_a_new_upload_name_is_random_and_keeps_its_extension(extension, prefix, shape):
    import re

    from app.services.tenant.attachments import new_upload_filename

    assert re.fullmatch(shape, new_upload_filename(extension, prefix=prefix))
