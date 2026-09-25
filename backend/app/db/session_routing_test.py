"""Unit tests for the role-routing decision in ``_render_context_bind_params``.

The pure function is the single place that decides which Postgres role a
request assumes; these pin the ``read_only`` (guild lifecycle status) leg
against the pre-existing PAM read-grant leg.
"""

import pytest

from app.db.schema_provisioning import (
    guild_app_role_name,
    guild_readonly_role_name,
    guild_schema_name,
    guild_role_name,
    guild_superadmin_role_name,
    guild_support_role_name,
)
from app.db.session import _render_context_bind_params


def _params(**overrides):
    base = {
        "user_id": 7,
        "guild_id": None,
        "context": None,
        "pam_guild_id": None,
        "pam_read": False,
        "pam_write": False,
        "settings_guild_id": None,
        "seat": False,
        "platform_role": None,
        "read_only": False,
    }
    base.update(overrides)
    return base


def test_member_routes_to_full_guild_role():
    bind = _render_context_bind_params(_params(guild_id=3))
    assert bind["role"] == guild_role_name(3)
    assert bind["gid"] == "3"


def test_read_only_member_routes_to_ro_role_keeping_membership_gucs():
    """A member of a read_only community assumes the SELECT-only role while the
    community context stays set — writes die in Postgres, reads (and the
    membership legs, once the standing is computed) behave normally."""
    bind = _render_context_bind_params(_params(guild_id=3, read_only=True))
    assert bind["role"] == guild_readonly_role_name(3)
    assert bind["gid"] == "3"


def test_read_only_admin_also_routes_to_ro_role():
    bind = _render_context_bind_params(_params(guild_id=3, read_only=True))
    assert bind["role"] == guild_readonly_role_name(3)


def test_pam_read_grant_still_routes_to_ro_role():
    bind = _render_context_bind_params(_params(pam_guild_id=3, pam_read=True))
    assert bind["role"] == guild_readonly_role_name(3)
    assert bind["gid"] == ""


def test_pam_write_grant_routes_to_support_role():
    """A scoped read_write grant (the ``support`` identity) routes into the
    restricted ``guild_<id>_support`` role — not the full member role — so its
    write cap (no member/permission-table writes) is Postgres-enforced."""
    bind = _render_context_bind_params(
        _params(pam_guild_id=3, pam_read=True, pam_write=True)
    )
    assert bind["role"] == guild_support_role_name(3)


def test_settings_grant_routes_without_content_grant_flags():
    """A settings rung on its own reads: the SELECT-only role, no content flags."""
    bind = _render_context_bind_params(_params(settings_guild_id=3))
    assert bind["role"] == guild_readonly_role_name(3)
    assert bind["sp"] == f"{guild_schema_name(3)}, public, pg_temp"
    assert bind["gid"] == ""
    assert bind["pgid"] == ""
    assert bind["pr"] == "false"
    assert bind["pw"] == "false"


def test_member_and_break_glass_keep_full_role():
    """A real member / break-glass (guild_id set) keeps the full role — only a
    scoped grant (guild_id unset) is downgraded to _ro / _support."""
    member = _render_context_bind_params(_params(guild_id=3))
    assert member["role"] == guild_role_name(3)
    # break-glass routes with guild_id set beside its grant
    bg = _render_context_bind_params(
        _params(guild_id=3, pam_guild_id=3, pam_write=True)
    )
    assert bg["role"] == guild_role_name(3)


