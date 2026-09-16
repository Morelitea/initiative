"""Tests for the attachment upload endpoint."""

import io

import pytest
from httpx import AsyncClient

from app.api.v1.tenant_endpoints.attachments import _detect_content_type
from app.models.platform.guild import GuildRole

#: A real 1x1 PNG — the header reader walks IHDR, so a stub signature is not
#: enough to be identified as one.
TINY_PNG = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx"
    b"\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00"
    b"\x00\x00\x00IEND\xaeB`\x82"
)


@pytest.mark.integration
async def test_upload_image_too_large(client: AsyncClient, acting_user):
    """Uploading an image larger than MAX_IMAGE_BYTES returns 413."""
    a = await acting_user(guild_role=GuildRole.admin)

    oversized = b"\x89PNG\r\n\x1a\n" + b"X" * (11 * 1024 * 1024)
    response = await client.post(
        a.g("/attachments/"),
        headers=a.headers,
        files={"file": ("big.png", io.BytesIO(oversized), "image/png")},
    )

    assert response.status_code == 413
    assert response.json()["detail"] == "ATTACHMENT_TOO_LARGE"


@pytest.mark.integration
async def test_upload_image_within_limit(client: AsyncClient, acting_user):
    """A valid PNG under the size limit is accepted."""
    a = await acting_user(guild_role=GuildRole.admin)

    response = await client.post(
        a.g("/attachments/"),
        headers=a.headers,
        files={"file": ("pixel.png", io.BytesIO(TINY_PNG), "image/png")},
    )

    assert response.status_code == 201
    assert response.json()["url"].startswith("/uploads/")


@pytest.mark.integration
async def test_upload_names_the_file_after_its_bytes(client: AsyncClient, acting_user):
    """The stored name and type come from the bytes, not from what the client
    called the file — so the name a serve request reads back describes it."""
    a = await acting_user(guild_role=GuildRole.admin)
    svg = b'<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1"></svg>'

    response = await client.post(
        a.g("/attachments/"),
        headers=a.headers,
        files={"file": ("disguised.png", io.BytesIO(svg), "image/png")},
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["content_type"] == "image/svg+xml"
    assert payload["url"].endswith(".svg")


@pytest.mark.integration
async def test_upload_ignores_a_declared_svg_type(client: AsyncClient, acting_user):
    """A raster is identified as one however it is labelled."""
    a = await acting_user(guild_role=GuildRole.admin)

    response = await client.post(
        a.g("/attachments/"),
        headers=a.headers,
        files={"file": ("pixel.svg", io.BytesIO(TINY_PNG), "image/svg+xml")},
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["content_type"] == "image/png"
    assert payload["url"].endswith(".png")


@pytest.mark.integration
@pytest.mark.parametrize(
    "prolog",
    [
        b"\xef\xbb\xbf",
        b'<?xml version="1.0" encoding="UTF-8"?>\n',
        b"<!-- exported by a drawing program -->\n",
        b'<!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN" '
        b'"http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd">\n',
    ],
)
async def test_upload_accepts_an_svg_behind_a_prolog(
    client: AsyncClient, acting_user, prolog: bytes
):
    """Real SVGs open with a byte-order mark, a declaration, a comment or a
    doctype before the root element; all four are still SVGs."""
    a = await acting_user(guild_role=GuildRole.admin)
    svg = prolog + b'<svg xmlns="http://www.w3.org/2000/svg"></svg>'

    response = await client.post(
        a.g("/attachments/"),
        headers=a.headers,
        files={"file": ("image.svg", io.BytesIO(svg), "image/svg+xml")},
    )

    assert response.status_code == 201
    assert response.json()["url"].endswith(".svg")


@pytest.mark.integration
async def test_upload_refuses_bytes_that_are_no_image(client: AsyncClient, acting_user):
    """Nothing the detector recognizes means nothing is stored, whatever the
    client called it."""
    a = await acting_user(guild_role=GuildRole.admin)

    response = await client.post(
        a.g("/attachments/"),
        headers=a.headers,
        files={
            "file": (
                "payload.png",
                io.BytesIO(b"MZ\x90\x00this is a program, not a picture"),
                "image/png",
            )
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "ATTACHMENT_INVALID_IMAGE"


@pytest.mark.unit
@pytest.mark.parametrize(
    "contents",
    [
        b'<svg xmlns="http://www.w3.org/2000/svg"></svg>',
        b"<svg/>",
        b'\xef\xbb\xbf<svg xmlns="x"></svg>',
        b'<?xml version="1.0"?>\n<svg xmlns="x"/>',
        b"<!-- drawn by a program -->\n<svg xmlns='x'/>",
        b'<!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN" '
        b'"http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd">\n<svg xmlns="x"/>',
        b'<?xml version="1.0"?><!-- one --><!-- two --><svg/>',
    ],
)
def test_an_svg_root_is_found_behind_its_prolog(contents: bytes):
    """Whatever an SVG carries ahead of its root element, the root is what
    decides."""
    assert _detect_content_type(contents) == "image/svg+xml"


@pytest.mark.unit
@pytest.mark.parametrize(
    "contents",
    [
        b"<!-- <svg -->not an image",
        b"<svgfoo></svgfoo>",
        b"<html><svg/></html>",
        b"<!-- a comment that never closes <svg/>",
        b"plain text mentioning <svg",
        b"",
    ],
)
def test_markup_that_is_not_an_svg_is_not_an_image(contents: bytes):
    """Naming the element somewhere in the file is not being it — the root
    element is, so none of these are stored as pictures."""
    assert _detect_content_type(contents) is None


@pytest.mark.unit
def test_a_raster_is_identified_before_markup():
    """A raster signature settles it; nothing goes looking for markup in a PNG."""
    assert _detect_content_type(TINY_PNG) == "image/png"
