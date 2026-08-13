"""Third-party events entering through an app.

The platform's half of the trip is narrow and worth pinning exactly: the event
type is one the *pinned* definition declares, it sits under the calling app's
own namespace, the guild has that app installed and switched on, and the body is
within a bound. Past those, it becomes an ordinary event — so the test that
matters most is that a valid one reaches ``dispatch_event`` unchanged, because
everything after that is machinery this phase did not build.

The namespace check is deliberately independent of the declaration check. A
manifest cannot get past the listing validator carrying another app's prefix,
but a pinned definition is a stored snapshot, and the ingress refuses on the
prefix in its own right rather than trusting that validation happened.
"""

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.v1.app_service_endpoints.events import MAX_EVENT_REQUEST_BYTES
from app.core.messages import AppChannelMessages
from app.services.tenant import app_channels as channels_service
from app.testing import (
    channel_headers,
    create_guild,
    create_guild_app,
    create_user,
    encode_body,
    register_app_service,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]

EVENTS = "/api/v1/app-service/events"
SHOP_UID = "TESTAPP0000001"
ORDER_CREATED = "app.tests.shop.order_created"


def _definition(public_id: str = "tests.shop", events: list[str] | None = None) -> dict:
    return {
        "app_kind": "service",
        "service": {"public_id": public_id, "protocol": 1},
        "features": ["events"],
        "events": [ORDER_CREATED] if events is None else events,
    }


@pytest.fixture
def dispatched(monkeypatch):
    """What reached the dispatcher, without delivering anything.

    Delivery targets belong to the automation delegate, and an unconfigured
    deployment has none — so capturing the call is what says the event arrived
    at the right seam.
    """
    calls: list[dict] = []

    async def _capture(session, *, event_type, guild_id, payload, initiative_id=None):
        calls.append(
            {
                "event_type": event_type,
                "guild_id": guild_id,
                "payload": payload,
                "initiative_id": initiative_id,
            }
        )

    monkeypatch.setattr(channels_service, "dispatch_event", _capture)
    return calls


async def _install(session: AsyncSession, *, definition=None, **overrides):
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    app = await create_guild_app(
        session,
        guild,
        user,
        definition=definition or _definition(),
        listing_uid=overrides.pop("listing_uid", SHOP_UID),
        **overrides,
    )
    return guild, app


async def _emit(client: AsyncClient, payload, **kwargs):
    body = encode_body(payload)
    return await client.post(
        EVENTS,
        headers=channel_headers(method="POST", path=EVENTS, body=body, **kwargs),
        content=body,
    )


async def test_a_declared_event_reaches_the_dispatcher(
    client: AsyncClient, session: AsyncSession, dispatched
):
    await register_app_service(session, listing_uid=SHOP_UID)
    guild, _ = await _install(session)

    response = await _emit(
        client,
        {
            "guild_id": guild.id,
            "event_type": ORDER_CREATED,
            "payload": {"order_id": "1001"},
        },
    )

    assert response.status_code == 202, response.text
    assert dispatched == [
        {
            "event_type": ORDER_CREATED,
            "guild_id": guild.id,
            "payload": {"order_id": "1001"},
            "initiative_id": None,
        }
    ]


async def test_an_event_carries_no_initiative(
    client: AsyncClient, session: AsyncSession, dispatched
):
    """Apps see guilds, not initiatives, so an app's event is guild-scoped and
    a field naming an initiative is simply not part of the shape."""
    await register_app_service(session, listing_uid=SHOP_UID)
    guild, _ = await _install(session)

    response = await _emit(
        client,
        {
            "guild_id": guild.id,
            "event_type": ORDER_CREATED,
            "payload": {},
            "initiative_id": 7,
        },
    )

    assert response.status_code == 202, response.text
    assert dispatched[0]["initiative_id"] is None


