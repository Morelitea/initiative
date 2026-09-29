"""The served wiring: what reaches which stream, at what level."""

from __future__ import annotations

import logging

import pytest

from app.core.config import settings
from app.core.logging_config import (
    AUDIT_LOGGER_NAME,
    configure_logging,
    logging_config,
)


@pytest.fixture(autouse=True)
def _served_wiring():
    """Apply the wiring before, and again after, so a test that pokes at a
    level leaves the process as it found it."""
    configure_logging()
    yield
    configure_logging()


def test_an_audit_line_reaches_stdout_with_nothing_forcing_the_level(capfd):
    """No ``caplog.at_level`` here: the level is the wiring's own."""
    logging.getLogger(AUDIT_LOGGER_NAME).info('{"event_type":"x"}')

    out, err = capfd.readouterr()
    assert out == '{"event_type":"x"}\n'
    assert '{"event_type":"x"}' not in err


def test_an_audit_line_is_the_bare_envelope_and_nothing_else(capfd):
    """No timestamp prefix, no level, no logger name: the line is the JSON
    object, so a pipeline parses it as a record."""
    logging.getLogger(AUDIT_LOGGER_NAME).info('{"a":1}')
    assert capfd.readouterr().out.splitlines() == ['{"a":1}']


def test_the_audit_stream_does_not_reach_the_root_handlers(caplog):
    """One envelope, one line, one place: the audit logger stops at its own
    handler rather than propagating up."""
    with caplog.at_level(logging.INFO):
        logging.getLogger(AUDIT_LOGGER_NAME).info('{"a":1}')
    assert [r for r in caplog.records if r.name == AUDIT_LOGGER_NAME] == []


def test_application_lines_go_to_stderr_at_the_configured_level(capfd):
    logging.getLogger("app.core.logging_config_test").info("hello from the app")

    out, err = capfd.readouterr()
    assert "hello from the app" in err
    assert "hello from the app" not in out


def test_the_root_level_is_the_setting():
    assert logging_config()["root"]["level"] == settings.LOG_LEVEL
    assert (
        logging.getLogger().level == logging.getLevelNamesMapping()[settings.LOG_LEVEL]
    )


def test_loggers_configured_before_this_are_kept():
    """Uvicorn configures its own loggers before it imports the app; the
    wiring adds to the process rather than silencing them."""
    assert logging_config()["disable_existing_loggers"] is False


def test_applying_the_wiring_twice_installs_one_handler():
    configure_logging()
    configure_logging()
    assert len(logging.getLogger(AUDIT_LOGGER_NAME).handlers) == 1
    assert len(logging.getLogger().handlers) == 1
