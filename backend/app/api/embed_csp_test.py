"""Which origins a served document may frame.

The property under test is that the answer is a property of the **deployment**:
the origins of the app services an operator has wired up and whose handshake
confirmed the manifest behind them. So the same header goes to every document,
it names no guild, install or reader, and an operator's kill switch is the
thing that takes an origin back out of it.
"""

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.embed_csp import app_frame_policy
from app.core.config import settings
from app.models.platform.app_service_registration import AppServiceStatus
from app.services.marketplace import registration_lookup
from app.services.marketplace.registration_lookup import (
    frame_origins,
    invalidate_registrations,
)
from app.testing import create_app_service_registration

pytestmark = pytest.mark.asyncio

FRAMED = "https://framed.example.test"
SECOND = "https://second.example.test"


class TestTheRegisteredOrigins:
    async def test_a_live_registration_is_named(self, session: AsyncSession):
        await create_app_service_registration(
            session,
            public_id="tests.framed",
            base_url=FRAMED,
            allowed_origins=[FRAMED],
        )

        assert FRAMED in await frame_origins()

    async def test_every_live_registration_is_named_once_and_in_order(
        self, session: AsyncSession
    ):
        """Two apps served from one origin put it on the list once. The order
        is the sorted one, so the header is the same string until a
        registration changes rather than varying with row order."""
        await create_app_service_registration(
            session,
            public_id="tests.first",
            base_url=FRAMED,
            allowed_origins=[FRAMED, SECOND],
        )
        await create_app_service_registration(
            session,
            public_id="tests.second",
            base_url=SECOND,
            allowed_origins=[SECOND],
        )

        origins = await frame_origins()
        assert FRAMED in origins
        assert origins.count(SECOND) == 1
        assert list(origins) == sorted(origins)

    async def test_a_stopped_registration_is_not_named(self, session: AsyncSession):
        """The kill switch reaches the header: a stopped app is not framed
        while it is stopped."""
        registration = await create_app_service_registration(
            session,
            public_id="tests.stopped",
            base_url=FRAMED,
            allowed_origins=[FRAMED],
        )

        registration.enabled = False
        session.add(registration)
        await session.commit()
        invalidate_registrations()

        assert FRAMED not in await frame_origins()

    async def test_an_unverified_registration_is_not_named(self, session: AsyncSession):
        """The origins come from a manifest, so the header waits on the
        verification that says which manifest this service serves."""
        registration = await create_app_service_registration(
            session,
            public_id="tests.drifted",
            base_url=FRAMED,
            allowed_origins=[FRAMED],
        )

        registration.status = AppServiceStatus.MANIFEST_MISMATCH
        session.add(registration)
        await session.commit()
        invalidate_registrations()

        assert FRAMED not in await frame_origins()


class TestThePolicy:
    async def test_a_document_may_frame_a_registered_app(self, session: AsyncSession):
        await create_app_service_registration(
            session,
            public_id="tests.framed",
            base_url=FRAMED,
            allowed_origins=[FRAMED],
        )

        assert FRAMED in _directive(await app_frame_policy(), "frame-src")

    async def test_a_deployment_with_nothing_live_frames_nothing(
        self, session: AsyncSession
    ):
        """Nothing live, nothing named: the document carries the same policy
        the middleware puts on everything else."""
        registration = await create_app_service_registration(
            session,
            public_id="tests.stopped",
            base_url=FRAMED,
            allowed_origins=[FRAMED],
        )
        registration.enabled = False
        session.add(registration)
        await session.commit()
        invalidate_registrations()

        assert await app_frame_policy() == settings.content_security_policy

    async def test_an_unreadable_list_leaves_the_ordinary_policy(self, monkeypatch):
        """Answered, not raised: this runs on the route that serves every
        document, so the fallback is the stricter policy and the page still
        loads."""

        async def boom() -> tuple[str, ...]:
            raise RuntimeError("no")

        monkeypatch.setattr(registration_lookup, "frame_origins", boom)

        assert await app_frame_policy() == settings.content_security_policy


@pytest.mark.unit
def test_the_ordinary_policy_frames_no_app():
    """What the middleware puts on every response that is not a document."""
    assert "example.test" not in _directive(
        settings.content_security_policy, "frame-src"
    )


def _directive(policy: str, name: str) -> str:
    for directive in policy.split(";"):
        cleaned = directive.strip()
        if cleaned.startswith(f"{name} "):
            return cleaned
    raise AssertionError(f"{name} missing from {policy!r}")
