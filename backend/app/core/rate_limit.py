"""Shared rate limiter configuration for the application."""

from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request


def get_real_client_ip(request: Request) -> str:
    """
    Get the real client IP address, accounting for proxies.

    Checks X-Forwarded-For header first (set by reverse proxies),
    falls back to direct client IP.
    """
    # X-Forwarded-For may contain multiple IPs: client, proxy1, proxy2, ...
    # The first one is the original client
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        # Take the first IP (original client)
        return forwarded_for.split(",")[0].strip()

    # X-Real-IP is another common header set by nginx
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip.strip()

    # Fall back to direct connection IP
    return get_remote_address(request)


# Shared limiter instance - import this in endpoints
limiter = Limiter(key_func=get_real_client_ip, default_limits=["100/minute"])
