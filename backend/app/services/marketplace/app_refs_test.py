"""The properties an app reference has to hold.

The sector is the install, so a member has one reference per install, and
another again for the same app installed in a second guild. These hold that
each of those values is distinct, and that one stays put once minted.

The guild check has its own group. The value lives in a platform-wide table
now, so the guild is a predicate the resolver applies rather than the schema
the query runs in — which makes it worth holding directly.
"""

import pytest

from app.models.platform.identity_ref import (
    REF_MAX_LENGTH,
    IdentityEntity,
    IdentityPurpose,
)
from app.services.marketplace.app_refs import (
    drop_guild_app_refs,
    drop_install_refs,
    ensure_app_ref,
    reissue_app_ref,
    reissue_install_refs,
    resolve_app_ref,
)
from app.services.platform.identity_refs import REF_GRACE_PERIOD, ensure_ref
from app.testing import create_guild, create_guild_app, create_user


def _definition(public_id: str = "acme.tracker") -> dict:
    return {"app_kind": "service", "service": {"public_id": public_id}}


async def _install(
    session, guild, user, *, listing_uid="TESTAPP0000001", public_id="acme.tracker"
):
    return await create_guild_app(
        session, guild, user, definition=_definition(public_id), listing_uid=listing_uid
    )


class TestOneReferencePerSector:
    @pytest.mark.integration
    async def test_two_installs_name_one_person_differently(self, session):
        user = await create_user(session)
        guild = await create_guild(session, creator=user)
        one = await _install(session, guild, user)
        two = await _install(
            session, guild, user, listing_uid="TESTAPP0000002", public_id="other.app"
        )
        await session.commit()

        first = await ensure_app_ref(
            guild_id=guild.id, app_install_id=one.id, user_id=user.id
        )
        second = await ensure_app_ref(
            guild_id=guild.id, app_install_id=two.id, user_id=user.id
        )
        assert first != second

    @pytest.mark.integration
    async def test_one_install_names_two_people_differently(self, session):
        owner = await create_user(session)
        other = await create_user(session)
        guild = await create_guild(session, creator=owner)
        app = await _install(session, guild, owner)
        await session.commit()

        assert await ensure_app_ref(
            guild_id=guild.id, app_install_id=app.id, user_id=owner.id
        ) != await ensure_app_ref(
            guild_id=guild.id, app_install_id=app.id, user_id=other.id
        )

    @pytest.mark.integration
    async def test_one_app_in_two_guilds_names_one_person_differently(self, session):
        user = await create_user(session)
        here = await create_guild(session, creator=user)
        there = await create_guild(session, creator=user)
        app_here = await _install(session, here, user)
        app_there = await _install(session, there, user)
        await session.commit()

        assert await ensure_app_ref(
            guild_id=here.id, app_install_id=app_here.id, user_id=user.id
        ) != await ensure_app_ref(
            guild_id=there.id, app_install_id=app_there.id, user_id=user.id
        )

    @pytest.mark.integration
    async def test_minting_twice_gives_the_same_reference(self, session):
        user = await create_user(session)
        guild = await create_guild(session, creator=user)
        app = await _install(session, guild, user)
        await session.commit()

        first = await ensure_app_ref(
            guild_id=guild.id, app_install_id=app.id, user_id=user.id
        )
        assert first == await ensure_app_ref(
            guild_id=guild.id, app_install_id=app.id, user_id=user.id
        )

    @pytest.mark.unit
    def test_the_value_fits_where_it_has_to_go(self):
        # A JWT claim and a URL bound the width the install parameter accepts.
        assert REF_MAX_LENGTH >= 37


