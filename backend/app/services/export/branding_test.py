"""Unit tests for export branding: icon decoding + the render-request seam."""

import base64
import struct
import zlib

import pytest

from app.services.export.branding import _decode_icon, apply_brand
from app.services.export.contract import RenderItem, RenderRequest

pytestmark = pytest.mark.unit


def _png_bytes() -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        c = tag + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c))

    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(b"\x00\xff\x00\x00"))
        + chunk(b"IEND", b"")
    )


def _data_uri(mime: str, data: bytes) -> str:
    return f"data:{mime};base64," + base64.b64encode(data).decode()


def test_decode_icon_accepts_raster_data_uri():
    decoded = _decode_icon(_data_uri("image/png", _png_bytes()))
    assert decoded is not None
    filename, blob = decoded
    assert filename == "guild-icon.png"
    assert blob == _png_bytes()
    # jpeg maps to a .jpg extension.
    jpeg = _decode_icon(_data_uri("image/jpeg", b"\xff\xd8\xff\xe0jpeg-ish"))
    assert jpeg is not None
    assert jpeg[0] == "guild-icon.jpg"


def test_decode_icon_rejects_svg_and_non_raster():
    # SVG is deliberately excluded (vector parser surface in the trusted report).
    assert _decode_icon(_data_uri("image/svg+xml", b"<svg></svg>")) is None
    assert _decode_icon(_data_uri("text/html", b"<h1>x</h1>")) is None


def test_decode_icon_rejects_malformed_and_missing():
    assert _decode_icon(None) is None
    assert _decode_icon("") is None
    assert _decode_icon("not-a-data-uri") is None
    # A data URI with non-base64 payload.
    assert _decode_icon("data:image/png;base64,!!!!not base64!!!!") is None


def test_decode_icon_rejects_oversized():
    from app.services.export import branding

    big = _data_uri("image/png", b"x" * (branding._MAX_ICON_BYTES + 1))
    assert _decode_icon(big) is None


async def test_apply_brand_passes_through_non_pdf_untouched():
    """Only PDF reports carry a header; a csv/xlsx/json request is returned
    unchanged (and the session is never touched, so None is safe here)."""
    request = RenderRequest(
        guild_id=1,
        template_id="task-table",
        format="csv",
        batch=(RenderItem(key="tasks", data={"rows": []}),),
    )
    result = await apply_brand(request, session=None)
    assert result is request
