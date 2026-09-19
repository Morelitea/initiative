"""The registry drives every surface, so the two halves have to agree."""

import pytest

from app.core.audit_events import AUDIT_EVENT_META, AuditEventType

pytestmark = pytest.mark.unit


def test_every_event_has_metadata():
    """Adding an action is an enum member plus its row. Forgetting the row
    would leave the tier and category to be guessed at write time."""
    missing = [e.value for e in AuditEventType if e not in AUDIT_EVENT_META]
    assert missing == []


def test_no_metadata_without_an_event():
    stray = [key for key in AUDIT_EVENT_META if not isinstance(key, AuditEventType)]
    assert stray == []


def test_values_are_namespaced():
    """``family.action`` — downstream filters on the prefix."""
    for event in AuditEventType:
        family, separator, action = event.value.partition(".")
        assert separator and family and action, event.value


def test_tiers_are_the_two_the_design_defines():
    for event, meta in AUDIT_EVENT_META.items():
        assert meta.tier in (1, 2), event.value
