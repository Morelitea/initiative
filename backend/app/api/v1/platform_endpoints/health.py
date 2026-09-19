"""Liveness and readiness.

Two questions, deliberately answered separately.

``/healthz`` asks whether this process is running and its event loop is
answering. It touches nothing outside the process, because a restart is the
only response to a "no" — and restarting a pod whose database went away fixes
nothing while costing its in-flight requests.

``/readyz`` asks whether this pod can serve a request now, which depends on
things outside the process. A "no" takes the pod out of the Service's
endpoints and leaves it running.

Which dependencies get a vote is the whole design. A pod that cannot reach
Postgres can serve nothing, so the three engines decide the verdict. The rest
— object storage, the cross-worker bus, the rate-limit counters — are reported
but do not: each one is normally reachable or unreachable for the entire
fleet at once, and a fleet that removes every pod from rotation over one of
them has turned a partial outage into a total one. They show up in the body as
``degraded`` so an operator reading the probe sees what a dashboard would.

Both routes are unauthenticated, and neither counts against the global rate
limit — a probe answered with a 429 reports a failure the process does not
have. ``PROBE_PATHS`` is what ``app.main`` skips them by.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable

import anyio
from fastapi import APIRouter, Response, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.rate_limit import limiter

logger = logging.getLogger(__name__)

router = APIRouter()

HEALTHZ_PATH = "/healthz"
READYZ_PATH = "/readyz"

#: Where these two answer, under whatever prefix the router is mounted on.
#: ``app.main`` reads it to keep them out of the default rate limit.
PROBE_PATHS = (HEALTHZ_PATH, READYZ_PATH)

#: How long any one check may take. Bounded well under the probe's own
#: ``timeoutSeconds`` so a hung dependency is reported as a failed check
#: rather than as a probe that never answered.
CHECK_TIMEOUT_SECONDS = 3.0

#: Checks whose failure means "send this pod no traffic". Everything else is
#: reported and does not change the verdict — see the module docstring.
REQUIRED = frozenset({"database", "database_system", "database_provisioning"})


async def _ping(engine_name: str) -> None:
    """Take a connection from one engine's pool and use it.

    The engine is read off the module rather than bound at import, so the
    connection tested is the one the process is serving requests with.
    """
    from app.db import session as db_session  # noqa: PLC0415

    target: AsyncEngine = getattr(db_session, engine_name)
    async with target.connect() as connection:
        await connection.execute(text("SELECT 1"))


async def _storage() -> None:
    from app.services import storage  # noqa: PLC0415 — import cycle at module scope

    await anyio.to_thread.run_sync(storage.probe)


async def _notify_bus() -> None:
    from app.services.platform import notify_bus  # noqa: PLC0415

    if not notify_bus.bus.running:
        raise RuntimeError("not connected")


async def _rate_limit_store() -> None:
    # ``check()`` is a round trip for a shared store and a no-op for the
    # in-process default. It is synchronous either way.
    if not await anyio.to_thread.run_sync(limiter.limiter.storage.check):
        raise RuntimeError("unavailable")


CHECKS: dict[str, Callable[[], Awaitable[None]]] = {
    "database": lambda: _ping("engine"),
    "database_system": lambda: _ping("admin_engine"),
    "database_provisioning": lambda: _ping("provisioning_engine"),
    "storage": _storage,
    "notify_bus": _notify_bus,
    "rate_limit_store": _rate_limit_store,
}


async def _run(name: str, check: Callable[[], Awaitable[None]]) -> str:
    """Run one check and report ``ok`` or ``error``.

    The reason goes to the log, where an operator can read it. The response
    says which dependency is unhappy and nothing else about it.
    """
    try:
        await asyncio.wait_for(check(), timeout=CHECK_TIMEOUT_SECONDS)
    except Exception:
        logger.warning("readiness check failed: %s", name, exc_info=True)
        return "error"
    return "ok"


@router.get(HEALTHZ_PATH, include_in_schema=False)
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get(READYZ_PATH, include_in_schema=False)
async def readyz(response: Response) -> dict[str, object]:
    names = list(CHECKS)
    results = await asyncio.gather(*(_run(name, CHECKS[name]) for name in names))
    checks = dict(zip(names, results))

    failed = {name for name, result in checks.items() if result != "ok"}
    if failed & REQUIRED:
        overall = "unavailable"
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    elif failed:
        overall = "degraded"
    else:
        overall = "ok"
    return {"status": overall, "checks": checks}
