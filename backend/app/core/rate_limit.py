"""Shared rate limiter configuration for the application."""

from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request

from app.core.config import settings


def get_real_client_ip(request: Request) -> str:
    """
    Get the real client IP address, accounting for proxies.

    Only trusts X-Forwarded-For/X-Real-IP headers when BEHIND_PROXY=True,
    preventing header spoofing when directly exposed to the internet.
    """
    if settings.BEHIND_PROXY:
        # X-Forwarded-For may contain multiple IPs: client, proxy1, proxy2, ...
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()

        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip.strip()

    # Direct connection IP (or BEHIND_PROXY not set)
    return get_remote_address(request)


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
