"""Handing out the number behind a name."""

import pytest
from sqlalchemy import func, select

from app.core import usernames
from app.core.usernames import UsernameError
from app.models.platform.user import User
from app.services.platform import usernames as username_service
from app.testing import create_user

pytestmark = [pytest.mark.integration, pytest.mark.database]


class TestAllocate:
    async def test_returns_the_name_as_asked_for(self, session):
        name, number = await username_service.allocate(session, name="Foobar")
        assert name == "foobar"
        assert 0 <= number <= 9999

    async def test_the_same_name_is_handed_out_again(self, session):
        """Ten thousand numbers sit behind every name, so registration never
        has to negotiate — fifty people called Jordan are fifty handles."""
        taken = set()
        for _ in range(20):
            name, number = await username_service.allocate(session, name="jordan")
            await create_user(session, username=name, discriminator=number)
            assert (name, number) not in taken
            taken.add((name, number))

    async def test_refuses_a_name_it_cannot_store(self, session):
        with pytest.raises(UsernameError) as exc:
            await username_service.allocate(session, name="admin")
        assert exc.value.code == "USERNAME_RESERVED"


class TestAllocateFromSeed:
    async def test_uses_the_seed(self, session):
        name, _ = await username_service.allocate_from_seed(
            session, seed="Jordan Drako"
        )
        assert name == "jordan-drako"

    @pytest.mark.parametrize("seed", [None, "", "jordan@example.com", "admin"])
    async def test_falls_back_to_a_generated_name(self, session, seed):
        """An address, a reserved word and an empty seed all have to end in
        something storable — this is the path every SSO account takes."""
        name, number = await username_service.allocate_from_seed(session, seed=seed)
        usernames.validate(name)
        assert 0 <= number <= 9999


class TestFreeSlots:
    async def test_a_fresh_name_is_free(self, session):
        assert await username_service.has_free_slot(session, name="brandnewname")

    @pytest.mark.parametrize("name", ["admin", "ab", "foo bar"])
    async def test_a_name_it_cannot_store_is_not_free(self, session, name):
        assert not await username_service.has_free_slot(session, name=name)


class TestClaim:
    async def test_sets_the_handle_and_marks_it_chosen(self, session):
        user = await create_user(session, username_chosen=False)

        await username_service.claim_for_user(session, user=user, name="Picked")
        await session.commit()

        assert user.username == "picked"
        assert user.username_chosen is True

    async def test_the_pair_is_unique(self, session):
        """Two accounts may hold the same name; the number is what separates
        them, and the index is what enforces it."""
        first = await create_user(session, username_chosen=False)
        second = await create_user(session, username_chosen=False)

        await username_service.claim_for_user(session, user=first, name="shared")
        await session.commit()
        await username_service.claim_for_user(session, user=second, name="shared")
        await session.commit()

        assert first.username == second.username == "shared"
        assert first.discriminator != second.discriminator

        held = (
            await session.exec(
                select(func.count())
                .select_from(User)
                .where(func.lower(User.username) == "shared")
            )
        ).scalar_one()
        assert held == 2
