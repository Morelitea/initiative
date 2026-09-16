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


def test_a_guild_cannot_hand_out_the_seat_itself():
    """Not assignable from inside: an admin who could grant it would be
    granting themselves the keys, which is what the separation is for."""
    assert GuildRole.security_admin not in GUILD_ASSIGNABLE_ROLES
    assert GuildRole.support not in GUILD_ASSIGNABLE_ROLES
    assert GUILD_ASSIGNABLE_ROLES == {GuildRole.admin, GuildRole.member}
