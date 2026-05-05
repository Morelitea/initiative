"""Validation helpers for webhook target URLs.

The dispatcher POSTs to operator-supplied URLs from inside Initiative's
network. Without a guard, a guild member could register
``http://169.254.169.254/`` (cloud metadata) or ``http://localhost:6379``
(an internal Redis) as a target — every matching event would then trigger
a server-side request to that address. Even though the response body
isn't surfaced to the caller (delivery is fire-and-log), this enables
internal port scanning and metadata-credential scraping.

The defense:

* Only ``https://`` is accepted by default. Plain ``http://`` lets a
  MITM strip the signature header and forge payloads at the transport
  layer, which defeats the whole point of HMAC.
* At create/update time we resolve the hostname and reject any address
  that isn't a public unicast IP (private, loopback, link-local, etc.).
* The same check runs again immediately before delivery in case DNS
  changed underneath us (rebinding) or a previously-public hostname now
  points at internal space.

The async variant (:func:`assert_target_url_is_public_async`) must be
used from any code path that runs on the event loop — :func:`socket.getaddrinfo`
is blocking and will stall every other coroutine until the resolver
returns. The sync variant exists for migrations / scripts / tests.

This is conservative — public DNS that resolves to multiple addresses
must have *all* of them pass. Operators who legitimately need to point a
hook at an internal address should run a public-facing relay.
"""

from __future__ import annotations

import asyncio
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


_ACCEPTED_SCHEMES = frozenset({"https", "http"})


def _allow_private_targets() -> bool:
    """Resolve the dev escape hatch lazily so monkeypatching ``settings``
    in tests works. Reading at call time also lets a deployed-process
    config-reload effort pick up the new value (we don't reload yet, but
    nothing here forecloses it)."""
    from app.core.config import settings

    return settings.WEBHOOK_ALLOW_PRIVATE_TARGETS


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


def _parse_and_check_scheme(url: str) -> tuple[str, str]:
    """Parse the URL and validate scheme + presence of hostname.

    With the dev flag off (production), reject anything other than
    ``https`` immediately — this preserves the structural-invalid
    error type for ``http://private-ip`` URLs (a plain ``http`` target
    is structurally wrong regardless of where it points). With the
    flag on, both ``http`` and ``https`` are tentatively accepted; the
    final scheme + address combination is decided in
    :func:`_enforce_address_policy` after DNS resolves, so we can bind
    the ``http`` allowance to private targets specifically.
    """
    parsed = urlparse(url)
    allowed = _ACCEPTED_SCHEMES if _allow_private_targets() else frozenset({"https"})
    if parsed.scheme not in allowed:
        allowed_desc = "https or http" if _allow_private_targets() else "https"
        raise WebhookTargetUrlError(
            f"unsupported scheme: {parsed.scheme!r} ({allowed_desc} required)"
        )
    if not parsed.hostname:
        raise WebhookTargetUrlError("missing hostname")
    return parsed.hostname, parsed.scheme


def _addresses_from_getaddrinfo_results(
    infos: list, host: str
) -> list[ipaddress._BaseAddress]:
    """Convert a ``getaddrinfo`` result list to a list of ``ipaddress``
    objects, stripping IPv6 zone identifiers."""
    addresses: list[ipaddress._BaseAddress] = []
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
    return addresses


def _enforce_address_policy(
    host: str,
    scheme: str,
    addresses: list[ipaddress._BaseAddress],
) -> None:
    """Apply the combined scheme + address policy to a resolved target.

    Two rules combine here:

    * **No private addresses** unless the dev escape hatch is on. The
      "any private blocks all" rule still applies — an attacker who
      publishes ``[1.1.1.1, 10.0.0.1]`` shouldn't roll the dice on
      whichever one httpx picks.
    * **No plain http to public hosts, ever.** A MITM on the way to a
      public webhook target can strip the signature and forge payloads.
      The dev flag deliberately doesn't relax this — its scope is local
      / private targets only, where there's no useful TLS to be
      between Initiative and auto.

    The matrix:

    | flag | scheme | resolves to | result |
    |------|--------|-------------|--------|
    | off  | https  | public      | accept |
    | off  | https  | private     | reject (private) |
    | off  | http   | any         | reject (http) |
    | on   | https  | public      | accept |
    | on   | https  | private     | accept |
    | on   | http   | public      | reject (http to public is forbidden) |
    | on   | http   | private     | accept (the dev case) |
    """
    has_private = any(not _is_public_address(a) for a in addresses)

    if has_private:
        if not _allow_private_targets():
            offending = next(a for a in addresses if not _is_public_address(a))
            raise WebhookTargetUrlPrivateError(
                f"host {host!r} resolves to non-public address {offending}"
            )
        # dev flag is on — http or https are both fine for private targets.
        return

    # All addresses are public.
    if scheme != "https":
        raise WebhookTargetUrlError(
            f"plain http to public host {host!r} is not permitted "
            f"(MITM would strip the signature)"
        )


def _resolve_literal_or_none(
    host: str,
) -> list[ipaddress._BaseAddress] | None:
    """If ``host`` is an IP literal, return ``[ip]``; otherwise ``None``
    so the caller can do a real DNS lookup."""
    try:
        return [ipaddress.ip_address(host)]
    except ValueError:
        return None


def assert_target_url_is_public(url: str) -> None:
    """Synchronous SSRF guard. Use only outside the event loop.

    Raises :class:`WebhookTargetUrlError` for malformed input or a
    scheme/address combination that can't be permitted (e.g. plain
    http to a public host), :class:`WebhookTargetUrlPrivateError` when
    the host resolves into private/loopback/link-local space and the
    dev flag isn't set.
    """
    host, scheme = _parse_and_check_scheme(url)
    addresses = _resolve_literal_or_none(host)
    if addresses is None:
        try:
            infos = socket.getaddrinfo(host, None)
        except socket.gaierror as exc:
            raise WebhookTargetUrlError(
                f"could not resolve host {host!r}: {exc}"
            ) from exc
        addresses = _addresses_from_getaddrinfo_results(infos, host)
    _enforce_address_policy(host, scheme, addresses)


async def assert_target_url_is_public_async(url: str) -> None:
    """Async SSRF guard for use inside coroutines.

    DNS resolution runs in a thread executor so the event loop stays
    free. Behaviour and exceptions match :func:`assert_target_url_is_public`.
    """
    host, scheme = _parse_and_check_scheme(url)
    addresses = _resolve_literal_or_none(host)
    if addresses is None:
        try:
            infos = await asyncio.to_thread(socket.getaddrinfo, host, None)
        except socket.gaierror as exc:
            raise WebhookTargetUrlError(
                f"could not resolve host {host!r}: {exc}"
            ) from exc
        addresses = _addresses_from_getaddrinfo_results(infos, host)
    _enforce_address_policy(host, scheme, addresses)
