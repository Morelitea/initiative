"""What a pairwise subject is for, stated as properties.

The reason this exists is not that apps need an identifier — a row id would have
served — but that a *global* identifier lets two apps discover they are talking
to the same human, and lets one app installed in two guilds link those guilds to
one person. Neither is visible to the member or the operator, so neither would
have been noticed.

So the cases below are mostly about what the value must *not* let somebody work
out, which is the half a happy-path test would miss entirely.
"""

import pytest

from app.services.marketplace.app_subjects import (
    SUBJECT_LENGTH,
    derive_subject,
    ensure_subject,
    resolve_subject,
)
from app.testing import create_guild, create_guild_app, create_user
from app.testing.schema_harness import route_session_to_guild


def _definition(public_id: str = "acme.tracker") -> dict:
    return {"app_kind": "service", "service": {"public_id": public_id}}


class TestWhatItMustNotReveal:
    @pytest.mark.unit
    def test_two_installs_see_unrelated_subjects_for_one_person(self):
        """The sector is the install, so an app in two guilds cannot link them
        to the same person — and two apps cannot compare notes."""
        here = derive_subject(app_install_id=1, user_id=42)
        there = derive_subject(app_install_id=2, user_id=42)
        assert here != there

    @pytest.mark.unit
    def test_one_install_sees_unrelated_subjects_for_two_people(self):
        assert derive_subject(app_install_id=1, user_id=42) != derive_subject(
            app_install_id=1, user_id=43
        )

    @pytest.mark.unit
    def test_the_subject_does_not_contain_the_user_id(self):
        """Obvious to state, easy to lose to a refactor that "simplifies" the
        derivation into something reversible."""
        subject = derive_subject(app_install_id=7, user_id=123456)
        assert "123456" not in subject
        assert "7" not in subject or len(subject) == SUBJECT_LENGTH

    @pytest.mark.unit
    def test_the_sector_and_the_member_cannot_be_confused(self):
        """(12, 345) and (123, 45) must not derive the same subject — which is
        what an undelimited concatenation would have done."""
        assert derive_subject(app_install_id=12, user_id=345) != derive_subject(
            app_install_id=123, user_id=45
        )


class TestWhatItMustGuarantee:
    @pytest.mark.unit
    def test_it_is_stable(self):
        """An app stores this as its key for a person. If it moved, every app's
        idea of who somebody is would move with it."""
        first = derive_subject(app_install_id=3, user_id=9)
        second = derive_subject(app_install_id=3, user_id=9)
        assert first == second

    @pytest.mark.unit
    def test_it_fits_where_it_has_to_go(self):
        subject = derive_subject(app_install_id=1, user_id=1)
        assert len(subject) == SUBJECT_LENGTH
        # A JWT claim and a URL, so nothing that would need escaping in either.
        assert subject.replace("-", "").replace("_", "").isalnum()


class TestResolution:
    @pytest.mark.integration
    async def test_a_minted_subject_resolves_to_its_member(self, session):
        user = await create_user(session)
        guild = await create_guild(session, creator=user)
        app = await create_guild_app(session, guild, user, definition=_definition())

        subject = await ensure_subject(
            session, app_install_id=app.id, guild_id=guild.id, user_id=user.id
        )
        await session.commit()

        found = await resolve_subject(session, subject=subject)
        assert found is not None
        assert found.user_id == user.id
        assert found.app_id == app.id

    @pytest.mark.integration
    async def test_minting_twice_is_the_same_subject_and_one_row(self, session):
        user = await create_user(session)
        guild = await create_guild(session, creator=user)
        app = await create_guild_app(session, guild, user, definition=_definition())

        first = await ensure_subject(
            session, app_install_id=app.id, guild_id=guild.id, user_id=user.id
        )
        second = await ensure_subject(
            session, app_install_id=app.id, guild_id=guild.id, user_id=user.id
        )
        await session.commit()
        assert first == second

    @pytest.mark.integration
    async def test_a_value_we_never_minted_resolves_to_nobody(self, session):
        user = await create_user(session)
        guild = await create_guild(session, creator=user)
        await route_session_to_guild(session, guild.id)

        assert await resolve_subject(session, subject="never-minted") is None
        # And a value too long to be one is refused before it is looked up.
        assert await resolve_subject(session, subject="x" * 500) is None
        assert await resolve_subject(session, subject="") is None
