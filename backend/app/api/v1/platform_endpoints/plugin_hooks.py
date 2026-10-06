"""Where a vendor sends an app's webhooks.

``POST /plugin-hooks/{public_id}`` — one address per app on this deployment, the
one the operator gives the vendor. It takes no credential of ours: a delivery
is admitted by its signature, under the vendor secret the operator supplied,
and routed to the communities that connected the vendor installation it names
(:mod:`app.services.tenant.plugin_hooks`).

The body is capped at 1 MiB at the transport (``app.core.body_limit``) and the
address has its own rate limits: per app and sending address, and a higher
one per app.

Not part of the OpenAPI document: only a vendor calls it.
"""

from __future__ import annotations

from fastapi import APIRouter, Request, Response

from app.core.rate_limit import get_real_client_ip, limiter
from app.services.tenant import plugin_hooks as plugin_hooks_service

router = APIRouter(include_in_schema=False)


def _per_plugin(request: Request) -> str:
    """Deliveries to one app, from anywhere."""
    return f"plugin-hooks:{request.path_params.get('public_id', '')}"


def _per_plugin_and_sender(request: Request) -> str:
    """Deliveries to one app from one address."""
    return f"{_per_plugin(request)}:{get_real_client_ip(request)}"


@router.post("/{public_id}")
@limiter.limit("600/minute", key_func=_per_plugin_and_sender)
@limiter.limit("6000/minute", key_func=_per_plugin)
async def receive_plugin_hook(public_id: str, request: Request) -> Response:
    """One vendor delivery: 202 when every community it belongs to has it, 401
    when its signature does not verify, 502 when a community's app did not
    accept it, so the vendor delivers it again."""
    status_code = await plugin_hooks_service.receive(
        public_id,
        {name.lower(): value for name, value in request.headers.items()},
        await request.body(),
    )
    return Response(status_code=status_code)
