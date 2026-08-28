"""Endpoints an app service calls back into Initiative on.

A third family beside ``platform_endpoints/`` and ``tenant_endpoints/``, split
out by *who calls* rather than by what the data is: no user is ever resolved
here, and no session cookie or bearer token is read. The caller is an external
container proving it holds its registration's shared secret, and everything it
may reach follows from which registration that is.

The channels, all under ``/api/v1/app-service``:

* ``GET /installs`` — which guilds have this app, at which pinned version.
* ``GET /installs/{guild_id}/config`` — the decrypted configuration for one
  install. The custody channel: the one place stored plaintext leaves.
* ``GET /installs/{guild_id}/connections`` — the app's per-member connections,
  by opaque reference, with status only.
* ``PUT /installs/{guild_id}/connections/{connection_ref}`` — what a vendor flow
  produced, written back into the platform's custody. The handle says which of
  two things it was: a member's own credential, or the one the whole guild uses
  and a guild admin obtained.
* ``POST /installs/{guild_id}/status`` — the app's verdict on the configuration
  it was handed.
* ``POST /events`` — third-party events, re-emitted through the dispatcher the
  automation delegate already subscribes to.

Ingress is one-way. Apps emit events and never subscribe: delivery targets
belong to the automation delegate, and nothing here creates one.
"""

from fastapi import APIRouter

from app.api.v1.app_service_endpoints import events, installs

# Not part of the OpenAPI document: this surface is consumed by app containers
# implementing the app protocol, never by the SPA, and the generated frontend
# client has no business carrying a channel no browser may call.
router = APIRouter(include_in_schema=False)
router.include_router(installs.router)
router.include_router(events.router)

__all__ = ["router"]
