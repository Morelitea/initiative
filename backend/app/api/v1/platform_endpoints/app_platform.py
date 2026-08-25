"""What an app service needs from us in order to trust a call.

Two public routes, one per kind of caller an app hears from. Initiative signs
every context JWT with its own dedicated keypair; an app has to be able to
fetch the public half to verify one, and to pick the right key out of the set
while a rotation is in flight. Delegates sign their own tokens with keys the
operator provisioned on their registrations, and an app verifying one of those
needs the public halves the same way — addressed per delegate, because a key
set belongs to one signer. Publishing both is what makes rotation an operator
action rather than a coordinated restart on both sides.

Unauthenticated by design — a public key is public, and requiring a credential
to fetch the key used to check a credential is a loop with no starting point.
Platform-addressed like the catalog: signing is deployment configuration and
names no guild.
"""

from typing import Any

from fastapi import APIRouter, HTTPException, status

from app.core.messages import AppServiceMessages
from app.core.security import (
    AppPlatformSigningNotConfiguredError,
    app_platform_signing_enabled,
)
from app.services.marketplace import context_jwt, registration_lookup

router = APIRouter()


@router.get("/jwks.json")
async def read_app_platform_jwks() -> dict[str, Any]:
    """The public half of the app-platform signing key, as a JWKS document.

    A deployment with no keypair configured answers **503** rather than an empty
    key set. The two are very different statements: an empty ``keys`` array says
    "this platform has published no keys", which an app would reasonably cache
    and then refuse every later token against. A 503 says the platform is not
    configured for app traffic yet, which is what is actually true, and it is
    the same answer registering and verifying an app service already give.
    """
    if not app_platform_signing_enabled():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=AppServiceMessages.SIGNING_NOT_CONFIGURED,
        )
    try:
        return context_jwt.context_jwks()
    except (AppPlatformSigningNotConfiguredError, context_jwt.ContextTokenError) as exc:
        # Configured but unusable — an unreadable or non-RSA key. Reported the
        # same way as absent, because from an app's side it is the same state.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=AppServiceMessages.SIGNING_NOT_CONFIGURED,
        ) from exc


@router.get("/delegates/{public_id}/jwks.json")
async def read_delegate_jwks(public_id: str) -> dict[str, Any]:
    """One delegate's public verification keys, as a JWKS document.

    What an app checks a delegate-signed token against. Addressed per delegate
    rather than served as one merged set, because a ``kid`` is only unique
    within the registration that published it: two delegates may pick the same
    label, and a consumer selecting one key per ``kid`` out of a merged
    document would reject calls that are perfectly valid. One issuer, one key
    set — Initiative's own verification handles the collision by trying every
    candidate, which is not something a JWKS consumer does.

    Served for registrations that are enabled and hold the ``delegation``
    grant — the same rule that resolves a token — so an operator's edit reaches
    this and verification alike within the registration cache TTL. Anything
    else is a 404: a delegate that is switched off or never held the grant
    publishes nothing here, and saying which of those it is would describe the
    deployment's wiring to an unauthenticated caller.

    No 503 leg, unlike the signing key above: an enabled delegate with no key
    provisioned yet has genuinely published no keys, and an empty ``keys``
    array is what a caller should cache for it.
    """
    document = await registration_lookup.delegate_jwks(public_id)
    if document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=AppServiceMessages.NOT_FOUND,
        )
    return document
