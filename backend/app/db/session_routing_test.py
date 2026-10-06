"""Which role and path each routing shape assumes, and what it writes.

``_bind_params`` renders a shape into the one statement that routes a
transaction; these pin the role picked for each kind of access, the schemas it
resolves in, and the variables that say which community it is.
"""

import pytest

from app.db.guild_standing import GuildContext, InstallContext
from app.db.request_context import (
    Billing,
    ContentGrantee,
    Install,
    Member,
    Platform,
    SettingsGrantee,
    SystemGuild,
    Unattributed,
)
from app.db.schema_provisioning import (
    GuildRoleKind,
    guild_role_name,
    guild_schema_name,
)
from app.db.session import _bind_params

_STANDING = GuildContext(guild=None, user_id=7, guild_id=3)


def _member(**overrides) -> dict[str, str]:
    return _bind_params(Member(guild_id=3, user_id=7, standing=_STANDING, **overrides))


def _grantee(**overrides) -> dict[str, str]:
    return _bind_params(ContentGrantee(guild_id=3, user_id=7, **overrides))


def _settings(**overrides) -> dict[str, str]:
    return _bind_params(
        SettingsGrantee(guild_id=3, user_id=7, standing=_STANDING, **overrides)
    )


def test_a_member_routes_by_the_community_and_its_hold():
    """A member assumes the community's role; in a ``read_only`` community the
    SELECT-only one, with the community still named — writes die in Postgres,
    reads and the membership legs behave normally. A standing that also shows a
    grant does not change a member's role."""
    member = _member()
    assert (member["role"], member["current_guild_id"]) == (guild_role_name(3), "3")
    held = _member(read_only=True)
    assert held["role"] == guild_role_name(3, GuildRoleKind.read_only)
    assert held["current_guild_id"] == "3"
    granted = _STANDING.with_standing(
        {"standing_guild_id": "3", "pam_read": "true", "pam_write": "true"}
    )
    also_granted = _bind_params(Member(guild_id=3, user_id=7, standing=granted))
    assert also_granted["role"] == guild_role_name(3)


def test_a_content_grant_routes_by_its_level():
    """A read grant reads; a read_write grant is the restricted ``support``
    role — no member or permission-table writes. Either names the community
    on its own axis, never as a membership."""
    read = _grantee()
    assert read["role"] == guild_role_name(3, GuildRoleKind.read_only)
    assert (read["current_guild_id"], read["pam_guild_id"]) == ("", "3")
    write = _grantee(read_write=True)
    assert write["role"] == guild_role_name(3, GuildRoleKind.support)


def test_a_settings_grant_reads_and_carries_no_content_flags():
    out = _settings()
    assert out["role"] == guild_role_name(3, GuildRoleKind.read_only)
    assert out["search_path"] == f"{guild_schema_name(3)}, public, pg_temp"
    assert (out["current_guild_id"], out["pam_guild_id"], out["settings_guild_id"]) == (
        "",
        "",
        "3",
    )
    assert (out["pam_read"], out["pam_write"]) == ("false", "false")


def test_break_glass_names_the_community_on_both_axes():
    """Break-glass is a pair: the settings half names the community on its own
    axis, and the content half is what picks the role."""
    read = _grantee(settings=True)
    assert read["role"] == guild_role_name(3, GuildRoleKind.read_only)
    assert (read["pam_guild_id"], read["settings_guild_id"]) == ("3", "3")
    write = _grantee(settings=True, read_write=True)
    assert write["role"] == guild_role_name(3, GuildRoleKind.support)


def test_the_seat_is_asked_for_not_held():
    """``guild_<id>_superadmin`` is assumed by a seat route, by a member or a
    settings grantee; an ordinary request by the same person routes the
    ordinary way."""
    assert _member(seat=True)["role"] == guild_role_name(3, GuildRoleKind.seat)
    assert _settings(seat=True)["role"] == guild_role_name(3, GuildRoleKind.seat)
    assert _member()["role"] == guild_role_name(3)


def test_a_query_sees_its_own_community_alone():
    out = _member(query=True, scope_initiative_id=9)
    assert out["role"] == guild_role_name(3, GuildRoleKind.query)
    assert out["search_path"] == f"{guild_schema_name(3)}, pg_temp"
    assert (out["query"], out["scope_initiative_id"]) == ("true", "9")


@pytest.mark.parametrize(
    "shape",
    [
        Member(guild_id=3, user_id=7, standing=_STANDING),
        ContentGrantee(guild_id=3, user_id=7),
        SettingsGrantee(guild_id=3, user_id=7, standing=_STANDING),
        SystemGuild(3),
        SystemGuild(3, read_only=True),
        Platform(user_id=7, tier="owner"),
        Billing(5),
        Unattributed(),
    ],
    ids=[
        "member",
        "grantee",
        "settings",
        "system",
        "system-read-only",
        "platform",
        "billing",
        "unrouted",
    ],
)
def test_every_route_names_its_schemas_and_ends_at_pg_temp(shape):
    """Guild content resolves in the guild schema first; the platform and
    billing routes resolve in ``public``. One helper renders them all, so no
    route can drift off the pattern."""
    expected = (
        f"{guild_schema_name(3)}, public, pg_temp"
        if shape.guild_id is not None
        else "public, pg_temp"
    )
    assert _bind_params(shape)["search_path"] == expected


class TestTheInstallRoute:
    """An installed app routes into the community's app role, as nobody."""

    def _install(self, **overrides):
        return _bind_params(
            Install(
                **{
                    "guild_id": 3,
                    "install_id": 5,
                    "standing": InstallContext(
                        guild_id=3,
                        install_id=5,
                        client_id="tests.app",
                        token_scopes=frozenset(),
                    ),
                    "token_client_id": "tests.app",
                    "token_scopes": frozenset({"documents:write", "comments:read"}),
                    **overrides,
                }
            )
        )

    def test_it_assumes_the_plugin_role_and_names_no_person(self):
        out = self._install(scope_initiative_id=9)
        assert out["role"] == guild_role_name(3, GuildRoleKind.app)
        assert out["search_path"] == f"{guild_schema_name(3)}, public, pg_temp"
        assert (out["current_user_id"], out["current_guild_id"]) == ("", "3")
        assert (
            out["pam_guild_id"],
            out["settings_guild_id"],
            out["pam_read"],
            out["pam_write"],
        ) == ("", "", "false", "false")
        assert out["current_install_id"] == "5"
        assert out["token_client_id"] == "tests.app"
        assert out["token_scopes"] == "comments:read,documents:write"
        assert out["scope_initiative_id"] == "9"

    def test_until_its_standing_is_computed_it_stands_nowhere(self):
        out = self._install()
        assert out["guild_auth_ok"] == "false"
        assert (
            out["standing_guild_id"],
            out["member_initiatives"],
            out["role_grants"],
            out["install_read"],
        ) == ("", "", "", "")

    def test_a_person_route_names_no_install(self):
        out = _member()
        assert (
            out["current_install_id"],
            out["token_client_id"],
            out["token_scopes"],
            out["install_read"],
        ) == ("", "", "", "")
