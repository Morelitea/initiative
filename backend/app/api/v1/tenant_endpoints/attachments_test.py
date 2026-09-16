"""Tests for the attachment upload endpoint."""

import io

import pytest
from httpx import AsyncClient

from app.models.platform.guild import GuildRole


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

    tiny_png = (
        b"\x89PNG\r\n\x1a\n"
        b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx"
        b"\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00"
        b"\x00\x00\x00IEND\xaeB`\x82"
    )
    response = await client.post(
        a.g("/attachments/"),
        headers=a.headers,
        files={"file": ("pixel.png", io.BytesIO(tiny_png), "image/png")},
    )

    assert response.status_code == 201
    assert response.json()["url"].startswith("/uploads/")


@pytest.mark.integration
async def test_upload_does_not_trust_svg_content_type(client: AsyncClient, acting_user):
    """A caller cannot turn arbitrary bytes into active SVG by naming its MIME type."""
    a = await acting_user(guild_role=GuildRole.admin)

    response = await client.post(
        a.g("/attachments/"),
        headers=a.headers,
        files={
            "file": (
                "payload.png",
                io.BytesIO(b"<script>alert(document.domain)</script>"),
                "image/svg+xml",
            )
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "ATTACHMENT_INVALID_IMAGE"


@pytest.mark.integration
async def test_upload_uses_detected_svg_type_and_suffix(
    client: AsyncClient, acting_user
):
    """Serving policy follows detected bytes, not the caller's name or MIME type."""
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

    served = await client.get(payload["url"], headers=a.headers)
    assert served.status_code == 200
    assert served.headers["content-type"].startswith("image/svg+xml")
    assert served.headers["content-disposition"] == "attachment"
    assert served.headers["content-security-policy"] == "script-src 'none'"
