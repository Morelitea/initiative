"""Statement timing on the engines."""

from __future__ import annotations

import logging

import pytest
from prometheus_client import REGISTRY
from sqlalchemy import text

from app.core import audit_context, metrics
from app.db import session as db_session

pytestmark = pytest.mark.integration


@pytest.fixture
def every_statement_is_slow(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(db_session, "SLOW_STATEMENT_SECONDS", 0.0)
    # The test engine is disposed at teardown; keep it out of the pool report.
    monkeypatch.setattr(metrics, "_watched_engines", {})


def _statements_timed(label: str) -> float:
    return (
        REGISTRY.get_sample_value(
            "initiative_db_statement_duration_seconds_count", {"engine": label}
        )
        or 0.0
    )


async def test_a_slow_statement_is_logged_with_its_request_and_never_its_values(
    engine, every_statement_is_slow, caplog: pytest.LogCaptureFixture
):
    db_session.instrument_engine(engine, "timed")
    before = _statements_timed("timed")

    _, token = audit_context.begin(request_id="req-slow-1")
    try:
        with caplog.at_level(logging.WARNING, logger=db_session.logger.name):
            async with engine.connect() as connection:
                await connection.execute(
                    text("SELECT :word AS said"), {"word": "hunter2"}
                )
    finally:
        audit_context.end(token)

    assert _statements_timed("timed") == before + 1
    assert REGISTRY.get_sample_value(
        "initiative_db_slow_statements_total", {"engine": "timed"}
    )
    [line] = [r.getMessage() for r in caplog.records if "timed" in r.getMessage()]
    assert "request req-slow-1" in line
    assert "SELECT" in line
    assert "hunter2" not in line


async def test_a_statement_whose_text_is_a_readers_keeps_it_out_of_the_log(
    engine, every_statement_is_slow, caplog: pytest.LogCaptureFixture
):
    db_session.instrument_engine(engine, "reader", log_text=False)

    with caplog.at_level(logging.WARNING, logger=db_session.logger.name):
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 'only mine' AS note"))

    [line] = [r.getMessage() for r in caplog.records if "reader" in r.getMessage()]
    assert "only mine" not in line
    assert "SELECT" not in line


async def test_ddl_is_timed_but_never_flagged(
    engine, every_statement_is_slow, caplog: pytest.LogCaptureFixture
):
    db_session.instrument_engine(engine, "ddl", flag_slow=False)
    before = _statements_timed("ddl")

    with caplog.at_level(logging.WARNING, logger=db_session.logger.name):
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))

    assert _statements_timed("ddl") == before + 1
    assert not [r for r in caplog.records if "ddl" in r.getMessage()]
