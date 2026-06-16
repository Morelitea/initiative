"""Integration tests for the native OTA bundle endpoints.

The native (Capacitor) app polls these to decide whether to download a matching web bundle.
A local dev/test checkout has no ``/app/ota`` directory, so the endpoints must 404 cleanly;
when an image ships the artifacts, the manifest must advertise a checksum that actually
matches the served zip.
"""

from __future__ import annotations

import hashlib

import pytest
from httpx import AsyncClient

from app.api.v1.public_endpoints import native
from app.core.messages import NativeMessages
from app.core.version import __version__


@pytest.mark.integration
async def test_manifest_404_when_bundle_absent(client: AsyncClient):
    """No OTA artifacts present (the default outside a built image) → 404, not a 500."""
    response = await client.get("/api/v1/native/bundle/manifest")
    assert response.status_code == 404
    assert response.json()["detail"] == NativeMessages.OTA_BUNDLE_NOT_AVAILABLE


@pytest.mark.integration
async def test_download_404_when_bundle_absent(client: AsyncClient):
    response = await client.get("/api/v1/native/bundle/download")
    assert response.status_code == 404
    assert response.json()["detail"] == NativeMessages.OTA_BUNDLE_NOT_AVAILABLE


@pytest.mark.integration
async def test_manifest_advertises_matching_checksum(
    client: AsyncClient, tmp_path, monkeypatch
):
    """The checksum in the manifest must be the sha256 of the exact zip the download
    endpoint serves — the updater rejects the bundle otherwise."""
    bundle = tmp_path / "bundle.zip"
    bundle.write_bytes(b"PK\x03\x04 fake zip payload")
    digest = hashlib.sha256(bundle.read_bytes()).hexdigest()
    checksum = tmp_path / "bundle.sha256"
    checksum.write_text(f"{digest}\n")

    monkeypatch.setattr(native, "_BUNDLE_PATH", bundle)
    monkeypatch.setattr(native, "_CHECKSUM_PATH", checksum)

    response = await client.get("/api/v1/native/bundle/manifest")
    assert response.status_code == 200
    body = response.json()
    assert body["version"] == __version__
    assert body["url"] == "/api/v1/native/bundle/download"
    assert body["checksum"] == digest
    assert isinstance(body["minNativeVersion"], str)


@pytest.mark.integration
async def test_download_serves_zip(client: AsyncClient, tmp_path, monkeypatch):
    bundle = tmp_path / "bundle.zip"
    payload = b"PK\x03\x04 fake zip payload"
    bundle.write_bytes(payload)

    monkeypatch.setattr(native, "_BUNDLE_PATH", bundle)

    response = await client.get("/api/v1/native/bundle/download")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert "immutable" in response.headers["cache-control"]
    assert response.content == payload
