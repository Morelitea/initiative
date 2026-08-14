"""What a pairwise subject is for, stated as properties.

The reason this exists is not that apps need an identifier — a row id would have
served — but that a *global* identifier lets two apps discover they are talking
to the same human, and lets one app installed in two guilds link those guilds to
one person. Neither is visible to the member or the operator, so neither would
have been noticed.

So most of these are about what the value must not let somebody work out, and
one is about what must never move: an app stores `sub` as its key for a person,
so a subject that changed under them would strand every one of those keys.
"""

import pytest

from app.core import config as config_module
from app.services.marketplace.app_subjects import (
    SUBJECT_LENGTH,
    ensure_subject,
    mint_subject,
    resolve_subject,
)
from app.testing import create_guild, create_guild_app, create_user
from app.testing.schema_harness import route_session_to_guild


def _definition(public_id: str = "acme.tracker") -> dict:
    return {"app_kind": "service", "service": {"public_id": public_id}}


async def _install(
    session, guild, user, *, listing_uid="TESTAPP0000001", public_id="acme.tracker"
):
    return await create_guild_app(
        session, guild, user, definition=_definition(public_id), listing_uid=listing_uid
    )


class TestTheValueItself:
    @pytest.mark.unit
    def test_it_fits_where_it_has_to_go(self):
        subject = mint_subject()
        assert len(subject) == SUBJECT_LENGTH
        # A JWT claim and a URL, so nothing that would need escaping in either.
        assert subject.replace("-", "").replace("_", "").isalnum()

    @pytest.mark.unit
    def test_it_is_not_guessable(self):
        assert len({mint_subject() for _ in range(200)}) == 200


class TestWhatItMustNotReveal:
    @pytest.mark.integration
    async def test_two_installs_name_one_person_differently(self, session):
        """The sector is the install, so an app in two guilds cannot link them
        to the same person — and two apps cannot compare notes."""
        user = await create_user(session)
        guild = await create_guild(session, creator=user)
        first = await _install(session, guild, user)
        second = await _install(
            session, guild, user, listing_uid="SECONDAPP00001", public_id="acme.second"
        )

        here = await ensure_subject(
            session, app_install_id=first.id, guild_id=guild.id, user_id=user.id
        )
        there = await ensure_subject(
            session, app_install_id=second.id, guild_id=guild.id, user_id=user.id
        )
        await session.commit()
        assert here != there

    @pytest.mark.integration
    async def test_one_install_names_two_people_differently(self, session):
        first = await create_user(session)
        second = await create_user(session)
        guild = await create_guild(session, creator=first)
        app = await _install(session, guild, first)

        one = await ensure_subject(
            session, app_install_id=app.id, guild_id=guild.id, user_id=first.id
        )
        two = await ensure_subject(
            session, app_install_id=app.id, guild_id=guild.id, user_id=second.id
        )
        await session.commit()
        assert one != two


class TestWhatMustNeverMove:
    @pytest.mark.integration
    async def test_minting_twice_gives_the_same_subject(self, session):
        user = await create_user(session)
        guild = await create_guild(session, creator=user)
        app = await _install(session, guild, user)

        first = await ensure_subject(
            session, app_install_id=app.id, guild_id=guild.id, user_id=user.id
        )
        second = await ensure_subject(
            session, app_install_id=app.id, guild_id=guild.id, user_id=user.id
        )
        await session.commit()
        assert first == second

    @pytest.mark.integration
    async def test_it_survives_a_secret_key_rotation(self, session, monkeypatch):
        """The property the first cut of this got wrong. An app stores `sub` as
        its key for a person; a subject derived from a rotating key would move
        under them, stranding every one of those keys with nothing on either
        side to notice."""
        user = await create_user(session)
        guild = await create_guild(session, creator=user)
        app = await _install(session, guild, user)

        before = await ensure_subject(
            session, app_install_id=app.id, guild_id=guild.id, user_id=user.id
        )
        await session.commit()

        monkeypatch.setattr(
            config_module.settings, "SECRET_KEY", "a-completely-new-key"
        )

        after = await ensure_subject(
            session, app_install_id=app.id, guild_id=guild.id, user_id=user.id
        )
        await session.commit()
        assert after == before
        # And it still resolves, which is the half that would strand an app.
        found = await resolve_subject(session, subject=before)
        assert found is not None and found.user_id == user.id


class TestResolution:
    @pytest.mark.integration
    async def test_a_minted_subject_resolves_to_its_member_and_install(self, session):
        user = await create_user(session)
        guild = await create_guild(session, creator=user)
        app = await _install(session, guild, user)

        subject = await ensure_subject(
            session, app_install_id=app.id, guild_id=guild.id, user_id=user.id
        )
        await session.commit()

        found = await resolve_subject(session, subject=subject)
        assert found is not None
        assert found.user_id == user.id
        assert found.app_id == app.id

    @pytest.mark.integration
    async def test_a_value_we_never_minted_resolves_to_nobody(self, session):
        user = await create_user(session)
        guild = await create_guild(session, creator=user)
        await route_session_to_guild(session, guild.id)

        assert await resolve_subject(session, subject="never-minted") is None
        # And one too long to be ours is refused before it is looked up.
        assert await resolve_subject(session, subject="x" * 500) is None
        assert await resolve_subject(session, subject="") is None


class TestConcurrency:
    @pytest.mark.integration
    async def test_two_first_handoffs_at_once_agree_on_one_subject(self, session):
        """Two callers racing a member's first handoff both insert. One loses
        on the unique constraint, and both must read back the winner's value —
        a member with two identifiers would be two people to the app, and a
        caller that raised would be a handoff that failed for no reason the
        member could act on."""
        import asyncio

        from app.db.session import AdminSessionLocal, set_rls_context

        user = await create_user(session)
        guild = await create_guild(session, creator=user)
        app = await _install(session, guild, user)
        await session.commit()

        async def mint_in_its_own_session() -> str:
            # Separate sessions, because two coroutines on one would serialize
            # and prove nothing about the constraint.
            async with AdminSessionLocal() as own:
                await set_rls_context(own, guild_id=guild.id, guild_role="admin")
                subject = await ensure_subject(
                    own, app_install_id=app.id, guild_id=guild.id, user_id=user.id
                )
                await own.commit()
                return subject

        first, second = await asyncio.gather(
            mint_in_its_own_session(), mint_in_its_own_session()
        )
        assert first == second
