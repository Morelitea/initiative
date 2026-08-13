"""Helpers for driving the app-service channel in tests.

An app service authenticates by signing its request, so a test that wants to
*be* an app has to sign like one. These build the same headers the app-kit will,
through the same :func:`~app.services.marketplace.app_channel_auth.sign_request`
the verifier is written against — so a test cannot pass by agreeing with a
second, private idea of the scheme.
"""

from __future__ import annotations

import json
import secrets
import time
from typing import Any, Optional

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.encryption import SALT_APP_SERVICE_SECRET, encrypt_field
from app.models.platform.app_service_registration import (
    AppServiceRegistration,
    AppServiceStatus,
)
from app.services.marketplace.app_channel_auth import (
    APP_HEADER,
    NONCE_HEADER,
    SIGNATURE_HEADER,
    TIMESTAMP_HEADER,
    sign_request,
)

__all__ = [
    "APP_CHANNEL_SECRET",
    "channel_headers",
    "encode_body",
    "register_app_service",
]

#: The shared secret a test registration is wired with.
APP_CHANNEL_SECRET = "app-channel-shared-secret"


async def register_app_service(
    session: AsyncSession,
    *,
    public_id: str = "tests.shop",
    listing_uid: str = "TESTAPP0000001",
    secret: Optional[str] = APP_CHANNEL_SECRET,
    base_url: str = "http://127.0.0.1:9300",
    enabled: bool = True,
    **overrides: Any,
) -> AppServiceRegistration:
    """A registration wired the way a verified handshake would leave one.

    ``listing_uid`` is what a handshake records, and it is what ties the
    registration to the installs it may reach — a registration created with
    ``listing_uid=None`` models one that has never verified.
    """
    row = AppServiceRegistration(
        public_id=public_id,
        listing_uid=listing_uid,
        base_url=base_url,
        allowed_origins=[base_url],
        secret_encrypted=(
            encrypt_field(secret, SALT_APP_SERVICE_SECRET) if secret else None
        ),
        enabled=enabled,
        status=overrides.pop("status", AppServiceStatus.OK),
        **overrides,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


def encode_body(payload: Any) -> bytes:
    """Serialize a request body the way a client would send it.

    The signature covers the exact bytes, so a test has to sign and send the
    same ones — which means building them once here rather than letting the
    HTTP client re-serialize.
    """
    if payload is None:
        return b""
    return json.dumps(payload, separators=(",", ":")).encode("utf-8")


def channel_headers(
    *,
    method: str,
    path: str,
    body: bytes = b"",
    secret: str = APP_CHANNEL_SECRET,
    public_id: str = "tests.shop",
    timestamp: Optional[int] = None,
    nonce: Optional[str] = None,
) -> dict[str, str]:
    """The signing headers for one request.

    ``path`` is the full request path, ``/api/v1/app-service/…``, because that is
    what the server sees and therefore what both sides sign.
    """
    stamp = str(int(time.time()) if timestamp is None else timestamp)
    value = nonce or secrets.token_urlsafe(12)
    headers = {
        APP_HEADER: public_id,
        TIMESTAMP_HEADER: stamp,
        NONCE_HEADER: value,
        SIGNATURE_HEADER: sign_request(
            secret,
            method=method,
            path=path,
            timestamp=stamp,
            nonce=value,
            body=body,
        ),
    }
    if body:
        headers["Content-Type"] = "application/json"
    return headers
