"""How an app service proves it is the app it says it is.

Everything on this surface hangs off one question — which registration signed
this request — so these tests hold that question rather than any route's answer.
Four properties, and each is asserted through the real HTTP surface rather than
against the verifier in isolation:

**The secret is the identity.** A request signed with the wrong secret is
refused, and so is one whose body changed after signing. The ``X-Initiative-App``
header only says which key to check; it never establishes who is calling.

**A signed request works once.** The same headers presented twice succeed and
then fail, because the nonce is spent on first use. The guard is per app, so one
app's traffic can never consume another's.

**Freshness is bounded.** A signature made outside the window is refused whether
or not the nonce is fresh, which is what keeps the guard's memory finite.

**The operator's switch outranks the key.** A disabled registration is refused
after its signature verifies — it is a state, not a failure to authenticate.
"""

import time

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.messages import AppChannelMessages
from app.services.marketplace.app_channel_auth import (
    APP_HEADER,
    NONCE_HEADER,
    SIGNATURE_HEADER,
    SIGNATURE_WINDOW_SECONDS,
    TIMESTAMP_HEADER,
)
from app.testing import (
    APP_CHANNEL_SECRET,
    channel_headers,
    encode_body,
    register_app_service,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.auth]

INSTALLS = "/api/v1/app-service/installs"


def _headers(**overrides) -> dict[str, str]:
    return channel_headers(method="GET", path=INSTALLS, **overrides)


async def test_a_signed_request_is_accepted(client: AsyncClient, session: AsyncSession):
    """The baseline: a request signed with the registration's own secret
    reaches the route. An app with no installs yet gets an empty list, which is
    a correct answer rather than a refusal."""
    await register_app_service(session)

    response = await client.get(INSTALLS, headers=_headers())

    assert response.status_code == 200, response.text
    assert response.json() == {"items": []}


@pytest.mark.parametrize(
    ("case", "registration", "build_headers", "status", "detail"),
    [
        ("unsigned", {}, lambda: None, 401, AppChannelMessages.MISSING_SIGNATURE),
        # Every signing header is required, not just the signature itself.
        (
            "a missing nonce header",
            {},
            lambda: {k: v for k, v in _headers().items() if k != NONCE_HEADER},
            401,
            AppChannelMessages.MISSING_SIGNATURE,
        ),
        # Bounded while verifying, so a value the guard column could not hold is
        # a clean refusal rather than an error at the insert.
        (
            "an oversized nonce",
            {},
            lambda: _headers(nonce="n" * 200),
            401,
            AppChannelMessages.MISSING_SIGNATURE,
        ),
        (
            "the wrong secret",
            {},
            lambda: _headers(secret="not-the-secret"),
            401,
            AppChannelMessages.INVALID_SIGNATURE,
        ),
        # An operator may clear a secret without deleting the row. What is left
        # has nothing to verify against, so nothing authenticates as it.
        (
            "a registration with no secret",
            {"secret": None},
            lambda: _headers(),
            401,
            AppChannelMessages.INVALID_SIGNATURE,
        ),
        (
            "an unknown app",
            {},
            lambda: _headers(public_id="tests.nobody"),
            401,
            AppChannelMessages.UNKNOWN_APP,
        ),
        (
            "an unparseable timestamp",
            {},
            lambda: {**_headers(), TIMESTAMP_HEADER: "yesterday"},
            401,
            AppChannelMessages.STALE_TIMESTAMP,
        ),
        # The operator's kill switch: the signature is fine, and the app still
        # reaches nothing.
        (
            "a disabled registration",
            {"enabled": False},
            lambda: _headers(),
            403,
            AppChannelMessages.APP_DISABLED,
        ),
    ],
    ids=lambda v: v if isinstance(v, str) and " " in v else "",
)
async def test_a_request_the_channel_cannot_authenticate_is_refused(
    client: AsyncClient,
    session: AsyncSession,
    case: str,
    registration: dict,
    build_headers,
    status: int,
    detail: str,
):
    """One refusal path per thing that can be wrong with a signed call, each
    naming what it was."""
    await register_app_service(session, **registration)

    headers = build_headers()
    response = (
        await client.get(INSTALLS, headers=headers)
        if headers
        else await client.get(INSTALLS)
    )

    assert response.status_code == status, response.text
    assert response.json()["detail"] == detail


