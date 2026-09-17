"""Ask an identity provider what it offers, before anybody tries to sign in.

Setting a provider up means copying four or five values between two screens,
and until now the first sign that one of them was wrong was a failed login —
with the reason in a server log the person who typed it cannot read. This
answers the same question at the moment they type it: is anything there, is it
the issuer you named, and what does it say it supports.

What comes back is parsed and named. The raw document does not leave here, and
neither does the upstream status; a failure collapses to one of the codes in
:class:`~app.core.messages.AuthProviderMessages`, with the detail going to the
log for whoever runs the deployment.

The reach is the login flow's: https only, under
:mod:`app.services.auth.oidc._http`'s size cap and timeout. Verify therefore
never refuses an address that signing in would accept, which is the point of
checking it here.

Discovery is fetched through a client of this module's own, built per probe, so
a probe reports what is there now and an address somebody typed never lands in
the cache the login path reads.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, replace

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.messages import AuthProviderMessages
from app.services.auth import provider_registry
from app.services.auth.oidc._http import ClientFactory
from app.services.auth.oidc.discovery import (
    DiscoveryError,
    OidcDiscovery,
    OidcMetadata,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProbeResult:
    """What one look at a provider found."""

    ok: bool
    error_code: str | None = None
    issuer: str | None = None
    authorization_endpoint: str | None = None
    token_endpoint: str | None = None
    jwks_uri: str | None = None
    userinfo_endpoint: str | None = None
    signing_algs: list[str] = field(default_factory=list)
    scopes_supported: list[str] = field(default_factory=list)
    claims_supported: list[str] = field(default_factory=list)
    callback_url_template: str = ""

    @classmethod
    def failed(cls, error_code: str) -> ProbeResult:
        return cls(ok=False, error_code=error_code)

    @classmethod
    def found(cls, metadata: OidcMetadata) -> ProbeResult:
        return cls(
            ok=True,
            issuer=metadata.issuer,
            authorization_endpoint=metadata.authorization_endpoint,
            token_endpoint=metadata.token_endpoint,
            jwks_uri=metadata.jwks_uri,
            userinfo_endpoint=metadata.userinfo_endpoint,
            signing_algs=list(metadata.id_token_signing_alg_values_supported or ()),
            scopes_supported=list(metadata.scopes_supported or ()),
            claims_supported=list(metadata.claims_supported or ()),
        )


def fresh_discovery(*, client_factory: ClientFactory | None = None) -> OidcDiscovery:
    """A discovery client that keeps nothing.

    Two things follow from the zero TTL and the separate instance: testing a
    saved provider reports what answers now rather than what answered an hour
    ago, and an address typed into the form is looked up without being written
    where the login path would find it.

    ``client_factory`` is the seam tests reach for, so they exercise this
    construction rather than one of their own.
    """
    return OidcDiscovery(cache_ttl_seconds=0, client_factory=client_factory)


def _error_code_for(exc: DiscoveryError) -> str:
    """Which of the three the caller is told.

    Discovery raises one error for every way this can go wrong, and the three
    outcomes worth telling apart are: nothing answered, something answered for
    a different issuer, and something answered that is not a discovery
    document. The wording is discovery's own, so it is matched rather than
    re-derived.
    """
    detail = str(exc)
    if detail.startswith("discovery fetch failed"):
        return AuthProviderMessages.DISCOVERY_UNREACHABLE
    if "does not match" in detail:
        return AuthProviderMessages.DISCOVERY_ISSUER_MISMATCH
    return AuthProviderMessages.DISCOVERY_INVALID


async def probe_issuer(
    issuer: str, *, discovery: OidcDiscovery | None = None
) -> ProbeResult:
    """Look up ``issuer`` and report what it offers.

    A pasted ``.well-known`` URL is accepted — discovery trims it — so the
    address somebody copied out of their provider's docs works as typed.

    Only the operator reaches here: a community connects to a provider rather
    than describing one, so it names no address to look up. The callback
    template rides along whether the look-up succeeded or not, because
    somebody whose address did not answer is still mid-setup and still needs
    it.
    """
    client = discovery or fresh_discovery()
    template = provider_registry.provider_callback_url("{slug}")
    try:
        metadata = await client.fetch(issuer)
    except DiscoveryError as exc:
        code = _error_code_for(exc)
        logger.info("provider probe of %s reported %s: %s", issuer, code, exc)
        return replace(ProbeResult.failed(code), callback_url_template=template)
    return replace(ProbeResult.found(metadata), callback_url_template=template)


async def probe_provider(
    session: AsyncSession,
    provider_id: int,
    *,
    discovery: OidcDiscovery | None = None,
) -> ProbeResult:
    """Look up a saved provider's own issuer.

    The address comes off the row, never off the request, so this reports on
    the provider as configured.
    """
    row = await provider_registry.editable_provider(session, provider_id)
    if not row.issuer:
        return ProbeResult.failed(AuthProviderMessages.DISCOVERY_NO_ISSUER)
    return await probe_issuer(row.issuer, discovery=discovery)
