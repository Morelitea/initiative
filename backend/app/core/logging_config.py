"""How the served process writes its logs.

Two streams, by what reads them. The application's own lines — startup
checks, back-fill counts, warnings — go to stderr in a plain readable format
at ``LOG_LEVEL``. The ``audit`` logger goes to stdout as the bare JSON line
``services/audit.py`` hands it: one envelope per line and nothing else on the
stream, so a container-log pipeline ships it as records rather than as text
with a record somewhere inside. It does not propagate to the root logger,
which is what keeps each envelope to one line in one place.

Applied when ``app.main`` is imported, which is how uvicorn loads the app, so
the wiring is the served one and not something a launcher has to remember.
Uvicorn's own loggers are left as it configured them.
"""

from __future__ import annotations

import logging
import logging.config
import sys
from typing import Any

from app.core.config import settings

#: The logger ``services/audit.py`` writes envelopes to.
AUDIT_LOGGER_NAME = "audit"


class LiveStreamHandler(logging.StreamHandler):
    """A stream handler bound to ``sys.stdout`` or ``sys.stderr`` by name.

    ``logging.StreamHandler`` keeps the stream object it was given. This one
    looks the named stream up per record, so a process whose streams are
    replaced after configuration — a test harness capturing output, a
    launcher redirecting it — writes to the current one.
    """

    def __init__(self, stream_name: str) -> None:
        if stream_name not in ("stdout", "stderr"):
            raise ValueError(
                f"stream_name must be stdout or stderr, got {stream_name!r}"
            )
        self._stream_name = stream_name
        super().__init__()

    @property
    def stream(self) -> Any:  # type: ignore[override]
        return getattr(sys, self._stream_name)

    @stream.setter
    def stream(self, _value: Any) -> None:
        # Assigned by the base initialiser and by ``setStream``; the property
        # answers by name regardless.
        pass


def logging_config() -> dict[str, Any]:
    """The ``dictConfig`` the served process applies.

    Kept as data so a test can assert on the shape without applying it.
    """
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "app": {"format": "%(asctime)s %(levelname)s %(name)s: %(message)s"},
            "line": {"format": "%(message)s"},
        },
        "handlers": {
            "app": {
                "()": "app.core.logging_config.LiveStreamHandler",
                "stream_name": "stderr",
                "formatter": "app",
            },
            "audit": {
                "()": "app.core.logging_config.LiveStreamHandler",
                "stream_name": "stdout",
                "formatter": "line",
            },
        },
        "root": {"level": settings.LOG_LEVEL, "handlers": ["app"]},
        "loggers": {
            AUDIT_LOGGER_NAME: {
                "level": "INFO",
                "handlers": ["audit"],
                "propagate": False,
            },
        },
    }


def configure_logging() -> None:
    """Apply :func:`logging_config`.

    Idempotent: applying it again replaces the handlers it installed rather
    than adding to them.
    """
    logging.config.dictConfig(logging_config())
