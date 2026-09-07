"""Handles, end to end: picking one, being given one, and finding someone by it.

Also the two rules that decide what a guild-scoped payload says about a person:
an address never appears in one, and a real name appears only where the guild
has asked for it.
"""

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.guild import GuildRole
from app.testing import create_guild, create_guild_membership, create_user
from app.testing.factories import get_auth_headers

pytestmark = pytest.mark.integration


REGISTRATION = {
    "email": "handle-new@example.com",
    "password": "a-long-enough-password-123",
    "username": "newcomer",
    "full_name": "New Comer",
}


class TestRegistration:
    async def test_a_new_account_gets_the_name_it_typed(self, client: AsyncClient):
        response = await client.post("/api/v1/auth/register", json=REGISTRATION)

        assert response.status_code == 201, response.text
        body = response.json()
        assert body["username"] == "newcomer"
        assert 0 <= body["discriminator"] <= 9999
        # Typed into a form, so it is chosen — this account never meets the
        # pick screen.
        assert body["username_chosen"] is True

    async def test_the_same_name_twice(self, client: AsyncClient):
        first = await client.post("/api/v1/auth/register", json=REGISTRATION)
        second = await client.post(
            "/api/v1/auth/register",
            json={**REGISTRATION, "email": "handle-other@example.com"},
        )

        assert first.status_code == 201
        assert second.status_code == 201, second.text
        assert first.json()["username"] == second.json()["username"] == "newcomer"
        assert first.json()["discriminator"] != second.json()["discriminator"]

    @pytest.mark.parametrize(
        ("username", "code"),
        [
            ("ab", "USERNAME_TOO_SHORT"),
            ("admin", "USERNAME_RESERVED"),
            ("has spaces", "USERNAME_INVALID_CHARACTERS"),
        ],
    )
    async def test_refuses_a_name_it_cannot_store(
        self, client: AsyncClient, username, code
    ):
        response = await client.post(
            "/api/v1/auth/register", json={**REGISTRATION, "username": username}
        )

        assert response.status_code == 422
        assert response.json()["detail"] == code

    async def test_a_name_is_required(self, client: AsyncClient):
        payload = {k: v for k, v in REGISTRATION.items() if k != "username"}
        response = await client.post("/api/v1/auth/register", json=payload)

        assert response.status_code == 422


class TestAvailability:
    async def test_a_fresh_name_is_available(self, client: AsyncClient):
        response = await client.get(
            "/api/v1/auth/username-available", params={"username": "unclaimedname"}
        )

        assert response.status_code == 200
        assert response.json() == {"available": True, "reason": None}

    async def test_a_reserved_name_says_why(self, client: AsyncClient):
        response = await client.get(
            "/api/v1/auth/username-available", params={"username": "admin"}
        )

        assert response.json() == {"available": False, "reason": "USERNAME_RESERVED"}

    async def test_a_name_someone_holds_is_still_available(
        self, client: AsyncClient, session: AsyncSession
    ):
        """The number is what resolves contention, so a name in use is not a
        name that is taken."""
        await create_user(session, username="popular", discriminator=1)

        response = await client.get(
            "/api/v1/auth/username-available", params={"username": "popular"}
        )

        assert response.json()["available"] is True


class TestClaimingAHandle:
    async def test_an_assigned_handle_can_be_picked_once(
        self, client: AsyncClient, session: AsyncSession
    ):
        user = await create_user(session, username_chosen=False)

        response = await client.patch(
            "/api/v1/users/me/username",
            headers=get_auth_headers(user),
            json={"username": "mine-now"},
        )

        assert response.status_code == 200, response.text
        assert response.json()["username"] == "mine-now"
        assert response.json()["username_chosen"] is True

    async def test_a_chosen_handle_is_not_changed_again(
        self, client: AsyncClient, session: AsyncSession
    ):
        user = await create_user(session, username_chosen=True)

        response = await client.patch(
            "/api/v1/users/me/username",
            headers=get_auth_headers(user),
            json={"username": "second-thoughts"},
        )

        assert response.status_code == 409
        assert response.json()["detail"] == "USERNAME_ALREADY_CHOSEN"

    async def test_the_picked_name_is_validated(
        self, client: AsyncClient, session: AsyncSession
    ):
        user = await create_user(session, username_chosen=False)

        response = await client.patch(
            "/api/v1/users/me/username",
            headers=get_auth_headers(user),
            json={"username": "owner"},
        )

        assert response.status_code == 422
        assert response.json()["detail"] == "USERNAME_RESERVED"


