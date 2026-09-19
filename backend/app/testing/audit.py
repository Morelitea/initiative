"""Reading the audit stream back in a test."""

from __future__ import annotations

import json
from typing import Any

from app.core.audit_events import AuditEventType


def emitted(capfd, event_type: AuditEventType | None = None) -> list[dict[str, Any]]:
    """The envelopes written to stdout since the capture was last read,
    oldest first — those of ``event_type``, or all of them.

    Reading consumes the capture, so take everything a test needs from one
    call. The served logging wiring is applied when ``app.main`` is imported,
    which the test suite does, so no level is forced here.
    """
    out = capfd.readouterr().out
    envelopes = [
        json.loads(line)
        for line in out.splitlines()
        if line.startswith("{") and '"stream":"audit"' in line
    ]
    if event_type is None:
        return envelopes
    return [e for e in envelopes if e["event_type"] == event_type.value]
