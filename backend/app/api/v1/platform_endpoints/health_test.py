"""Tests for the liveness and readiness probes."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.api.v1.platform_endpoints import health
from app.core.config import settings


@pytest.fixture(autouse=True)
def request_engine_on_the_test_database(engine, monkeypatch: pytest.MonkeyPatch):
    """conftest already points the system and provisioning engines at this
    worker's database; the request engine is reached through the overridden
    session dependency, so nothing had moved it. The readiness check connects
    with the engine itself, which is what needs pointing here."""
    import app.db.session as db_session

    monkeypatch.setattr(db_session, "engine", engine)


async def test_healthz_answers_without_touching_anything(client: AsyncClient):
    """Liveness is about this process only, so it answers the same whether or
    not its dependencies are reachable."""
    resp = await client.get("/api/v1/healthz")
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"status": "ok"}


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


def test_a_read_replica_is_reported_and_does_not_decide(monkeypatch):
    assert "database_query" not in health.declared_checks()

    monkeypatch.setattr(
        health.settings, "DATABASE_URL_QUERY", "postgresql+asyncpg://r/initiative"
    )
    assert "database_query" in health.declared_checks()
    assert "database_query" not in health.REQUIRED


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


@pytest.mark.parametrize("path", ["/api/v1/healthz", "/api/v1/readyz"])
async def test_probes_are_not_rate_limited(
    client: AsyncClient, rate_limit_of_one_per_minute, path: str
):
    """A cluster calls these on a fixed interval, so they must never be
    answered with a 429 — and the marker slowapi offers for that does not
    reach the middleware in an app with a catch-all route, so this asks the
    running limiter rather than the decorator."""
    first = await client.get(path)
    second = await client.get(path)
    assert (first.status_code, second.status_code) != (200, 429), second.text
    assert first.status_code == 200 and second.status_code == 200, second.text


async def test_probes_stay_out_of_the_api_schema(client: AsyncClient):
    """Infrastructure routes, with no client generated for them."""
    resp = await client.get("/api/v1/openapi.json")
    assert resp.status_code == 200, resp.text
    paths = resp.json()["paths"]
    assert "/api/v1/healthz" not in paths
    assert "/api/v1/readyz" not in paths


METRICS = "/api/v1/metrics"


async def test_metrics_is_not_there_until_a_token_is_set(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(settings, "METRICS_TOKEN", None)
    resp = await client.get(METRICS, headers={"Authorization": "Bearer anything"})
    assert resp.status_code == 404


@pytest.mark.parametrize(
    "authorization", [None, "Bearer wrong", "Basic c2NyYXBlOnM=", "s3cret-token"]
)
async def test_metrics_wants_the_token_as_a_bearer(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, authorization: str | None
):
    monkeypatch.setattr(settings, "METRICS_TOKEN", "s3cret-token")
    headers = {"Authorization": authorization} if authorization else {}
    resp = await client.get(METRICS, headers=headers)
    assert resp.status_code == 401
    assert resp.headers["www-authenticate"] == "Bearer"


async def test_metrics_answers_a_scrape_presenting_the_token(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(settings, "METRICS_TOKEN", "s3cret-token")
    await client.get("/api/v1/version")

    resp = await client.get(METRICS, headers={"Authorization": "Bearer s3cret-token"})

    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("text/plain")
    body = resp.text
    assert (
        'initiative_http_requests_total{method="GET",route="/api/v1/version",status="200"}'
        in body
    )
    assert "initiative_build_info{version=" in body
    assert 'initiative_db_pool_connections{engine="request",state="idle"}' in body
    assert "initiative_sessions_active " in body
    assert "process_cpu_seconds_total" in body or "python_gc_objects" in body
