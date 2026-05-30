"""Unit tests for the PAM request-context access helper."""

import pytest

from app.core.pam_context import active_grant_level, grant_satisfies, set_active_grant


@pytest.fixture(autouse=True)
def _clear_grant():
    set_active_grant(None, None)
    yield
    set_active_grant(None, None)


@pytest.mark.unit
def test_no_grant_satisfies_nothing():
    assert grant_satisfies(1, access="read") is False
    assert grant_satisfies(1, access="write") is False
    assert active_grant_level(1) is None


@pytest.mark.unit
def test_read_grant_satisfies_read_only_for_its_guild():
    set_active_grant(42, "read")
    assert grant_satisfies(42, access="read") is True
    assert grant_satisfies(42, access="write") is False
    # Different guild — not covered.
    assert grant_satisfies(99, access="read") is False


@pytest.mark.unit
def test_read_write_grant_satisfies_both():
    set_active_grant(42, "read_write")
    assert grant_satisfies(42, access="read") is True
    assert grant_satisfies(42, access="write") is True


@pytest.mark.unit
def test_grant_never_confers_owner():
    set_active_grant(42, "read_write")
    assert grant_satisfies(42, access="write", require_owner=True) is False
