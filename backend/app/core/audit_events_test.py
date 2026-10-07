"""The catalogue's members, as downstream reads them."""

import pytest

from app.core.audit_events import AuditEventType

pytestmark = pytest.mark.always


def test_values_are_namespaced():
    """``family.action`` — downstream filters on the prefix."""
    for event in AuditEventType:
        family, separator, action = event.value.partition(".")
        assert separator and family and action, event.value


def test_tiers_are_the_two_the_design_defines():
    for event in AuditEventType:
        assert event.tier in (1, 2), event.value