async def test_a_body_changed_after_signing_is_refused(
    client: AsyncClient, session: AsyncSession
):
    """The signature covers a digest of the body, so a request whose payload was
    swapped for another is not the request that was signed."""
    await register_app_service(session)
    path = "/api/v1/app-service/events"
    signed = encode_body({"guild_id": 1, "event_type": "app.tests.shop.x"})
    sent = encode_body({"guild_id": 2, "event_type": "app.tests.shop.x"})

    response = await client.post(
        path,
        headers=channel_headers(method="POST", path=path, body=signed),
        content=sent,
    )

    assert response.status_code == 401
    assert response.json()["detail"] == AppChannelMessages.INVALID_SIGNATURE


async def test_a_signature_for_another_path_is_refused(
    client: AsyncClient, session: AsyncSession
):
    """The path is signed too, so a signature captured from one route cannot be
    replayed against another."""
    await register_app_service(session)
    headers = channel_headers(
        method="GET", path="/api/v1/app-service/installs/1/config"
    )

    response = await client.get(INSTALLS, headers=headers)

    assert response.status_code == 401
    assert response.json()["detail"] == AppChannelMessages.INVALID_SIGNATURE


@pytest.mark.parametrize("offset", [-(SIGNATURE_WINDOW_SECONDS + 60), 3600])
async def test_a_stale_timestamp_is_refused(
    client: AsyncClient, session: AsyncSession, offset: int
):
    """Both directions: too old, and too far in the future. A signature that is
    always acceptable would need a guard that remembers forever."""
    await register_app_service(session)
    stale = int(time.time()) + offset

    response = await client.get(INSTALLS, headers=_headers(timestamp=stale))

    assert response.status_code == 401
    assert response.json()["detail"] == AppChannelMessages.STALE_TIMESTAMP


async def test_a_replayed_request_is_refused(
    client: AsyncClient, session: AsyncSession
):
    """The same signed request, sent twice. The first is served; the second is
    refused because its nonce was spent on the first."""
    await register_app_service(session)
    headers = _headers()

    first = await client.get(INSTALLS, headers=headers)
    second = await client.get(INSTALLS, headers=headers)

    assert first.status_code == 200, first.text
    assert second.status_code == 401
    assert second.json()["detail"] == AppChannelMessages.REPLAYED_REQUEST


async def test_the_replay_guard_is_scoped_to_one_app(
    client: AsyncClient, session: AsyncSession
):
    """Two apps using the same nonce value both succeed: the guard is keyed by
    (registration, nonce), so what one app spends is not taken from another."""
    await register_app_service(session)
    await register_app_service(
        session,
        public_id="tests.other",
        listing_uid="TESTAPP0000002",
        secret="other-secret",
    )
    shared_nonce = "the-same-value"

    first = await client.get(INSTALLS, headers=_headers(nonce=shared_nonce))
    second = await client.get(
        INSTALLS,
        headers=_headers(
            nonce=shared_nonce, public_id="tests.other", secret="other-secret"
        ),
    )

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text


async def test_a_disabled_registration_does_not_spend_a_nonce(
    client: AsyncClient, session: AsyncSession
):
    """Refusing before the burn means re-enabling the app does not leave the
    caller's in-flight retries poisoned."""
    registration = await register_app_service(session, enabled=False)
    headers = _headers()

    refused = await client.get(INSTALLS, headers=headers)
    assert refused.status_code == 403

    registration.enabled = True
    session.add(registration)
    await session.commit()

    accepted = await client.get(INSTALLS, headers=headers)
    assert accepted.status_code == 200, accepted.text


async def test_the_app_header_alone_establishes_nothing(
    client: AsyncClient, session: AsyncSession
):
    """Naming one app while signing as another is refused. The header selects a
    key; the signature is what decides."""
    await register_app_service(session)
    await register_app_service(
        session,
        public_id="tests.other",
        listing_uid="TESTAPP0000002",
        secret="other-secret",
    )
    headers = _headers(public_id="tests.other", secret=APP_CHANNEL_SECRET)
    assert headers[APP_HEADER] == "tests.other"
    assert headers[SIGNATURE_HEADER].startswith("sha256=")

    response = await client.get(INSTALLS, headers=headers)

    assert response.status_code == 401
    assert response.json()["detail"] == AppChannelMessages.INVALID_SIGNATURE
