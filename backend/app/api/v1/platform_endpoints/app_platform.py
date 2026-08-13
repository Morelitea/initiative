"""What an app service needs from us in order to trust a call.

One public route. Initiative signs every context JWT with its own dedicated
keypair; an app has to be able to fetch the public half to verify one, and to
pick the right key out of the set while a rotation is in flight. Publishing it
is what makes rotation an operator action rather than a coordinated restart on
both sides.

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
from app.services.marketplace import context_jwt

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
