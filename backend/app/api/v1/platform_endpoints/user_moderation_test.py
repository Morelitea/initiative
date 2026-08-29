"""What a moderator may do to an account, and everything they may not.

Three actions: take a picture down, change a username, freeze the account. Each
is gated on a platform capability, each records itself, each tells the person.
Nothing else about an account is a moderator's to change, and none of it needs
a PAM grant — these are platform actions about an account, not access to a
guild's content.
"""

import pytest
from httpx import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.main import app
from app.models.platform.guild import GuildRole
from app.models.platform.notification import Notification, NotificationType
from app.models.platform.user import User, UserRole, UserStatus
from app.testing import create_guild, create_guild_membership, create_user
from app.testing.factories import get_auth_headers

pytestmark = pytest.mark.integration


async def _notification_types(session: AsyncSession, user_id: int) -> set[str]:
    rows = (
        await session.exec(select(Notification).where(Notification.user_id == user_id))
    ).all()
    return {row.type for row in rows}


async def _audit_entries(
    client: AsyncClient, reader: User, subject_id: int
) -> list[dict]:
    response = await client.get(
        "/api/v1/admin/audit-events",
        headers=get_auth_headers(reader),
        params={"target_user_id": subject_id},
    )
    assert response.status_code == 200, response.text
    return response.json()["items"]


class TestRenaming:
    async def test_a_moderator_sets_the_name_part(
        self, client: AsyncClient, session: AsyncSession
    ):
        moderator = await create_user(session, role=UserRole.moderator)
        subject = await create_user(session, username="unsuitable", discriminator=42)

        response = await client.patch(
            f"/api/v1/admin/users/{subject.id}/username",
            headers=get_auth_headers(moderator),
            json={"username": "renamed"},
        )

        assert response.status_code == 200, response.text
        assert response.json()["username"] == "renamed"
        # The number is drawn, not chosen — not by its owner, and not by a
        # moderator either. It survives the rename.
        assert response.json()["discriminator"] == 42

    async def test_the_new_name_is_validated_like_any_other(
        self, client: AsyncClient, session: AsyncSession
    ):
        moderator = await create_user(session, role=UserRole.moderator)
        subject = await create_user(session)

        response = await client.patch(
            f"/api/v1/admin/users/{subject.id}/username",
            headers=get_auth_headers(moderator),
            json={"username": "owner"},
        )

        assert response.status_code == 422
        assert response.json()["detail"] == "USERNAME_RESERVED"

    async def test_the_subject_cannot_spend_a_pick_undoing_it(
        self, client: AsyncClient, session: AsyncSession
    ):
        moderator = await create_user(session, role=UserRole.moderator)
        subject = await create_user(session, username_chosen=False)

        await client.patch(
            f"/api/v1/admin/users/{subject.id}/username",
            headers=get_auth_headers(moderator),
            json={"username": "assigned-name"},
        )

        claim = await client.patch(
            "/api/v1/users/me/username",
            headers=get_auth_headers(subject),
            json={"username": "back-to-mine"},
        )
        assert claim.status_code == 409

    async def test_the_person_is_told_and_the_change_is_recorded(
        self, client: AsyncClient, session: AsyncSession
    ):
        moderator = await create_user(session, role=UserRole.moderator)
        subject = await create_user(session, username="before", discriminator=7)

        await client.patch(
            f"/api/v1/admin/users/{subject.id}/username",
            headers=get_auth_headers(moderator),
            json={"username": "after"},
        )

        assert NotificationType.username_changed.value in await _notification_types(
            session, subject.id
        )
        entry = (await _audit_entries(client, moderator, subject.id))[0]
        assert entry["event_type"] == "user.username_changed"
        # The handle they lost is what they will look for; the one they have is
        # already on screen.
        assert entry["detail"]["from"] == "before#0007"
        assert entry["detail"]["to"] == "after#0007"

    @pytest.mark.parametrize("role", [UserRole.member, UserRole.support])
    async def test_below_moderator_is_refused(
        self, client: AsyncClient, session: AsyncSession, role
    ):
        actor = await create_user(session, role=role)
        subject = await create_user(session)

        response = await client.patch(
            f"/api/v1/admin/users/{subject.id}/username",
            headers=get_auth_headers(actor),
            json={"username": "nope"},
        )
        assert response.status_code == 403


