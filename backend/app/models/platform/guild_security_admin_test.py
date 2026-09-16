"""The seat above admin, and the one thing it must not cost.

``security_admin`` is a third stored role. What keeps that from touching the
tenancy model is that ``app.current_guild_role`` still carries two values — it
answers what content access a request has, and a security admin's answer is an
admin's. These pin both halves: the authority it has, and the GUC it does not
widen.
"""

import pytest

from app.core.role_context import is_request_guild_admin
from app.models.platform.guild import (
    GUILD_ADMIN_ROLES,
    GUILD_ASSIGNABLE_ROLES,
    GuildRole,
    assignable_roles,
    content_role,
)
from app.services import rls as rls_service

pytestmark = pytest.mark.unit


def test_a_security_admin_carries_an_admins_authority():
    assert rls_service.is_guild_admin(GuildRole.security_admin)
    assert GuildRole.security_admin in GUILD_ADMIN_ROLES
    # And the check that raises agrees with the one that answers.
    rls_service.require_guild_admin(GuildRole.security_admin)


def test_a_member_still_does_not():
    assert not rls_service.is_guild_admin(GuildRole.member)
    with pytest.raises(Exception):
        rls_service.require_guild_admin(GuildRole.member)


def test_the_guc_still_carries_two_values():
    """The reason no RLS policy changed.

    Every ``current_guild_role = 'admin'`` leg — on ``public`` and inside every
    guild schema — keeps meaning what it meant, because a security admin
    arrives there as an admin.
    """
    assert content_role(GuildRole.security_admin) == "admin"
    assert content_role(GuildRole.admin) == "admin"
    assert content_role(GuildRole.member) == "member"


def test_the_context_helper_accepts_either_stored_role():
    assert is_request_guild_admin(1, guild_role=GuildRole.admin)
    assert is_request_guild_admin(1, guild_role=GuildRole.security_admin)
    assert not is_request_guild_admin(1, guild_role=GuildRole.member)


def test_an_ordinary_admin_cannot_hand_out_the_seat():
    """The separation: administering a community is not deciding who enters."""
    assert GuildRole.security_admin not in assignable_roles(GuildRole.admin)
    assert assignable_roles(GuildRole.admin) == GUILD_ASSIGNABLE_ROLES


def test_the_seat_is_passed_on_by_whoever_holds_it():
    """An operator seats the first one; after that the guild can carry on
    without going back to the platform for every change."""
    allowed = assignable_roles(GuildRole.security_admin)
    assert GuildRole.security_admin in allowed
    assert {GuildRole.admin, GuildRole.member} <= allowed


def test_support_is_never_assignable_by_anybody():
    """A synthesized PAM identity, not a stored membership role."""
    for by in (GuildRole.admin, GuildRole.security_admin, GuildRole.member):
        assert GuildRole.support not in assignable_roles(by)
