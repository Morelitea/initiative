"""Tests for the app service registration handshake.

Every case runs against an injected ``httpx.MockTransport``, and the base URL is
a loopback literal so target resolution never leaves the process.
"""

import hashlib
import hmac
import json

import httpx
import pytest

from app.core.messages import AppServiceMessages
from app.models.platform.app_service_registration import AppServiceStatus
from app.services.marketplace import handshake as handshake_service
from app.services.marketplace.handshake import (
    APP_PROTOCOL_VERSION,
    HandshakeError,
    canonical_manifest_hash,
    perform_handshake,
)

pytestmark = pytest.mark.unit

BASE_URL = "http://127.0.0.1:9100"
SECRET = "shared-secret-value"

MANIFEST = {
    "uid": "K7M2QX8N4TVB9C",
    "public_id": "acme.widgets",
    "kind": "app",
    "name": "Widgets",
    "protocol_version": APP_PROTOCOL_VERSION,
    "definition": {"app_kind": "tool_instance", "tool": "calendar"},
}


def _sign(secret: str, challenge: str) -> str:
    return hmac.new(
        secret.encode("utf-8"), challenge.encode("utf-8"), hashlib.sha256
    ).hexdigest()


def make_transport(
    *,
    manifest: dict | None = None,
    manifest_bytes: bytes | None = None,
    manifest_status: int = 200,
    sign_with: str = SECRET,
    raise_on_manifest: Exception | None = None,
) -> httpx.MockTransport:
    """An app service that answers both wire endpoints.

    ``sign_with`` is the secret the fake app signs the challenge with, so a
    mismatch is expressed by handing it a different one.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("initiative-app.json"):
            if raise_on_manifest is not None:
                raise raise_on_manifest
            if manifest_bytes is not None:
                return httpx.Response(manifest_status, content=manifest_bytes)
            body = MANIFEST if manifest is None else manifest
            return httpx.Response(manifest_status, json=body)
        if request.url.path.endswith("/v1/handshake"):
            challenge = json.loads(request.content)["challenge"]
            return httpx.Response(200, json={"signature": _sign(sign_with, challenge)})
        return httpx.Response(404)

    return httpx.MockTransport(handler)


async def test_handshake_succeeds_and_reports_the_manifest():
    result = await perform_handshake(
        base_url=BASE_URL, secret=SECRET, transport=make_transport()
    )

    assert result.public_id == "acme.widgets"
    assert result.listing_uid == "K7M2QX8N4TVB9C"
    assert result.protocol_version == APP_PROTOCOL_VERSION
    assert result.manifest_hash == canonical_manifest_hash(MANIFEST)


async def test_manifest_hash_ignores_key_order_and_whitespace():
    """Re-serving the same content formatted differently is not a change."""
    reordered = dict(reversed(list(MANIFEST.items())))
    assert canonical_manifest_hash(reordered) == canonical_manifest_hash(MANIFEST)


async def test_signature_mismatch_is_reported_as_such():
    with pytest.raises(HandshakeError) as excinfo:
        await perform_handshake(
            base_url=BASE_URL,
            secret=SECRET,
            transport=make_transport(sign_with="a-different-secret"),
        )

    assert excinfo.value.code == AppServiceMessages.SIGNATURE_MISMATCH
    assert excinfo.value.status == AppServiceStatus.SIGNATURE_MISMATCH


async def test_unreachable_host_is_reported_as_unreachable():
    transport = make_transport(raise_on_manifest=httpx.ConnectError("refused"))

    with pytest.raises(HandshakeError) as excinfo:
        await perform_handshake(base_url=BASE_URL, secret=SECRET, transport=transport)

    assert excinfo.value.code == AppServiceMessages.UNREACHABLE
    assert excinfo.value.status == AppServiceStatus.UNREACHABLE


async def test_error_status_is_reported_as_unreachable():
    with pytest.raises(HandshakeError) as excinfo:
        await perform_handshake(
            base_url=BASE_URL,
            secret=SECRET,
            transport=make_transport(manifest_status=500),
        )

    assert excinfo.value.code == AppServiceMessages.UNREACHABLE


async def test_oversized_manifest_is_refused(monkeypatch):
    """The response is read as a bounded stream, so a service that answers with
    something enormous costs the cap and not the caller."""
    monkeypatch.setattr(handshake_service, "_MANIFEST_MAX_BYTES", 1024)
    oversized = json.dumps({**MANIFEST, "name": "x" * 4096}).encode("utf-8")

    with pytest.raises(HandshakeError) as excinfo:
        await perform_handshake(
            base_url=BASE_URL,
            secret=SECRET,
            transport=make_transport(manifest_bytes=oversized),
        )

    assert excinfo.value.code == AppServiceMessages.UNREACHABLE
    assert "exceeded" in excinfo.value.detail


async def test_non_json_manifest_is_refused():
    with pytest.raises(HandshakeError) as excinfo:
        await perform_handshake(
            base_url=BASE_URL,
            secret=SECRET,
            transport=make_transport(manifest_bytes=b"<html>not json</html>"),
        )

    assert excinfo.value.code == AppServiceMessages.UNREACHABLE


async def test_unknown_protocol_version_is_refused():
    with pytest.raises(HandshakeError) as excinfo:
        await perform_handshake(
            base_url=BASE_URL,
            secret=SECRET,
            transport=make_transport(
                manifest={**MANIFEST, "protocol_version": APP_PROTOCOL_VERSION + 99}
            ),
        )

    assert excinfo.value.code == AppServiceMessages.INVALID_MANIFEST
    assert excinfo.value.status == AppServiceStatus.MANIFEST_MISMATCH


async def test_definition_the_validator_refuses_is_reported():
    """The served definition goes through the same validator an authored one
    does, so an app cannot publish a body the app itself could not."""
    with pytest.raises(HandshakeError) as excinfo:
        await perform_handshake(
            base_url=BASE_URL,
            secret=SECRET,
            transport=make_transport(
                manifest={
                    **MANIFEST,
                    "definition": {"app_kind": "tool_instance", "tool": "nonsense"},
                }
            ),
        )

    assert excinfo.value.code == AppServiceMessages.INVALID_MANIFEST


async def test_manifest_without_public_id_is_refused():
    body = {k: v for k, v in MANIFEST.items() if k != "public_id"}

    with pytest.raises(HandshakeError) as excinfo:
        await perform_handshake(
            base_url=BASE_URL, secret=SECRET, transport=make_transport(manifest=body)
        )

    assert excinfo.value.code == AppServiceMessages.INVALID_MANIFEST


async def test_wrapped_manifest_document_is_accepted():
    """An app kit that wraps the manifest is read the same as one that does
    not — the validation and the hash apply to the manifest either way."""
    wrapped = {"protocol_version": APP_PROTOCOL_VERSION, "manifest": MANIFEST}

    result = await perform_handshake(
        base_url=BASE_URL, secret=SECRET, transport=make_transport(manifest=wrapped)
    )

    assert result.manifest_hash == canonical_manifest_hash(MANIFEST)
