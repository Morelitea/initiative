"""Authenticating a service this deployment ships with.

A bundled service is named by an operator rather than installed from the
marketplace, and this authenticates the one channel it holds here. Everything
else it does with this deployment it does as a delegate, on a member's behalf,
through the app channel.

The envelope is the one its own inbound surfaces use, so the two directions are
the same shape: an HMAC over ``METHOD\\nPATH\\nTIMESTAMP\\nsha256(body)``,
which binds a signature to the exact request it was minted for rather than to a
body that could be replayed at another route.

Its own secret, separate from the app-platform registration's. The two channels
prove different things and do not share key material.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from collections.abc import Mapping

from app.core.config import settings
from app.core.messages import BundledChannelMessages

__all__ = [
    "BundledChannelError",
    "bundled_channel_enabled",
    "verify_bundled_envelope",
]

#: How far a caller's clock may be out. The same window the app channel allows.
SKEW_SECONDS = 300


class BundledChannelError(Exception):
    """The call was not one this deployment's bundled service made."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def bundled_channel_enabled() -> bool:
    """Whether an operator has named a bundled service and wired its secret."""
    return bool(
        (settings.BUNDLED_SERVICE_PUBLIC_ID or "").strip()
        and (settings.BUNDLED_SERVICE_SHARED_SECRET or "").strip()
    )


def verify_bundled_envelope(
    *, method: str, path: str, headers: Mapping[str, str], body: bytes
) -> None:
    """Check the envelope on a call from the bundled service. Pure — no DB.

    Raises :class:`BundledChannelError` with a code naming which check
    refused. Returns nothing: there is no identity to hand back, because the
    secret has exactly one holder.
    """
    if not bundled_channel_enabled():
        raise BundledChannelError(BundledChannelMessages.NOT_CONFIGURED)

    ts_header = headers.get("X-Initiative-Timestamp")
    signature = headers.get("X-Initiative-Signature")
    if not ts_header or not signature:
        raise BundledChannelError(BundledChannelMessages.MISSING_SIGNATURE)

    try:
        ts = int(ts_header)
    except ValueError as exc:
        raise BundledChannelError(BundledChannelMessages.STALE_TIMESTAMP) from exc
    if abs(time.time() - ts) > SKEW_SECONDS:
        raise BundledChannelError(BundledChannelMessages.STALE_TIMESTAMP)

    secret = (settings.BUNDLED_SERVICE_SHARED_SECRET or "").strip()
    message = f"{method}\n{path}\n{ts_header}\n{hashlib.sha256(body).hexdigest()}"
    expected = hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()
    offered = (
        signature[len("sha256=") :] if signature.startswith("sha256=") else signature
    )
    if not hmac.compare_digest(expected, offered):
        raise BundledChannelError(BundledChannelMessages.BAD_SIGNATURE)