class TestSearchPathNamesEverySchema:
    """The routed path names every schema it resolves against, in priority
    order, ending at ``pg_temp`` (see ``_search_path``). Guild content resolves
    in the guild schema first; the platform and billing routes resolve in
    ``public``."""

    def test_guild_route_names_guild_schema_then_public(self):
        out = _render_context_bind_params(_params(guild_id=3))
        assert out["sp"] == f"{guild_schema_name(3)}, public, pg_temp"

    def test_platform_route_names_public(self):
        out = _render_context_bind_params(_params(platform_role="member"))
        assert out["sp"] == "public, pg_temp"

    def test_billing_route_names_public(self):
        out = _render_context_bind_params(_params(billing_guild_id=5))
        assert out["sp"] == "public, pg_temp"

    @pytest.mark.parametrize(
        "overrides",
        [
            {"guild_id": 3},
            {"guild_id": 3, "read_only": True},
            {"pam_guild_id": 4, "pam_read": True},
            {"pam_guild_id": 4, "pam_write": True},
            {"settings_guild_id": 4},
            {"platform_role": "owner"},
            {"billing_guild_id": 5},
            {},
        ],
        ids=[
            "member",
            "read-only",
            "pam-read",
            "pam-write",
            "settings",
            "platform",
            "billing",
            "unrouted",
        ],
    )
    def test_every_route_ends_at_pg_temp(self, overrides):
        """One helper renders them all, so no route can drift off the pattern."""
        out = _render_context_bind_params(_params(**overrides))
        assert out["sp"].endswith(", pg_temp")


class TestTheInstallRoute:
    """An installed app routes into the community's app role, as nobody."""

    def _install(self, **overrides):
        return _render_context_bind_params(
            {
                "guild_id": 3,
                "install_id": 5,
                "token_client_id": "tests.app",
                "token_scopes": frozenset({"documents:write", "comments:read"}),
                **overrides,
            }
        )

    def test_it_assumes_the_app_role_and_names_no_person(self):
        out = self._install()
        assert out["role"] == guild_app_role_name(3)
        assert out["sp"] == f"{guild_schema_name(3)}, public, pg_temp"
        assert out["uid"] == ""
        assert out["gid"] == "3"
        assert (out["pgid"], out["setgid"], out["pr"], out["pw"]) == (
            "",
            "",
            "false",
            "false",
        )
        assert out["iid"] == "5"
        assert out["tcid"] == "tests.app"
        assert out["tsc"] == "comments:read,documents:write"

    def test_until_its_standing_is_computed_it_stands_nowhere(self):
        out = self._install()
        assert out["gok"] == "false"
        assert (out["sgid"], out["minit"], out["rgr"], out["iread"]) == (
            "",
            "",
            "",
            "",
        )

    def test_it_narrows_to_one_initiative(self):
        assert self._install(scope_initiative_id=9)["sinit"] == "9"

    def test_a_person_route_names_no_install(self):
        out = _render_context_bind_params(_params(guild_id=3))
        assert (out["iid"], out["tcid"], out["tsc"], out["iread"]) == ("", "", "", "")


class TestTheSeatRoute:
    """``guild_<id>_superadmin`` is assumed by asking for it, not by holding
    the seat: an ordinary request routes the ordinary way."""

    def test_a_seat_request_by_a_member_assumes_the_seat_role(self):
        out = _render_context_bind_params(_params(guild_id=3, seat=True))
        assert out["role"] == guild_superadmin_role_name(3)
        assert out["gid"] == "3"

    def test_a_seat_request_by_a_settings_grantee_assumes_it_too(self):
        out = _render_context_bind_params(_params(settings_guild_id=4, seat=True))
        assert out["role"] == guild_superadmin_role_name(4)
        assert out["setgid"] == "4"

    def test_an_ordinary_request_by_the_same_person_does_not(self):
        out = _render_context_bind_params(_params(guild_id=3))
        assert out["role"] == guild_role_name(3)

    def test_a_settings_grant_beside_a_read_grant_still_reads_read_only(self):
        """Break-glass is a pair. The settings half names the community on its
        own axis; the content half is what picks the role."""
        out = _render_context_bind_params(
            _params(pam_guild_id=4, pam_read=True, settings_guild_id=4)
        )
        assert out["role"] == guild_readonly_role_name(4)
        assert out["setgid"] == "4"

    def test_a_settings_only_grant_reads(self):
        """The rung alone is a view; a read_write grant beside it is what
        picks the writable role."""
        out = _render_context_bind_params(_params(settings_guild_id=4))
        assert out["role"] == guild_readonly_role_name(4)
        paired = _render_context_bind_params(
            _params(pam_guild_id=4, pam_write=True, settings_guild_id=4)
        )
        assert paired["role"] == guild_support_role_name(4)
