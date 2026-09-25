"""A fetch as a job: the bound on how long it may read."""

import asyncio

import pytest

from app.core.messages import ImportEngineMessages
from app.services.import_engine import atlassian_job
from app.services.import_engine import limits as import_limits
from app.services.import_engine.contract import ImportEngineError


async def test_a_fetch_past_its_deadline_fails_as_too_slow(monkeypatch):
    async def forever(*_args, **_kwargs):
        await asyncio.sleep(3600)

    monkeypatch.setattr(atlassian_job, "_read", forever)
    monkeypatch.setattr(import_limits, "IMPORT_FETCH_DEADLINE_SECONDS", 0.05)

    with pytest.raises(ImportEngineError) as exc:
        await atlassian_job.fetch(
            None,  # type: ignore[arg-type]
            guild_id=1,
            open_user_session=None,  # type: ignore[arg-type]
        )
    assert exc.value.code == ImportEngineMessages.IMPORT_SOURCE_TOO_SLOW