class TestSuspension:
    @pytest.fixture
    async def moderator_and_member(self, session):
        moderator = await create_user(session, role=UserRole.moderator)
        member = await create_user(session)
        guild = await create_guild(session, creator=member)
        await create_guild_membership(
            session, user=member, guild=guild, role=GuildRole.admin
        )
        return moderator, member, guild

    async def _suspend(self, client, moderator, member, suspended=True, reason=None):
        return await client.post(
            f"/api/v1/admin/users/{member.id}/suspension",
            headers=get_auth_headers(moderator),
            json={"suspended": suspended, **({"reason": reason} if reason else {})},
        )

    async def test_it_freezes_and_thaws(self, client, session, moderator_and_member):
        moderator, member, _guild = moderator_and_member

        frozen = await self._suspend(client, moderator, member)
        assert frozen.status_code == 200, frozen.text
        assert frozen.json()["status"] == "suspended"

        thawed = await self._suspend(client, moderator, member, suspended=False)
        assert thawed.json()["status"] == "active"

    async def test_a_suspended_account_still_signs_in(
        self, client, session, moderator_and_member
    ):
        """Being able to sign in is how its holder reaches their own account,
        and the only reason telling them anything works."""
        moderator, member, _guild = moderator_and_member
        await self._suspend(client, moderator, member)

        response = await client.get(
            "/api/v1/users/me", headers=get_auth_headers(member)
        )

        assert response.status_code == 200
        assert response.json()["status"] == "suspended"

    async def test_it_reaches_no_guild(self, client, session, moderator_and_member):
        moderator, member, guild = moderator_and_member
        before = await client.get(
            f"/api/v1/g/{guild.id}/users/", headers=get_auth_headers(member)
        )
        assert before.status_code == 200

        await self._suspend(client, moderator, member)

        after = await client.get(
            f"/api/v1/g/{guild.id}/users/", headers=get_auth_headers(member)
        )
        # The same code a non-member gets: a guild is never told that one of
        # its members was suspended.
        assert after.status_code == 403
        assert after.json()["detail"] == "GUILD_ACCESS_DENIED"

    async def test_its_guild_list_is_empty(self, client, session, moderator_and_member):
        moderator, member, _guild = moderator_and_member
        await self._suspend(client, moderator, member)

        response = await client.get("/api/v1/guilds/", headers=get_auth_headers(member))

        assert response.status_code == 200
        assert response.json() == []

    async def test_nothing_is_taken_away(self, client, session, moderator_and_member):
        """Suspension writes one column. Lifting it restores the account
        whole, which is what makes it different from deactivation."""
        moderator, member, guild = moderator_and_member

        await self._suspend(client, moderator, member)
        await self._suspend(client, moderator, member, suspended=False)

        response = await client.get(
            f"/api/v1/g/{guild.id}/users/", headers=get_auth_headers(member)
        )
        assert response.status_code == 200
        assert member.id in {row["id"] for row in response.json()}

    async def test_they_vanish_from_the_roster(
        self, client, session, moderator_and_member
    ):
        moderator, member, guild = moderator_and_member
        onlooker = await create_user(session)
        await create_guild_membership(
            session, user=onlooker, guild=guild, role=GuildRole.member
        )

        await self._suspend(client, moderator, member)

        response = await client.get(
            f"/api/v1/g/{guild.id}/users/", headers=get_auth_headers(onlooker)
        )
        assert member.id not in {row["id"] for row in response.json()}

    async def test_they_vanish_from_the_picker(
        self, client, session, moderator_and_member
    ):
        moderator, member, guild = moderator_and_member
        onlooker = await create_user(session)
        await create_guild_membership(
            session, user=onlooker, guild=guild, role=GuildRole.member
        )

        await self._suspend(client, moderator, member)

        response = await client.get(
            f"/api/v1/g/{guild.id}/users/search", headers=get_auth_headers(onlooker)
        )
        assert member.id not in {row["id"] for row in response.json()["items"]}

    async def test_the_person_is_told_with_the_reason(
        self, client, session, moderator_and_member
    ):
        moderator, member, _guild = moderator_and_member

        await self._suspend(client, moderator, member, reason="Terms of use")

        assert NotificationType.account_suspended.value in await _notification_types(
            session, member.id
        )

    async def test_both_directions_are_recorded(
        self, client, session, moderator_and_member
    ):
        moderator, member, _guild = moderator_and_member

        await self._suspend(client, moderator, member, reason="Terms of use")
        await self._suspend(client, moderator, member, suspended=False)

        kinds = [
            e["event_type"] for e in await _audit_entries(client, moderator, member.id)
        ]
        assert set(kinds) == {"user.suspended", "user.unsuspended"}

    async def test_a_moderator_cannot_suspend_themselves(
        self, client, session, moderator_and_member
    ):
        moderator, _member, _guild = moderator_and_member

        response = await client.post(
            f"/api/v1/admin/users/{moderator.id}/suspension",
            headers=get_auth_headers(moderator),
            json={"suspended": True},
        )

        assert response.status_code == 400
        assert response.json()["detail"] == "ADMIN_CANNOT_SUSPEND_SELF"

    async def test_a_closed_account_is_not_frozen(self, client, session):
        """Thawing it later would quietly reopen an account its owner closed."""
        moderator = await create_user(session, role=UserRole.moderator)
        closed = await create_user(session, status=UserStatus.deactivated)

        response = await client.post(
            f"/api/v1/admin/users/{closed.id}/suspension",
            headers=get_auth_headers(moderator),
            json={"suspended": True},
        )

        assert response.status_code == 400
        assert response.json()["detail"] == "ADMIN_CANNOT_SUSPEND_INACTIVE"

    @pytest.mark.parametrize("role", [UserRole.member, UserRole.support])
    async def test_below_moderator_is_refused(self, client, session, role):
        actor = await create_user(session, role=role)
        subject = await create_user(session)

        response = await client.post(
            f"/api/v1/admin/users/{subject.id}/suspension",
            headers=get_auth_headers(actor),
            json={"suspended": True},
        )
        assert response.status_code == 403


class TestNothingElse:
    """The admin surface writes exactly five things about an account, and each
    one is gated deliberately. A sixth appearing here is a decision, not an
    accident — this is what makes it one."""

    def test_the_admin_router_writes_only_what_it_should(self):
        writes = {
            (route.path, verb)
            for route in app.routes
            if getattr(route, "path", "").startswith("/api/v1/admin/users")
            for verb in getattr(route, "methods", set())
            if verb in {"POST", "PATCH", "PUT", "DELETE"}
        }

        assert writes == {
            # Moderator (content.moderate / users.manage).
            ("/api/v1/admin/users/{user_id}/avatar", "DELETE"),
            ("/api/v1/admin/users/{user_id}/username", "PATCH"),
            ("/api/v1/admin/users/{user_id}/suspension", "POST"),
            ("/api/v1/admin/users/{user_id}/reactivate", "POST"),
            # Sends the holder a link; it never sets a password.
            ("/api/v1/admin/users/{user_id}/reset-password", "POST"),
            # Operator and above, deliberately out of a moderator's reach.
            ("/api/v1/admin/users/{user_id}/platform-role", "PATCH"),
            ("/api/v1/admin/users/{user_id}", "DELETE"),
        }
