"""Keeping a registration's record honest.

The sweep re-runs the handshake and writes down what it found. What it must not
do is act on it: an app that fails to answer is *reported*, never switched off,
because a network blip is not an operator decision and the kill switch has one
owner. The same goes for a manifest that changed — the row says so, and adopting
the new one stays a click somebody makes deliberately.

Registrations reach the request path through a cached snapshot, so a status this
sweep writes has to be what the next read sees.
"""

import hashlib
import hmac
import json

import httpx
import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.models.platform.app_service_registration import AppServiceStatus
from app.services.marketplace.handshake import (
    APP_PROTOCOL_VERSION,
    canonical_manifest_hash,
)
from app.services.marketplace.registration_lookup import load_registrations
from app.services.marketplace.reverification import (
    reverification_configured,
    sweep_registrations,
)
from app.testing import create_app_service_registration


SECRET = "test-secret"  # what the factory stores
BASE_URL = "http://127.0.0.1:9200"

MANIFEST = {
    "uid": "K7M2QX8N4TVB9C",
    "public_id": "acme.widgets",
    "kind": "app",
    "name": "Widgets",
    "protocol_version": APP_PROTOCOL_VERSION,
    "definition": {"app_kind": "tool_instance", "tool": "calendar"},
}


def _transport(*, manifest: dict | None = None, fail: bool = False):
    def handler(request: httpx.Request) -> httpx.Response:
        if fail:
            raise httpx.ConnectError("refused")
        if request.url.path.endswith("initiative-app.json"):
            return httpx.Response(200, json=manifest or MANIFEST)
        challenge = json.loads(request.content)["challenge"]
        signature = hmac.new(
            SECRET.encode("utf-8"), challenge.encode("utf-8"), hashlib.sha256
        ).hexdigest()
        return httpx.Response(200, json={"signature": signature})

    return httpx.MockTransport(handler)


async def _registration(session: AsyncSession, **overrides):
    return await create_app_service_registration(
        session,
        public_id="acme.widgets",
        base_url=BASE_URL,
        **{"status": AppServiceStatus.UNVERIFIED, **overrides},
    )


class TestWhetherItRunsAtAll:
    @pytest.mark.unit
    def test_it_is_off_without_a_signing_key(self, monkeypatch):
        """The app platform is inert without its keypair, so a worker for it
        would wake up forever to find nothing."""
        monkeypatch.setattr(settings, "APP_PLATFORM_SIGNING_PRIVATE_KEY_PEM", None)
        monkeypatch.setattr(settings, "APP_SERVICE_VERIFY_INTERVAL_SECONDS", 900)
        assert reverification_configured() is False

    @pytest.mark.unit
    def test_it_is_off_when_the_interval_is_zero(self, monkeypatch):
        monkeypatch.setattr(settings, "APP_PLATFORM_SIGNING_PRIVATE_KEY_PEM", "pem")
        monkeypatch.setattr(settings, "APP_SERVICE_VERIFY_INTERVAL_SECONDS", 0)
        assert reverification_configured() is False

    @pytest.mark.unit
    def test_it_runs_when_both_are_present(self, monkeypatch):
        monkeypatch.setattr(settings, "APP_PLATFORM_SIGNING_PRIVATE_KEY_PEM", "pem")
        monkeypatch.setattr(settings, "APP_SERVICE_VERIFY_INTERVAL_SECONDS", 900)
        assert reverification_configured() is True


class TestTheSweep:
    async def test_a_healthy_app_is_recorded_as_ok(self, session: AsyncSession):
        row = await _registration(session)

        result = await sweep_registrations(transport=_transport())
        assert (result.checked, result.ok, result.failed) == (1, 1, 0)

        await session.refresh(row)
        assert row.status == AppServiceStatus.OK
        assert row.last_verified_at is not None
        assert row.manifest_hash == canonical_manifest_hash(MANIFEST)
        assert row.listing_uid == MANIFEST["uid"]

    async def test_an_unreachable_app_is_marked_but_left_enabled(
        self, session: AsyncSession
    ):
        """Reported, not switched off: stopping an app is the operator's lever,
        and a sweep that flipped it would hand that lever to the network."""
        row = await _registration(session, status=AppServiceStatus.OK)

        result = await sweep_registrations(transport=_transport(fail=True))
        assert (result.checked, result.ok, result.failed) == (1, 0, 1)

        await session.refresh(row)
        assert row.status == AppServiceStatus.UNREACHABLE
        assert row.enabled is True

    async def test_a_changed_manifest_is_recorded_not_adopted(
        self, session: AsyncSession
    ):
        row = await _registration(session)
        await sweep_registrations(transport=_transport())
        await session.refresh(row)
        first_hash = row.manifest_hash

        widened = {**MANIFEST, "name": "Widgets Pro"}
        await sweep_registrations(transport=_transport(manifest=widened))

        await session.refresh(row)
        assert row.status == AppServiceStatus.MANIFEST_MISMATCH
        # The recorded hash still describes what an operator accepted.
        assert row.manifest_hash == first_hash

    async def test_a_switched_off_registration_is_skipped(self, session: AsyncSession):
        row = await _registration(session, enabled=False, status=AppServiceStatus.OK)

        result = await sweep_registrations(transport=_transport(fail=True))
        assert (result.checked, result.skipped) == (0, 1)

        await session.refresh(row)
        assert row.status == AppServiceStatus.OK

    async def test_the_cached_snapshot_reflects_what_the_sweep_wrote(
        self, session: AsyncSession
    ):
        await _registration(session)
        # Prime the cache with the pre-sweep state.
        assert (await load_registrations())["acme.widgets"].status == (
            AppServiceStatus.UNVERIFIED
        )

        await sweep_registrations(transport=_transport())

        assert (await load_registrations())["acme.widgets"].status == (
            AppServiceStatus.OK
        )
