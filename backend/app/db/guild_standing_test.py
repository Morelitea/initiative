"""The standing answers the community's ladder for a request."""

from __future__ import annotations


from app.db.guild_standing import GuildContext
from app.models.platform.guild import GuildRole


def _context(**fields) -> GuildContext:
    return GuildContext(guild=None, user_id=1, guild_id=7, **fields)


def test_a_member_reaches_the_member_rung_and_no_further():
    c = _context(membership=object(), guild_role="member")
    assert c.reaches(GuildRole.support)
    assert c.reaches(GuildRole.member)
    assert not c.reaches(GuildRole.admin)
    assert not c.reaches(GuildRole.superadmin)
    assert c.rung is GuildRole.member


def test_an_admin_reaches_admin_by_the_standing_and_not_the_seat():
    c = _context(membership=object(), guild_role="admin", admin=True)
    assert c.reaches(GuildRole.admin)
    assert not c.reaches(GuildRole.superadmin)
    assert c.rung is GuildRole.admin


def test_the_seat_reaches_every_rung():
    c = _context(membership=object(), guild_role="superadmin", admin=True, seat=True)
    assert all(c.reaches(r) for r in GuildRole)
    assert c.rung is GuildRole.superadmin


def test_a_settings_grant_reaches_the_rung_it_lends_on_the_settings_surface():
    lent_admin = _context(settings_grant_level="admin", settings_rung="admin")
    assert lent_admin.reaches(GuildRole.admin, settings=True)
    assert not lent_admin.reaches(GuildRole.superadmin, settings=True)
    assert not lent_admin.reaches(GuildRole.member, settings=True)
    assert lent_admin.rung is GuildRole.admin

    lent_seat = _context(
        settings_grant_level="superadmin", settings_rung="superadmin", seat=True
    )
    assert lent_seat.reaches(GuildRole.admin, settings=True)
    assert lent_seat.reaches(GuildRole.superadmin, settings=True)
    assert lent_seat.rung is GuildRole.superadmin


def test_a_settings_grant_lends_no_rung_off_the_settings_surface():
    lent_admin = _context(settings_grant_level="admin", settings_rung="admin")
    assert not lent_admin.reaches(GuildRole.admin)

    lent_seat = _context(
        settings_grant_level="superadmin", settings_rung="superadmin", seat=True
    )
    assert not lent_seat.reaches(GuildRole.admin)
    assert not lent_seat.reaches(GuildRole.superadmin)


def test_a_content_grant_reaches_nothing_on_the_ladder():
    c = _context(grant=object(), pam_read=True)
    assert c.reaches(GuildRole.support)
    assert not c.reaches(GuildRole.member)
    assert not c.reaches(GuildRole.admin)
    assert c.rung is GuildRole.support