class TestWhatAGuildPayloadSays:
    @pytest.fixture
    async def guild_with_member(self, session):
        admin = await create_user(session, full_name="Ada Admin")
        guild = await create_guild(session, creator=admin)
        await create_guild_membership(
            session, user=admin, guild=guild, role=GuildRole.admin
        )
        member = await create_user(
            session, full_name="Mem Ber", username="member", discriminator=77
        )
        await create_guild_membership(
            session, user=member, guild=guild, role=GuildRole.member
        )
        return admin, member, guild

    async def test_no_address_reaches_the_guild(self, client, guild_with_member):
        """An account is a person's, not a tenant's — not even on the guild's
        own member-management surface."""
        admin, _member, guild = guild_with_member

        response = await client.get(
            f"/api/v1/g/{guild.id}/users/", headers=get_auth_headers(admin)
        )

        assert response.status_code == 200
        for row in response.json():
            assert "email" not in row

    async def test_handles_are_always_there(self, client, guild_with_member):
        admin, member, guild = guild_with_member

        response = await client.get(
            f"/api/v1/g/{guild.id}/users/", headers=get_auth_headers(admin)
        )

        row = next(r for r in response.json() if r["id"] == member.id)
        assert row["username"] == "member"
        assert row["discriminator"] == 77

    async def test_a_guild_shows_names_by_default(self, client, guild_with_member):
        admin, member, guild = guild_with_member

        response = await client.get(
            f"/api/v1/g/{guild.id}/users/", headers=get_auth_headers(admin)
        )

        row = next(r for r in response.json() if r["id"] == member.id)
        assert row["full_name"] == "Mem Ber"

    async def test_a_guild_that_turned_them_off_sends_none(
        self, client, session, guild_with_member
    ):
        admin, member, guild = guild_with_member
        guild.show_member_names = False
        session.add(guild)
        await session.commit()

        response = await client.get(
            f"/api/v1/g/{guild.id}/users/", headers=get_auth_headers(admin)
        )

        row = next(r for r in response.json() if r["id"] == member.id)
        assert row["full_name"] is None

    async def test_a_listed_guild_shows_none_without_being_asked(
        self, client, session, guild_with_member
    ):
        """Listing a guild turns its names off in the same write, so the
        payload follows without an admin having to do it in two steps."""
        admin, member, guild = guild_with_member
        guild.is_community = True
        guild.categories = ["other"]
        guild.has_adult_content = False
        session.add(guild)
        await session.commit()

        response = await client.get(
            f"/api/v1/g/{guild.id}/users/", headers=get_auth_headers(admin)
        )

        row = next(r for r in response.json() if r["id"] == member.id)
        assert row["full_name"] is None


class TestFindingSomeone:
    @pytest.fixture
    async def searchable_guild(self, session):
        # The searcher is a member too, so their own handle and name are in the
        # corpus. Pinned rather than generated: matching is fuzzy, and a random
        # name that happens to share three letters with a search term ("Three"
        # against "ivory-thrush") would fail an assertion about somebody else.
        admin = await create_user(
            session, username="zeph", discriminator=9001, full_name="Zeph Quill"
        )
        guild = await create_guild(session, creator=admin)
        await create_guild_membership(
            session, user=admin, guild=guild, role=GuildRole.admin
        )
        for username, discriminator, full_name in [
            ("jordan", 1234, "Jordan One"),
            ("jordan", 5678, "Jordan Two"),
            ("morgan", 12, "Morgan Three"),
        ]:
            member = await create_user(
                session,
                username=username,
                discriminator=discriminator,
                full_name=full_name,
            )
            await create_guild_membership(
                session, user=member, guild=guild, role=GuildRole.member
            )
        return admin, guild

    async def _search(self, client, admin, guild, term):
        response = await client.get(
            f"/api/v1/g/{guild.id}/users/search",
            headers=get_auth_headers(admin),
            params={"search": term},
        )
        assert response.status_code == 200, response.text
        return response.json()["items"]

    async def test_a_name_part_matches_a_family_of_handles(
        self, client, searchable_guild
    ):
        admin, guild = searchable_guild

        items = await self._search(client, admin, guild, "jordan")

        assert {item["discriminator"] for item in items} == {1234, 5678}

    async def test_the_whole_handle_pins_one(self, client, searchable_guild):
        admin, guild = searchable_guild

        items = await self._search(client, admin, guild, "jordan#5678")

        assert [item["discriminator"] for item in items] == [5678]

    async def test_a_partial_number_is_a_prefix_of_the_four_digits(
        self, client, searchable_guild
    ):
        """The number renders zero-padded, so a prefix is a prefix of what is
        on screen: ``#00`` finds ``0012``."""
        admin, guild = searchable_guild

        items = await self._search(client, admin, guild, "morgan#00")

        assert [item["discriminator"] for item in items] == [12]

    async def test_a_name_is_searchable_where_it_is_showable(
        self, client, searchable_guild
    ):
        admin, guild = searchable_guild

        items = await self._search(client, admin, guild, "Three")

        assert [item["username"] for item in items] == ["morgan"]

    async def test_and_not_where_it_is_not(self, client, session, searchable_guild):
        """A guild that does not show names does not match on them either.

        Asserted as "the person whose name that is does not come back" rather
        than "nothing comes back": handles are still matched, and loosely, so
        someone whose handle merely resembles the word is a legitimate hit.
        """
        admin, guild = searchable_guild
        guild.show_member_names = False
        session.add(guild)
        await session.commit()

        items = await self._search(client, admin, guild, "Three")

        assert "morgan" not in [item["username"] for item in items]
