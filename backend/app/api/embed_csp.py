"""The frame policy carried by the documents this deployment serves.

An embedded plug-in runs in a cross-origin iframe, which the app-wide
``Content-Security-Policy`` forbids by default. The permission comes from the
deployment's own registrations: ``plugin_service_registrations`` is the operator's
trusted-site list, and the live ones' origins are what ``frame-src`` names.

An origin reaches that list one way — an operator wires up a plug-in service. So
the header describes what this deployment runs. It names no guild, no install and no
reader, and it is the same header on every document, which is what makes it
answerable without a session and stable for as long as the operator's
configuration is.

The kill switch reaches it too: a registration that is stopped, whose
publisher is stopped, or that has no key set is not live, and its origins leave
the header within the registration cache's TTL.

``connect-src`` is untouched — a plug-in's data reaches the browser same-origin
through the proxy.
"""

from __future__ import annotations

import logging
from functools import lru_cache

from app.core.config import settings
from app.services import captcha_config
from app.services.marketplace import registration_lookup

logger = logging.getLogger(__name__)

__all__ = ["content_security_policy", "plugin_frame_policy"]


async def plugin_frame_policy() -> str:
    """The policy for a served document: the app-wide one, admitting the frame
    origins this deployment's live registrations name.

    Deliberately fail-soft: a document is served either way, and the fallback is
    the stricter policy. Nothing here is allowed to cost a page load, so an
    unexpected failure is logged and the caller carries on.
    """
    captcha_provider = captcha_config.current_captcha_config().provider
    try:
        origins = await registration_lookup.frame_origins()
    except Exception:
        logger.warning("embed CSP: could not read the frame origins", exc_info=True)
        origins = ()
    return content_security_policy(captcha_provider, origins)


@lru_cache(maxsize=8)
def content_security_policy(
    captcha_provider: str | None, frame_origins: tuple[str, ...] = ()
) -> str:
    """The assembled header for one captcha provider and set of frame origins.

    Built once per distinct pair rather than once per response: the provider
    lives in the settings row and the origins change only when an operator
    changes a registration, and the string is the same every time until they
    do. With no origins it is the app-wide policy every response carries.
    """
    return settings.content_security_policy_with_frames(
        frame_origins, captcha_provider=captcha_provider
    )
