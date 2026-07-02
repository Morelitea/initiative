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
