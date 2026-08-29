"""Third-party events entering the platform through an app.

The shape of the trip: a vendor calls the app service, the app verifies that
vendor's own signature and works out which of its installs the event belongs to,
then posts it here. Initiative adds the half only it can — the event type is one
the *pinned* definition declares, namespaced under the calling app, and the
guild named has that app installed and switched on — and re-emits it through the
dispatcher that already exists.

Re-emitting rather than forwarding is what keeps one inbound trust relationship
for the automation delegate: from the dispatcher on, an app's event is an
ordinary event, matched by the same subscriptions and deduped in the same place
as a task or a document change.

**Ingress is one-way.** Apps emit; they never subscribe. Delivery targets are
created and modified only by the automation delegate, so there is nothing on
this router that registers one.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status

from app.api.v1.app_service_endpoints.deps import (
    AdminSessionDep,
    CallerDep,
    parse_body,
    raw_body,
    to_http,
)
from app.core.messages import AppChannelMessages
from app.schemas.tenant.app_channel import AppEventIngest
from app.services.tenant import app_channels as channels_service
from app.services.tenant.app_channels import (
    MAX_EVENT_PAYLOAD_BYTES,
    AppChannelError,
)

router = APIRouter()

#: The whole request, with room for the envelope around a payload already capped
#: at :data:`MAX_EVENT_PAYLOAD_BYTES`. Checked against the bytes the signature
#: covered, before they are parsed.
#:
#: The transport refuses anything past this first (``body_limit``), so a body
#: is never buffered unbounded for a caller who has not authenticated. This
#: check stays because the middleware reads Content-Length and a chunked
#: request carries none — and the two are asserted equal, so neither can drift.
MAX_EVENT_REQUEST_BYTES = MAX_EVENT_PAYLOAD_BYTES + 8 * 1024


@router.post("/events", status_code=status.HTTP_202_ACCEPTED)
async def ingest_event(
    request: Request, session: AdminSessionDep, caller: CallerDep
) -> dict[str, str]:
    """Re-emit one third-party event into a guild the calling app is installed in.

    Answers ``202`` rather than ``200``: the platform has accepted the event and
    handed it to the dispatcher. What subscribers do with it — and whether a
    deployment has any — is not something the emitting app is told, which is the
    same boundary that keeps it from learning who subscribes.
    """
    body = raw_body(request)
    if len(body) > MAX_EVENT_REQUEST_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=AppChannelMessages.EVENT_TOO_LARGE,
        )

    payload = parse_body(request, AppEventIngest)
    try:
        app = await channels_service.load_install(
            session, caller.registration, payload.guild_id
        )
        await channels_service.emit_event(
            session,
            app,
            caller.registration,
            event_type=payload.event_type,
            payload=payload.payload,
        )
    except AppChannelError as exc:
        raise to_http(exc) from exc
    return {"status": "accepted"}
