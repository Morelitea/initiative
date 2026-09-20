"""Tests for the liveness and readiness probes."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.api.v1.platform_endpoints import health


@pytest.fixture(autouse=True)
def request_engine_on_the_test_database(engine, monkeypatch: pytest.MonkeyPatch):
    """conftest already points the system and provisioning engines at this
    worker's database; the request engine is reached through the overridden
    session dependency, so nothing had moved it. The readiness check connects
    with the engine itself, which is what needs pointing here."""
    import app.db.session as db_session

    monkeypatch.setattr(db_session, "engine", engine)


@pytest.mark.integration
async def test_healthz_answers_without_touching_anything(client: AsyncClient):
    """Liveness is about this process only, so it answers the same whether or
    not its dependencies are reachable."""
    resp = await client.get("/api/v1/healthz")
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"status": "ok"}


@pytest.mark.integration
async def test_readyz_reports_every_dependency(client: AsyncClient):
    """Readiness names each dependency it pinged. The three engines are
    reachable under test, so the verdict is never ``unavailable``."""
    resp = await client.get("/api/v1/readyz")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body["checks"]) == set(health.CHECKS)
    for name in health.REQUIRED:
        assert body["checks"][name] == "ok", body
    assert body["status"] in {"ok", "degraded"}


@pytest.mark.integration
async def test_readyz_is_503_when_a_database_is_unreachable(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    """A pod that cannot reach Postgres can serve nothing, so it leaves the
    Service's endpoints."""

    async def unreachable() -> None:
        raise RuntimeError("down")

    monkeypatch.setitem(health.CHECKS, "database", unreachable)
    resp = await client.get("/api/v1/readyz")
    assert resp.status_code == 503, resp.text
    body = resp.json()
    assert body["status"] == "unavailable"
    assert body["checks"]["database"] == "error"


@pytest.mark.integration
async def test_readyz_stays_in_rotation_when_only_a_reported_check_fails(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    """Object storage, the bus and the rate-limit counters are reported, not
    voted on: losing one leaves most of the app serving, and removing every
    pod over it would leave none."""

    async def unreachable() -> None:
        raise RuntimeError("down")

    for name in set(health.CHECKS) - health.REQUIRED:
        monkeypatch.setitem(health.CHECKS, name, unreachable)
    resp = await client.get("/api/v1/readyz")
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "degraded"


@pytest.mark.integration
async def test_readyz_reports_a_hung_dependency_rather_than_hanging(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    """A check that never returns is bounded, so the probe answers inside its
    own timeout instead of being killed by it."""
    import asyncio

    async def never() -> None:
        await asyncio.sleep(60)

    async def immediately() -> None:
        return None

    for name in health.CHECKS:
        monkeypatch.setitem(health.CHECKS, name, immediately)
    monkeypatch.setattr(health, "CHECK_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setitem(health.CHECKS, "storage", never)

    resp = await client.get("/api/v1/readyz")
    assert resp.status_code == 200, resp.text
    assert resp.json()["checks"]["storage"] == "error"


@pytest.fixture
def one_request_a_minute(monkeypatch: pytest.MonkeyPatch):
    """Turn the global default limit on, at a rate a second request breaks."""
    from slowapi.wrappers import LimitGroup

    from app.core.rate_limit import get_real_client_ip, limiter

    monkeypatch.setattr(limiter, "enabled", True)
    monkeypatch.setattr(
        limiter,
        "_default_limits",
        [
            LimitGroup(
                limit_provider="1/minute",
                key_function=get_real_client_ip,
                scope=None,
                per_method=False,
                methods=None,
                error_message=None,
                exempt_when=None,
                cost=1,
                override_defaults=False,
            )
        ],
    )
    limiter.reset()
    yield
    limiter.reset()


@pytest.mark.integration
@pytest.mark.parametrize("path", ["/api/v1/healthz", "/api/v1/readyz"])
async def test_probes_are_not_rate_limited(
    client: AsyncClient, one_request_a_minute, path: str
):
    """A cluster calls these on a fixed interval, so they must never be
    answered with a 429 — and the marker slowapi offers for that does not
    reach the middleware in an app with a catch-all route, so this asks the
    running limiter rather than the decorator."""
    first = await client.get(path)
    second = await client.get(path)
    assert (first.status_code, second.status_code) != (200, 429), second.text
    assert first.status_code == 200 and second.status_code == 200, second.text


@pytest.mark.integration
async def test_the_limit_it_is_skipping_is_really_on(
    client: AsyncClient, one_request_a_minute
):
    """The other half of the test above: an ordinary route under the same
    fixture does answer 429, so the probes passing means they were skipped and
    not that the limiter was asleep."""
    assert (await client.get("/api/v1/version")).status_code == 200
    assert (await client.get("/api/v1/version")).status_code == 429


@pytest.mark.integration
async def test_probes_stay_out_of_the_api_schema(client: AsyncClient):
    """Infrastructure routes, with no client generated for them."""
    resp = await client.get("/api/v1/openapi.json")
    assert resp.status_code == 200, resp.text
    paths = resp.json()["paths"]
    assert "/api/v1/healthz" not in paths
    assert "/api/v1/readyz" not in paths
