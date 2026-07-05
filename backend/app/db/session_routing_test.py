"""Unit tests for the role-routing decision in ``_render_context_bind_params``.

The pure function is the single place that decides which Postgres role a
request assumes; these pin the ``read_only`` (guild lifecycle status) leg
against the pre-existing PAM read-grant leg.
"""

import pytest

from app.db.schema_provisioning import guild_readonly_role_name, guild_role_name
from app.db.session import _render_context_bind_params

pytestmark = pytest.mark.unit


def _params(**overrides):
    base = {
        "user_id": 7,
        "guild_id": None,
        "guild_role": None,
        "pam_guild_id": None,
        "pam_read": False,
        "pam_write": False,
        "platform_role": None,
        "read_only": False,
    }
    base.update(overrides)
    return base


def test_member_routes_to_full_guild_role():
    bind = _render_context_bind_params(_params(guild_id=3, guild_role="member"))
    assert bind["role"] == guild_role_name(3)
    assert bind["gid"] == "3"


def test_read_only_member_routes_to_ro_role_keeping_membership_gucs():
    """A member of a read_only guild assumes the SELECT-only role while the
    membership GUCs stay set — writes die in Postgres, reads (and the
    member/admin RLS legs) behave normally."""
    bind = _render_context_bind_params(
        _params(guild_id=3, guild_role="member", read_only=True)
    )
    assert bind["role"] == guild_readonly_role_name(3)
    assert bind["gid"] == "3"
    assert bind["grole"] == "member"


def test_read_only_admin_also_routes_to_ro_role():
    bind = _render_context_bind_params(
        _params(guild_id=3, guild_role="admin", read_only=True)
    )
    assert bind["role"] == guild_readonly_role_name(3)
    assert bind["grole"] == "admin"


def test_pam_read_grant_still_routes_to_ro_role():
    bind = _render_context_bind_params(_params(pam_guild_id=3, pam_read=True))
    assert bind["role"] == guild_readonly_role_name(3)
    assert bind["gid"] == ""


def test_pam_write_grant_keeps_full_role_regardless_of_read_only_flag():
    """The read_only flag is a membership-path concept; the PAM write route is
    untouched (grants override the guild status)."""
    bind = _render_context_bind_params(
        _params(pam_guild_id=3, pam_read=True, pam_write=True)
    )
    assert bind["role"] == guild_role_name(3)
