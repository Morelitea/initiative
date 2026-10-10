"""Shared rate limiter configuration for the application."""

from dataclasses import dataclass

import anyio
from limits import RateLimitItem, parse
from slowapi import Limiter
from starlette.requests import Request

from app.core import audit_context
from app.core.config import settings
from app.core.encryption import hash_email
from app.core.identify import identify, identify_url_token

#: The counter for requests the server named no address for — the same one
#: slowapi's own key falls back to.
_NO_ADDRESS = "127.0.0.1"


def client_address_key() -> str:
    """The client address a limit counts by: the one this request's context
    holds (``app.core.audit_context``)."""
    return audit_context.client_ip() or _NO_ADDRESS


def get_user_or_ip_key(request: Request) -> str:
    """Whom a request is counted against: every limit's key.

    The account or install the request was admitted as, once its dependencies
    have run — which a route's own limit is checked after. Before then, for
    the server-wide default, whoever its credential names as far as can be
    told without the database (``app.core.identify``): a session, an upload
    token, an installed plug-in. Everybody behind a shared address gets their own
    allowance that way. The client address for the rest: no credential, one
    only the database can name (an API key), or one that failed its check.
    """
    install = getattr(request.state, "plugin_install", None)
    if install is not None:
        client_id, guild_id, install_id = install
        return f"install:{client_id}:{guild_id}:{install_id}"
    user_id = getattr(request.state, "user_id", None)
    if user_id is not None:
        return f"user:{user_id}"
    identified = identify(request) or identify_url_token(request)
    if identified is not None and (key := identified.limit_key) is not None:
        return key
    return client_address_key()


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


def build_limiter(storage_uri: str) -> Limiter:
    """The limiter, counting in ``storage_uri``.

    While that storage cannot be reached, each process counts the same limits
    in its own memory, and goes back to the storage once it answers again.
    """
    return Limiter(
        key_func=get_user_or_ip_key,
        default_limits=_default_limits(),
        storage_uri=storage_uri,
        in_memory_fallback_enabled=True,
    )


# Shared limiter instance - import this in endpoints. The default limit and the
# counter storage backend are both settings-driven so a multi-worker deployment
# can point at Redis (RATE_LIMIT_STORAGE_URI) or relax/disable the global default
# (RATE_LIMIT_DEFAULT) with no code change.
limiter = build_limiter(settings.RATE_LIMIT_STORAGE_URI)

# Master kill-switch for local dev/testing. When RATE_LIMIT_ENABLED is False the
# limiter short-circuits every check (global default *and* per-route decorators),
# exactly as the test suite does. Defaults True, so shared/prod deployments are
# unaffected unless the operator explicitly opts out via env.
limiter.enabled = settings.RATE_LIMIT_ENABLED


@dataclass
class AddressAllowance:
    """A count kept per email address, from any number of clients.

    Asked of the address as typed in, whether or not an account holds it, so
    the answer is the same either way. The counter store holds a keyed digest
    of the address, never the address.
    """

    namespace: str
    limit: RateLimitItem

    def _key(self, address: str) -> str:
        # The address's lookup digest, at the length the counters have always
        # been keyed by.
        return hash_email(address)[:32]

    async def left(self, address: str) -> bool:
        """Whether the address has anything left in the current window."""
        return await allowance_left(self.limit, self.namespace, self._key(address))

    async def take(self, address: str) -> bool:
        """Count one against the address; whether it was within the allowance."""
        return await take_allowance(self.limit, self.namespace, self._key(address))

    async def clear(self, address: str) -> None:
        """Start the address's count over."""
        if not limiter.enabled:
            return
        await anyio.to_thread.run_sync(
            limiter.limiter.clear, self.limit, self.namespace, self._key(address)
        )


#: Refused password sign-ins one address may collect before a password is not
#: checked for it for the rest of the window. The same numbers as the account
#: lock in ``app.services.auth.sign_in_locks``, counted by the address typed
#: in, so an address nobody holds runs out the same way. Cleared when its
#: holder signs in or a lock on it is lifted.
SIGN_IN_FAILURES = AddressAllowance("sign-in-address", parse("5/15minutes"))
#: Letters one address may be sent in one window: sign-in codes and password
#: resets together. Taken for every address typed in, held or not.
MAIL_SENDS = AddressAllowance("mail-address", parse("5/15minutes"))


#: Requests to act as a member one install may send, answered or repeated, in
#: one window. Counted by the install.
CONSENT_REQUESTS_PER_INSTALL = parse("30/minute")
#: New requests one install may make of one member in one window. A repeat of
#: one already made notifies nobody and does not count.
NEW_CONSENT_REQUESTS_PER_MEMBER = parse("5/hour")


#: Calls one install may make to other plug-ins through Initiative in one window,
#: to every plug-in together.
PLUGIN_HUB_CALLS_PER_INSTALL = parse("120/minute")
#: Calls one install may make to one other plug-in in one window.
PLUGIN_HUB_CALLS_PER_TARGET = parse("60/minute")
#: A plug-in's actions one member may run in one community in one window,
#: counted per install.
PLUGIN_ACTIONS_PER_MEMBER = parse("30/minute")


async def take_allowance(item: RateLimitItem, namespace: str, key: str) -> bool:
    """Count one against ``key`` under ``item``; whether it was within the
    allowance. Always ``True`` with the limiter switched off."""
    if not limiter.enabled:
        return True
    return await anyio.to_thread.run_sync(limiter.limiter.hit, item, namespace, key)


async def allowance_left(item: RateLimitItem, namespace: str, key: str) -> bool:
    """Whether ``key`` has anything left under ``item``, counting nothing."""
    if not limiter.enabled:
        return True
    return await anyio.to_thread.run_sync(limiter.limiter.test, item, namespace, key)
