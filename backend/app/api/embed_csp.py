"""The frame policy carried by the documents this deployment serves.

An embedded app runs in a cross-origin iframe, which the app-wide
``Content-Security-Policy`` forbids by default. The permission comes from the
deployment's own registrations: ``app_service_registrations`` is the operator's
trusted-site list, and the live ones' origins are what ``frame-src`` names.

An origin reaches that list one way — an operator wires up an app service, and
that service's handshake confirms the manifest it serves. So the header
describes what this deployment runs. It names no guild, no install and no
reader, and it is the same header on every document, which is what makes it
answerable without a session and stable for as long as the operator's
configuration is.

The kill switch reaches it too: a registration that is stopped, or whose last
verification found a different manifest behind it, is not live, and its origins
leave the header within the registration cache's TTL.

``connect-src`` is untouched — an app's data reaches the browser same-origin
through the proxy.
"""

from __future__ import annotations

import logging
from functools import lru_cache

from app.core.config import settings
from app.services.marketplace import registration_lookup

logger = logging.getLogger(__name__)

__all__ = ["app_frame_policy"]


async def app_frame_policy() -> str:
    """The policy for a served document: the app-wide one, admitting the frame
    origins this deployment's live registrations name.

    Deliberately fail-soft: a document is served either way, and the fallback is
    the stricter policy. Nothing here is allowed to cost a page load, so an
    unexpected failure is logged and the caller carries on.
    """
    try:
        origins = await registration_lookup.frame_origins()
    except Exception:
        logger.warning("embed CSP: could not read the frame origins", exc_info=True)
        return settings.content_security_policy
    return _policy_for(origins)


@lru_cache(maxsize=8)
def _policy_for(origins: tuple[str, ...]) -> str:
    """The assembled header for one set of origins.

    Built once per distinct set rather than once per document: the set changes
    only when an operator changes a registration, and the string is the same
    every time until they do.
    """
    return settings.content_security_policy_with_frames(origins)
