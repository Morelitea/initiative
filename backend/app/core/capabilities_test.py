"""Unit tests for the platform capability model."""

import pytest

from app.core.capabilities import (
    Capability,
    can_assign_role,
    capabilities_for,
    roles_with_capability,
)
from app.models.user import UserRole


class _Actor:
    def __init__(self, role: UserRole):
        self.role = role


@pytest.mark.unit
def test_config_manage_is_owner_only():
    assert roles_with_capability(Capability.CONFIG_MANAGE) == frozenset(
        {UserRole.owner}
    )


@pytest.mark.unit
def test_data_bypass_is_admin_and_owner():
    assert roles_with_capability(Capability.DATA_BYPASS) == frozenset(
        {UserRole.admin, UserRole.owner}
    )


@pytest.mark.unit
def test_member_has_no_capabilities():
    assert capabilities_for(UserRole.member) == frozenset()


@pytest.mark.unit
def test_owner_can_assign_every_role():
    owner = _Actor(UserRole.owner)
    for role in UserRole:
        assert can_assign_role(owner, role) is True, role


@pytest.mark.unit
def test_admin_can_assign_up_to_admin_but_not_owner():
    admin = _Actor(UserRole.admin)
    assert can_assign_role(admin, UserRole.member) is True
    assert can_assign_role(admin, UserRole.support) is True
    assert can_assign_role(admin, UserRole.moderator) is True
    assert can_assign_role(admin, UserRole.admin) is True
    assert can_assign_role(admin, UserRole.owner) is False


@pytest.mark.unit
def test_roles_without_assign_capability_cannot_assign():
    for role in (UserRole.member, UserRole.support, UserRole.moderator):
        assert can_assign_role(_Actor(role), UserRole.member) is False
