"""Unit tests for avatar validation.

Fixtures are hand-built headers rather than encoder output: there is no image
library in the runtime (deliberately — see ``app.core.image_headers``), and
writing the bytes out documents the layout the parser depends on.
"""

import struct
import zlib

import pytest

from app.core.image_headers import read_image_header
from app.core.messages import UserMessages
from app.models.platform.user_avatar import AVATAR_MAX_BYTES
from app.services.platform import user_avatars as service


def png(width: int, height: int, *, pad: int = 0) -> bytes:
    ihdr = struct.pack(">II", width, height) + b"\x08\x06\x00\x00\x00"
    chunk = b"IHDR" + ihdr
    out = (
        b"\x89PNG\r\n\x1a\n"
        + struct.pack(">I", len(ihdr))
        + chunk
        + struct.pack(">I", zlib.crc32(chunk))
    )
    return out + b"\x00" * pad


def jpeg(width: int, height: int) -> bytes:
    sof = b"\x08" + struct.pack(">HH", height, width) + b"\x03" + b"\x00" * 9
    return (
        b"\xff\xd8"
        + b"\xff\xe0"
        + struct.pack(">H", 16)
        + b"JFIF\x00"
        + b"\x00" * 9
        + b"\xff\xc0"
        + struct.pack(">H", len(sof) + 2)
        + sof
    )


def webp(width: int, height: int) -> bytes:
    body = (
        b"VP8 "
        + struct.pack("<I", 20)
        + b"\x00\x00\x00"
        + b"\x9d\x01\x2a"
        + struct.pack("<HH", width, height)
    )
    return b"RIFF" + struct.pack("<I", len(body) + 4) + b"WEBP" + body


@pytest.mark.unit
@pytest.mark.parametrize(
    "builder,expected",
    [(png, "image/png"), (jpeg, "image/jpeg"), (webp, "image/webp")],
)
def test_accepts_each_supported_format(builder, expected) -> None:
    validated = service.validate_avatar(builder(256, 256))

    assert validated.content_type == expected
    assert (validated.width, validated.height) == (256, 256)


@pytest.mark.unit
def test_content_type_comes_from_the_header_not_the_caller() -> None:
    """The recorded type is served back in a Content-Type, so it is the one the
    bytes prove rather than anything a client asserted."""
    assert service.validate_avatar(webp(64, 64)).content_type == "image/webp"


@pytest.mark.unit
def test_digest_is_of_these_exact_bytes() -> None:
    import hashlib

    data = png(128, 128)

    assert service.validate_avatar(data).sha256 == hashlib.sha256(data).hexdigest()


@pytest.mark.unit
def test_refuses_svg() -> None:
    """An avatar is rendered rather than downloaded, so a scriptable document
    format has no safe way to be served."""
    svg = b'<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256"/>'

    with pytest.raises(service.AvatarRejected) as excinfo:
        service.validate_avatar(svg)

    assert excinfo.value.code == UserMessages.AVATAR_INVALID_IMAGE


@pytest.mark.unit
def test_refuses_a_gif_even_though_it_is_a_raster() -> None:
    gif = b"GIF89a" + struct.pack("<HH", 256, 256) + b"\x00" * 20

    with pytest.raises(service.AvatarRejected):
        service.validate_avatar(gif)


@pytest.mark.unit
def test_refuses_oversized_dimensions() -> None:
    with pytest.raises(service.AvatarRejected) as excinfo:
        service.validate_avatar(png(512, 512))

    assert excinfo.value.code == UserMessages.AVATAR_TOO_LARGE_DIMENSIONS


@pytest.mark.unit
def test_refuses_a_non_square_image() -> None:
    with pytest.raises(service.AvatarRejected) as excinfo:
        service.validate_avatar(png(256, 100))

    assert excinfo.value.code == UserMessages.AVATAR_NOT_SQUARE


@pytest.mark.unit
def test_allows_a_pixel_of_rounding_off_square() -> None:
    """A canvas resize lands on 1:1; the tolerance is for images prepared
    elsewhere, so one pixel out is not a refusal."""
    assert service.validate_avatar(png(256, 255)).width == 256


@pytest.mark.unit
def test_refuses_bytes_over_the_cap() -> None:
    with pytest.raises(service.AvatarRejected) as excinfo:
        service.validate_avatar(png(256, 256, pad=AVATAR_MAX_BYTES))

    assert excinfo.value.code == UserMessages.AVATAR_TOO_LARGE


@pytest.mark.unit
def test_refuses_an_empty_body() -> None:
    with pytest.raises(service.AvatarRejected):
        service.validate_avatar(b"")


@pytest.mark.unit
def test_refuses_a_truncated_header() -> None:
    with pytest.raises(service.AvatarRejected):
        service.validate_avatar(png(256, 256)[:12])


@pytest.mark.unit
def test_riff_that_is_not_webp_is_not_an_image() -> None:
    assert read_image_header(b"RIFF" + b"\x00" * 4 + b"AVI " + b"\x00" * 20) is None


@pytest.mark.unit
def test_serving_url_carries_the_digest() -> None:
    url = service.avatar_url(7, "ab" * 32)

    assert url == f"/api/v1/users/7/avatar/{'ab' * 32}"
    assert service.is_avatar_url(url)


@pytest.mark.unit
def test_an_external_url_is_not_one_of_ours() -> None:
    assert not service.is_avatar_url("https://idp.example/pic.png")


@pytest.mark.unit
@pytest.mark.parametrize("value", ["", "xyz", "AB" * 32, "ab" * 31, "ab" * 33])
def test_rejects_a_malformed_digest(value: str) -> None:
    assert not service.is_valid_digest(value)
