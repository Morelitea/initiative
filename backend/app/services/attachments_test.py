"""Unit tests for the attachments service helpers."""

import pytest
from fastapi import UploadFile

from app.services.attachments import (
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


@pytest.mark.unit
async def test_read_upload_bounded_returns_bytes_within_limit() -> None:
    upload = _CountingUpload(b"hello")
    result = await read_upload_bounded(upload, max_size=10)  # type: ignore[arg-type]
    assert result == b"hello"
    # Reads at most one byte past the cap, never the whole stream unbounded.
    assert upload.requested == 11


@pytest.mark.unit
async def test_read_upload_bounded_accepts_exactly_at_limit() -> None:
    upload = _CountingUpload(b"abcdef")
    result = await read_upload_bounded(upload, max_size=6)  # type: ignore[arg-type]
    assert result == b"abcdef"


@pytest.mark.unit
async def test_read_upload_bounded_rejects_over_limit() -> None:
    upload = _CountingUpload(b"abcdefg")  # 7 bytes, cap is 6
    with pytest.raises(FileTooLargeError) as exc:
        await read_upload_bounded(upload, max_size=6)  # type: ignore[arg-type]
    assert exc.value.max_size == 6
    # Only the cap + 1 sentinel byte was requested, not the full body.
    assert upload.requested == 7


@pytest.mark.unit
async def test_read_upload_bounded_works_with_real_uploadfile() -> None:
    import io

    upload = UploadFile(filename="x.bin", file=io.BytesIO(b"X" * 100))
    with pytest.raises(FileTooLargeError):
        await read_upload_bounded(upload, max_size=50)