async def test_an_undeclared_event_type_is_refused(
    client: AsyncClient, session: AsyncSession, dispatched
):
    await register_app_service(session, listing_uid=SHOP_UID)
    guild, _ = await _install(session)

    response = await _emit(
        client,
        {
            "guild_id": guild.id,
            "event_type": "app.tests.shop.never_declared",
            "payload": {},
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == AppChannelMessages.UNKNOWN_EVENT_TYPE
    assert dispatched == []


async def test_another_apps_namespace_is_refused(
    client: AsyncClient, session: AsyncSession, dispatched
):
    """Even a pinned definition that lists it: an app announces and emits only
    under its own name, so the prefix is checked against the caller."""
    await register_app_service(session, listing_uid=SHOP_UID)
    guild, _ = await _install(
        session, definition=_definition(events=["app.tests.other.order_created"])
    )

    response = await _emit(
        client,
        {
            "guild_id": guild.id,
            "event_type": "app.tests.other.order_created",
            "payload": {},
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == AppChannelMessages.UNKNOWN_EVENT_TYPE
    assert dispatched == []


async def test_an_oversized_event_is_refused(
    client: AsyncClient, session: AsyncSession, dispatched
):
    """An event is a notification, not a transfer: an app with more to say
    serves it from a data source the platform fetches on demand."""
    await register_app_service(session, listing_uid=SHOP_UID)
    guild, _ = await _install(session)
    oversized = "x" * (channels_service.MAX_EVENT_PAYLOAD_BYTES + 1_000)

    response = await _emit(
        client,
        {
            "guild_id": guild.id,
            "event_type": ORDER_CREATED,
            "payload": {"note": oversized},
        },
    )

    assert response.status_code == 413
    assert response.json()["detail"] == AppChannelMessages.EVENT_TOO_LARGE
    assert dispatched == []


async def test_a_body_beyond_the_request_bound_is_refused(
    client: AsyncClient, session: AsyncSession, dispatched
):
    """Checked against the bytes the signature covered, before they are parsed."""
    await register_app_service(session, listing_uid=SHOP_UID)
    guild, _ = await _install(session)

    response = await _emit(
        client,
        {
            "guild_id": guild.id,
            "event_type": ORDER_CREATED,
            "payload": {"note": "x" * (128 * 1024)},
        },
    )

    assert response.status_code == 413
    assert response.json()["detail"] == AppChannelMessages.EVENT_TOO_LARGE
    assert dispatched == []


async def test_an_event_for_a_guild_without_the_install_is_refused(
    client: AsyncClient, session: AsyncSession, dispatched
):
    await register_app_service(session, listing_uid=SHOP_UID)
    user = await create_user(session)
    bare = await create_guild(session, creator=user)

    response = await _emit(
        client,
        {"guild_id": bare.id, "event_type": ORDER_CREATED, "payload": {}},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == AppChannelMessages.INSTALL_NOT_FOUND
    assert dispatched == []


async def test_a_disabled_install_refuses_events(
    client: AsyncClient, session: AsyncSession, dispatched
):
    await register_app_service(session, listing_uid=SHOP_UID)
    guild, _ = await _install(session, enabled=False)

    response = await _emit(
        client,
        {"guild_id": guild.id, "event_type": ORDER_CREATED, "payload": {}},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == AppChannelMessages.INSTALL_DISABLED
    assert dispatched == []


async def test_a_disabled_registration_refuses_events(
    client: AsyncClient, session: AsyncSession, dispatched
):
    await register_app_service(session, listing_uid=SHOP_UID, enabled=False)
    guild, _ = await _install(session)

    response = await _emit(
        client,
        {"guild_id": guild.id, "event_type": ORDER_CREATED, "payload": {}},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == AppChannelMessages.APP_DISABLED
    assert dispatched == []


async def test_an_unparseable_body_is_refused(
    client: AsyncClient, session: AsyncSession, dispatched
):
    await register_app_service(session, listing_uid=SHOP_UID)
    body = b"not json at all"

    response = await client.post(
        EVENTS,
        headers=channel_headers(method="POST", path=EVENTS, body=body),
        content=body,
    )

    assert response.status_code == 422
    assert response.json()["detail"] == AppChannelMessages.INVALID_PAYLOAD
    assert dispatched == []


class TestTheTransportRefusesFirst:
    """An oversized body is refused before it is buffered.

    Every route on this surface has to read its body to check the signature
    that covers it, which means an unauthenticated caller can make the worker
    hold whatever they send. The ceiling therefore lives at the transport seam,
    and the handler's exact cap stays as the check for a chunked request that
    carries no Content-Length.
    """

    def test_the_transport_ceiling_matches_the_handler_cap(self):
        from app.core.body_limit import APP_SERVICE_MAX_REQUEST_BYTES

        assert APP_SERVICE_MAX_REQUEST_BYTES == MAX_EVENT_REQUEST_BYTES

    def test_the_app_service_surface_has_a_transport_rule(self):
        from app.core.body_limit import _RULES

        assert any(
            pattern.match("/api/v1/app-service/events") for pattern, _, _ in _RULES
        ), "app-service routes buffer before authenticating and need a body ceiling"
