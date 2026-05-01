"""Validation helpers for webhook target URLs.

The dispatcher POSTs to operator-supplied URLs from inside Initiative's
network. Without a guard, a guild member could register
``http://169.254.169.254/`` (cloud metadata) or ``http://localhost:6379``
(an internal Redis) as a target — every matching event would then trigger
a server-side request to that address. Even though the response body
isn't surfaced to the caller (delivery is fire-and-log), this enables
internal port scanning and metadata-credential scraping.

The defense:

* At create/update time we resolve the hostname and reject any address
  that isn't a public unicast IP (private, loopback, link-local, etc.).
* The same check runs again immediately before delivery in case DNS
  changed underneath us (rebinding) or a previously-public hostname now
  points at internal space.

This is conservative — public DNS that resolves to multiple addresses
must have *all* of them pass. Operators who legitimately need to point a
hook at an internal address should run a public-facing relay.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse


class WebhookTargetUrlError(ValueError):
    """Raised when a target URL is structurally invalid (bad scheme,
    missing host, unparseable port, etc.)."""


class WebhookTargetUrlPrivateError(ValueError):
    """Raised when a target URL resolves to a private/loopback/link-local
    address. Distinct from :class:`WebhookTargetUrlError` so the API
    layer can return a more specific error code."""


_ALLOWED_SCHEMES = frozenset({"http", "https"})


def _is_public_address(ip: ipaddress._BaseAddress) -> bool:
    """Return True only for public unicast addresses we're willing to
    POST to. Everything else (private, loopback, link-local, multicast,
    reserved, unspecified) is blocked."""
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def assert_target_url_is_public(url: str) -> None:
    """Validate ``url`` for outbound delivery.

    Raises :class:`WebhookTargetUrlError` for malformed input,
    :class:`WebhookTargetUrlPrivateError` when the host resolves into
    private/loopback/link-local space.
    """
    parsed = urlparse(url)
    if parsed.scheme not in _ALLOWED_SCHEMES:
        raise WebhookTargetUrlError(f"unsupported scheme: {parsed.scheme!r}")
    if not parsed.hostname:
        raise WebhookTargetUrlError("missing hostname")

    host = parsed.hostname
    # IP literals are checked directly. For hostnames we resolve every A
    # / AAAA record and require every one to be public — partial coverage
    # would let an attacker include a single public IP next to internal
    # ones to slip past the check.
    try:
        literal = ipaddress.ip_address(host)
        addresses: list[ipaddress._BaseAddress] = [literal]
    except ValueError:
        try:
            infos = socket.getaddrinfo(host, None)
        except socket.gaierror as exc:
            raise WebhookTargetUrlError(f"could not resolve host {host!r}: {exc}") from exc
        addresses = []
        for family, _type, _proto, _canon, sockaddr in infos:
            if family == socket.AF_INET:
                addresses.append(ipaddress.IPv4Address(sockaddr[0]))
            elif family == socket.AF_INET6:
                # sockaddr[0] for v6 may include zone id (``fe80::1%eth0``);
                # ipaddress accepts the bare numeric form so strip it.
                addr_str = sockaddr[0].split("%", 1)[0]
                addresses.append(ipaddress.IPv6Address(addr_str))

    if not addresses:
        raise WebhookTargetUrlError(f"no usable address for host {host!r}")

    for addr in addresses:
        if not _is_public_address(addr):
            raise WebhookTargetUrlPrivateError(
                f"host {host!r} resolves to non-public address {addr}"
            )
