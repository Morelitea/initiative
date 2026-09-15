"""Shared rate limiter configuration for the application."""

import ipaddress
import logging
import time

from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request

from app.core.config import settings

logger = logging.getLogger(__name__)

#: How often the configuration hint below repeats. It describes a setting, so
#: it is worth saying while the setting is still that way, and worth saying no
#: more often than somebody would act on it.
_FORWARDED_HINT_INTERVAL_SECONDS = 3600
_forwarded_hint_at: float | None = None


def _is_local_network_peer(address: str) -> bool:
    """Whether the request arrived from this deployment's own network — a
    container network, a private LAN, the host itself."""
    try:
        parsed = ipaddress.ip_address(address.split("%", 1)[0])
    except ValueError:
        return False
    return parsed.is_private or parsed.is_loopback or parsed.is_link_local


def _note_ignored_forwarded_header(request: Request, resolved: str) -> None:
    """Note, occasionally, that ``X-Forwarded-For`` is arriving and not being
    read.

    Uvicorn reads that header only from a peer named in
    ``--forwarded-allow-ips`` (``127.0.0.1`` unless told otherwise, which is
    what ``BEHIND_PROXY=true`` does), so a reverse proxy anywhere else leaves
    every visitor resolving to the proxy's address rather than their own.
    Nothing else reports that, so this does.

    It is a hint about configuration and nothing more: the header decides
    nothing here, and this changes no behaviour.
    """
    global _forwarded_hint_at
    now = time.monotonic()
    if (
        _forwarded_hint_at is not None
        and now - _forwarded_hint_at < _FORWARDED_HINT_INTERVAL_SECONDS
    ):
        return
    forwarded = request.headers.get("x-forwarded-for")
    if not forwarded:
        return
    # A hop that was read leaves the resolved address somewhere in the chain the
    # header names; one that was not leaves the peer itself, which is not.
    if resolved in {hop.strip() for hop in forwarded.split(",")}:
        return
    if not _is_local_network_peer(resolved):
        return
    _forwarded_hint_at = now
    logger.warning(
        "Requests carry X-Forwarded-For but this peer is not configured as a "
        "trusted proxy, so every client resolves to %s. Set BEHIND_PROXY=true "
        "(and FORWARDED_ALLOW_IPS to the proxy's address) so rate limits and "
        "recorded sign-in addresses are per-visitor.",
        resolved,
    )


def get_real_client_ip(request: Request) -> str:
    """Return the client address selected by the configured ASGI server.

    Uvicorn resolves ``request.client`` from its own ``FORWARDED_ALLOW_IPS``
    configuration before the application sees the request, so the address is
    already whatever the deployment's proxy configuration says it is.
    """
    resolved = get_remote_address(request)
    _note_ignored_forwarded_header(request, resolved)
    return resolved


def get_inet_client_ip(request: Request) -> str | None:
    """The client IP as a value an INET column accepts, or ``None`` when it
    isn't a parseable address (e.g. the ``testclient`` peer). Guards session
    bookkeeping writes from faulting on a non-IP host string.

    The address is normalized, and any IPv6 zone identifier is dropped because
    Postgres ``inet`` stores network addresses without an interface scope.
    """
    raw = get_real_client_ip(request)
    # A zone identifies a local interface and is not meaningful in stored data.
    candidate = raw.split("%", 1)[0]
    try:
        parsed = ipaddress.ip_address(candidate)
    except ValueError:
        return None
    return str(parsed)


def _default_limits() -> list[str]:
    """Build the global default-limit list from settings.

    ``RATE_LIMIT_DEFAULT`` is a slowapi/limits string (e.g. ``"100/minute"``);
    an empty/whitespace value disables the global default entirely. We must NOT
    pass an empty string into ``Limiter`` — slowapi eagerly parses each entry and
    ``""`` raises ``ValueError`` — so an unset value yields an empty list, which
    slowapi treats as "no default limit". Per-route ``@limiter.limit(...)``
    decorators are unaffected either way.
    """
    raw = settings.RATE_LIMIT_DEFAULT.strip()
    return [raw] if raw else []


# Shared limiter instance - import this in endpoints. The default limit and the
# counter storage backend are both settings-driven so a multi-worker deployment
# can point at Redis (RATE_LIMIT_STORAGE_URI) or relax/disable the global default
# (RATE_LIMIT_DEFAULT) with no code change.
limiter = Limiter(
    key_func=get_real_client_ip,
    default_limits=_default_limits(),
    storage_uri=settings.RATE_LIMIT_STORAGE_URI,
)

# Master kill-switch for local dev/testing. When RATE_LIMIT_ENABLED is False the
# limiter short-circuits every check (global default *and* per-route decorators),
# exactly as the test suite does. Defaults True, so shared/prod deployments are
# unaffected unless the operator explicitly opts out via env.
limiter.enabled = settings.RATE_LIMIT_ENABLED
