"""The seat above admin, and the one thing it must not cost.

``superadmin`` is a third stored role. What keeps that from touching the
tenancy model is that ``app.current_guild_role`` still carries two values — it
answers what content access a request has, and a superadmin's answer is an
admin's. These pin both halves: the authority it has, and the GUC it does not
widen.
"""

import pytest
from fastapi import HTTPException

from app.api import deps
from app.core.role_context import is_request_guild_admin
from app.models.platform.guild import (
    CONTENT_ROLES,
    GUILD_ADMIN_ROLES,
    GUILD_ASSIGNABLE_ROLES,
    GUILD_STORED_ROLES,
    Guild,
    GuildMembership,
    GuildRole,
    assignable_roles,
    content_role,
)
from app.services import rls as rls_service

pytestmark = pytest.mark.unit


def test_a_superadmin_carries_an_admins_authority():
    assert rls_service.is_guild_admin(GuildRole.superadmin)
    assert GuildRole.superadmin in GUILD_ADMIN_ROLES
    # And the check that raises agrees with the one that answers.
    rls_service.require_guild_admin(GuildRole.superadmin)


def test_a_member_still_does_not():
    assert not rls_service.is_guild_admin(GuildRole.member)
    with pytest.raises(Exception):
        rls_service.require_guild_admin(GuildRole.member)


def test_the_guc_still_carries_two_values():
    """The reason no RLS policy changed.

    Every ``current_guild_role = 'admin'`` leg — on ``public`` and inside every
    guild schema — keeps meaning what it meant, because a superadmin
    arrives there as an admin.
    """
    assert content_role(GuildRole.superadmin) == "admin"
    assert content_role(GuildRole.admin) == "admin"
    assert content_role(GuildRole.member) == "member"
    # Said once more from the other end: three roles can sit in a membership
    # row, and putting all three through ``content_role`` yields two values.
    # ``superadmin`` is deliberately absent from the result — it arrives as
    # ``admin``, which is what lets every policy leg stay as it was written.
    assert GuildRole.superadmin in GUILD_STORED_ROLES
    assert GuildRole.superadmin.value not in CONTENT_ROLES
    assert {content_role(role) for role in GUILD_STORED_ROLES} == CONTENT_ROLES
    assert CONTENT_ROLES == {"admin", "member"}


def test_support_is_not_a_stored_role():
    """It is synthesized for the length of a PAM request, so it never reaches
    the GUC — which is why ``content_role`` is not asked about it."""
    assert GuildRole.support not in GUILD_STORED_ROLES
    assert GUILD_STORED_ROLES == frozenset(GuildRole) - {GuildRole.support}


def test_the_context_helper_accepts_either_stored_role():
    assert is_request_guild_admin(1, guild_role=GuildRole.admin)
    assert is_request_guild_admin(1, guild_role=GuildRole.superadmin)
    assert not is_request_guild_admin(1, guild_role=GuildRole.member)


def test_an_ordinary_admin_cannot_hand_out_the_seat():
    """The separation: administering a community is not deciding who enters."""
    assert GuildRole.superadmin not in assignable_roles(GuildRole.admin)
    assert assignable_roles(GuildRole.admin) == GUILD_ASSIGNABLE_ROLES


def test_the_seat_is_passed_on_by_whoever_holds_it():
    """An operator seats the first one; after that the guild can carry on
    without going back to the platform for every change."""
    allowed = assignable_roles(GuildRole.superadmin)
    assert GuildRole.superadmin in allowed
    assert {GuildRole.admin, GuildRole.member} <= allowed


def test_support_is_never_assignable_by_anybody():
    """A synthesized PAM identity, not a stored membership role."""
    for by in (GuildRole.admin, GuildRole.superadmin, GuildRole.member):
        assert GuildRole.support not in assignable_roles(by)


def _context(role: GuildRole) -> deps.GuildContext:
    return deps.GuildContext(
        guild=Guild(id=1, name="g"),
        membership=GuildMembership(guild_id=1, user_id=2, role=role),
    )


def test_the_context_answers_admin_or_above():
    assert _context(GuildRole.admin).is_admin
    assert _context(GuildRole.superadmin).is_admin
    assert not _context(GuildRole.member).is_admin


async def test_a_guard_asking_for_admin_admits_the_seat_above_it():
    """The dependency every guild-admin endpoint is written against.

    Each of those endpoints names ``admin``; this is the one place that reads
    that as admin-or-above, so the seat reaches all of them at once.
    """
    guard = deps.require_guild_roles(GuildRole.admin)
    for role in (GuildRole.admin, GuildRole.superadmin):
        assert (await guard(_context(role))).role == role


async def test_that_guard_still_turns_a_member_away():
    guard = deps.require_guild_roles(GuildRole.admin)
    with pytest.raises(HTTPException) as caught:
        await guard(_context(GuildRole.member))
    assert caught.value.status_code == 403


async def test_a_guard_naming_other_roles_is_left_alone():
    """Widening applies to the ``admin`` rung, not to every guard."""
    guard = deps.require_guild_roles(GuildRole.member)
    with pytest.raises(HTTPException):
        await guard(_context(GuildRole.superadmin))


def test_a_claim_rule_cannot_name_the_seat():
    """What an identity provider's rules may hand out.

    The mapping surface stores a role as a string, and the set it validates
    against is derived from the same one the guild's own endpoints use, so the
    seat stays off it by construction rather than by a second list agreeing.
    """
    from app.api.v1.platform_endpoints.settings import _MAPPABLE_GUILD_ROLES

    assert GuildRole.superadmin.value not in _MAPPABLE_GUILD_ROLES
    assert GuildRole.support.value not in _MAPPABLE_GUILD_ROLES
    assert _MAPPABLE_GUILD_ROLES == {r.value for r in GUILD_ASSIGNABLE_ROLES}