class TestTheGuildPredicate:
    @pytest.mark.integration
    async def test_a_reference_resolves_inside_its_own_guild(self, session):
        user = await create_user(session)
        guild = await create_guild(session, creator=user)
        app = await _install(session, guild, user)
        await session.commit()

        ref = await ensure_app_ref(
            guild_id=guild.id, app_install_id=app.id, user_id=user.id
        )
        row = await resolve_app_ref(session, ref=ref, guild_id=guild.id)
        assert row is not None
        assert row.entity_id == user.id
        assert row.sector_id == app.id

    @pytest.mark.integration
    async def test_it_does_not_resolve_for_another_guild(self, session):
        user = await create_user(session)
        here = await create_guild(session, creator=user)
        there = await create_guild(session, creator=user)
        app = await _install(session, here, user)
        await session.commit()

        ref = await ensure_app_ref(
            guild_id=here.id, app_install_id=app.id, user_id=user.id
        )
        assert await resolve_app_ref(session, ref=ref, guild_id=there.id) is None

    @pytest.mark.integration
    async def test_a_reference_for_another_purpose_does_not_resolve(self, session):
        user = await create_user(session)
        guild = await create_guild(session, creator=user)
        await session.commit()

        billing = await ensure_ref(
            session,
            entity_type=IdentityEntity.user,
            entity_id=user.id,
            purpose=IdentityPurpose.billing,
        )
        await session.commit()
        assert await resolve_app_ref(session, ref=billing, guild_id=guild.id) is None

    @pytest.mark.integration
    async def test_a_guild_reference_does_not_resolve_as_a_member(self, session):
        user = await create_user(session)
        guild = await create_guild(session, creator=user)
        await session.commit()

        as_guild = await ensure_ref(
            session,
            entity_type=IdentityEntity.guild,
            entity_id=guild.id,
            purpose=IdentityPurpose.app,
            sector_guild_id=guild.id,
            sector_id=1,
        )
        await session.commit()
        assert await resolve_app_ref(session, ref=as_guild, guild_id=guild.id) is None


class TestMovingOne:
    @pytest.mark.integration
    async def test_a_member_can_be_made_unrecognisable_to_an_install(self, session):
        user = await create_user(session)
        guild = await create_guild(session, creator=user)
        app = await _install(session, guild, user)
        await session.commit()

        before = await ensure_app_ref(
            guild_id=guild.id, app_install_id=app.id, user_id=user.id
        )
        after = await reissue_app_ref(
            session, guild_id=guild.id, app_install_id=app.id, user_id=user.id
        )
        await session.commit()

        assert after != before
        # In flight during the swap still lands.
        assert await resolve_app_ref(session, ref=before, guild_id=guild.id) is not None

    @pytest.mark.integration
    async def test_every_member_at_one_install_can_be_moved_together(self, session):
        owner = await create_user(session)
        other = await create_user(session)
        guild = await create_guild(session, creator=owner)
        app = await _install(session, guild, owner)
        await session.commit()

        before = {
            u.id: await ensure_app_ref(
                guild_id=guild.id, app_install_id=app.id, user_id=u.id
            )
            for u in (owner, other)
        }
        moved = await reissue_install_refs(
            session, guild_id=guild.id, app_install_id=app.id
        )
        await session.commit()

        assert moved == 2
        for user_id, old in before.items():
            assert (
                await ensure_app_ref(
                    guild_id=guild.id, app_install_id=app.id, user_id=user_id
                )
                != old
            )


class TestRemoval:
    @pytest.mark.integration
    async def test_uninstalling_removes_what_that_install_called_people(self, session):
        user = await create_user(session)
        guild = await create_guild(session, creator=user)
        going = await _install(session, guild, user)
        staying = await _install(
            session, guild, user, listing_uid="TESTAPP0000002", public_id="other.app"
        )
        await session.commit()

        gone = await ensure_app_ref(
            guild_id=guild.id, app_install_id=going.id, user_id=user.id
        )
        kept = await ensure_app_ref(
            guild_id=guild.id, app_install_id=staying.id, user_id=user.id
        )

        assert await drop_install_refs(guild_id=guild.id, app_install_id=going.id) == 1
        assert await resolve_app_ref(session, ref=gone, guild_id=guild.id) is None
        assert await resolve_app_ref(session, ref=kept, guild_id=guild.id) is not None

    @pytest.mark.integration
    async def test_deleting_a_guild_removes_its_app_references(self, session):
        user = await create_user(session)
        here = await create_guild(session, creator=user)
        there = await create_guild(session, creator=user)
        app_here = await _install(session, here, user)
        app_there = await _install(session, there, user)
        await session.commit()

        gone = await ensure_app_ref(
            guild_id=here.id, app_install_id=app_here.id, user_id=user.id
        )
        kept = await ensure_app_ref(
            guild_id=there.id, app_install_id=app_there.id, user_id=user.id
        )

        assert await drop_guild_app_refs(session, guild_id=here.id) == 1
        await session.commit()
        assert await resolve_app_ref(session, ref=gone, guild_id=here.id) is None
        assert await resolve_app_ref(session, ref=kept, guild_id=there.id) is not None

    @pytest.mark.unit
    def test_the_grace_window_is_the_shared_one(self):
        # App references retire on the same clock as every other sector's.
        assert REF_GRACE_PERIOD.days == 30
