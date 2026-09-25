"""Unit tests for the platform capability model."""

from app.core.capabilities import (
    Capability,
    can_assign_role,
    capabilities_for,
    role_rank,
    roles_with_capability,
    standing_capabilities,
    user_has_capability,
)
from app.models.platform.user import UserRole, UserStatus


class _Actor:
    def __init__(self, role: UserRole, status: UserStatus = UserStatus.active):
        self.role = role
        self.status = status


def test_a_suspended_account_holds_no_capability():
    """Whatever its rung: it is in time out, and the rung comes back on lifting."""
    for role in UserRole:
        assert standing_capabilities(role, UserStatus.suspended) == frozenset()
        assert standing_capabilities(role, UserStatus.active) == capabilities_for(role)
    assert not user_has_capability(
        _Actor(UserRole.owner, UserStatus.suspended), Capability.CONFIG_MANAGE
    )


def test_config_manage_is_owner_only():
    assert roles_with_capability(Capability.CONFIG_MANAGE) == frozenset(
        {UserRole.owner}
    )


def test_apps_manage_is_owner_only():
    """Wiring an app service is deployment configuration — the same tier
    ``config.manage`` occupies, and no lower one."""
    assert roles_with_capability(Capability.APPS_MANAGE) == frozenset({UserRole.owner})


def test_data_bypass_is_operator_and_owner():
    assert roles_with_capability(Capability.DATA_BYPASS) == frozenset(
        {UserRole.operator, UserRole.owner}
    )


def test_access_approve_is_operator_and_owner():
    """Approvers are also the ones who read the full access-grant queue."""
    assert roles_with_capability(Capability.ACCESS_APPROVE) == frozenset(
        {UserRole.operator, UserRole.owner}
    )


def test_role_rank_follows_the_ladder():
    ladder = [
        UserRole.member,
        UserRole.support,
        UserRole.moderator,
        UserRole.operator,
        UserRole.owner,
    ]
    assert [role_rank(role) for role in ladder] == list(range(len(ladder)))
    assert sorted(UserRole, key=role_rank) == ladder


def test_member_has_no_capabilities():
    assert capabilities_for(UserRole.member) == frozenset()


def test_owner_can_assign_every_role():
    owner = _Actor(UserRole.owner)
    for role in UserRole:
        assert can_assign_role(owner, role) is True, role


def test_operator_can_assign_up_to_operator_but_not_owner():
    operator = _Actor(UserRole.operator)
    assert can_assign_role(operator, UserRole.member) is True
    assert can_assign_role(operator, UserRole.support) is True
    assert can_assign_role(operator, UserRole.moderator) is True
    assert can_assign_role(operator, UserRole.operator) is True
    assert can_assign_role(operator, UserRole.owner) is False


def test_roles_without_assign_capability_cannot_assign():
    for role in (UserRole.member, UserRole.support, UserRole.moderator):
        assert can_assign_role(_Actor(role), UserRole.member) is False
