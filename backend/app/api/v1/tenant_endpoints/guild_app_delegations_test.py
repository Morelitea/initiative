"""A member's own authorization for an installed app to act as them.

Two gates, and the point of nearly every case here is that they are separate:
the guild installs the app, and each member decides whether it may carry their
name. One does not stand in for the other, in either direction.
"""

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core import config as config_module
from app.models.platform.guild import GuildRole
from app.services.marketplace.registration_lookup import invalidate_registrations
from app.testing.delegation import (
    DELEGATE_PUBLIC_ID,
    install_delegate,
    mint_delegation_token,
    register_delegate,
)


@pytest.fixture(autouse=True)
async def _delegate_registered(session: AsyncSession):
    """An operator has granted the delegate, which is what makes the question
    worth asking a member at all."""
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(
            config_module.settings,
            "APP_PLATFORM_SIGNING_PRIVATE_KEY_PEM",
            "-----BEGIN PRIVATE KEY-----",
        )
        await register_delegate(session)
        yield
    invalidate_registrations()


async def _clear_the_grant(session: AsyncSession) -> None:
    """Take the operator's `delegation` grant back off the registration."""
    from sqlmodel import select

    from app.models.platform.app_service_registration import AppServiceRegistration

    row = (
        await session.exec(
            select(AppServiceRegistration).where(
                AppServiceRegistration.public_id == DELEGATE_PUBLIC_ID
            )
        )
    ).one()
    row.grants = []
    session.add(row)
    await session.commit()
    invalidate_registrations()


async def _installed_for(session: AsyncSession, actor):
    """The delegate, installed in the actor's guild."""
    return await install_delegate(session, actor.guild, creator=actor.user)


def _delegated(user_id: int, guild_id: int) -> dict[str, str]:
    token = mint_delegation_token(user_id=user_id, guild_id=guild_id)
    return {"Authorization": f"Bearer {token}"}


class TestTheMembersOwnAnswer:
    @pytest.mark.integration
    async def test_an_install_alone_authorizes_nobody(
        self, client: AsyncClient, session: AsyncSession, acting_user
    ):
        """Installing is the guild's decision and carrying a name is the
        member's, so a fresh install can act as nobody yet."""
        a = await acting_user(guild_role=GuildRole.member)
        await _installed_for(session, a)

        response = await client.get(
            "/api/v1/users/me", headers=_delegated(a.user.id, a.guild.id)
        )
        assert response.status_code == 401

    @pytest.mark.integration
    async def test_authorizing_lets_the_app_act(
        self, client: AsyncClient, session: AsyncSession, acting_user
    ):
        a = await acting_user(guild_role=GuildRole.member)
        app = await _installed_for(session, a)

        granted = await client.put(
            a.g(f"/apps/{app.id}/delegation"),
            headers=a.headers,
            json={"can_write": False},
        )
        assert granted.status_code == 200, granted.text
        assert granted.json()["granted"] is True
        assert granted.json()["can_write"] is False

        response = await client.get(
            "/api/v1/users/me", headers=_delegated(a.user.id, a.guild.id)
        )
        assert response.status_code == 200

    @pytest.mark.integration
    async def test_read_authorization_does_not_carry_writes(
        self, client: AsyncClient, session: AsyncSession, acting_user
    ):
        """The member is asked the two questions separately, so answering the
        first does not answer the second."""
        a = await acting_user(guild_role=GuildRole.admin, initiative=True)
        app = await _installed_for(session, a)
        await client.put(
            a.g(f"/apps/{app.id}/delegation"),
            headers=a.headers,
            json={"can_write": False},
        )

        reading = await client.get(
            a.g("/initiatives/"), headers=_delegated(a.user.id, a.guild.id)
        )
        assert reading.status_code == 200

        writing = await client.post(
            a.g("/initiatives/"),
            headers=_delegated(a.user.id, a.guild.id),
            json={"name": "Written by the app"},
        )
        assert writing.status_code == 401

    @pytest.mark.integration
    async def test_write_authorization_carries_writes(
        self, client: AsyncClient, session: AsyncSession, acting_user
    ):
        a = await acting_user(guild_role=GuildRole.admin, initiative=True)
        app = await _installed_for(session, a)
        await client.put(
            a.g(f"/apps/{app.id}/delegation"),
            headers=a.headers,
            json={"can_write": True},
        )

        writing = await client.post(
            a.g("/initiatives/"),
            headers=_delegated(a.user.id, a.guild.id),
            json={"name": "Written by the app"},
        )
        assert writing.status_code == 201, writing.text

    @pytest.mark.integration
    async def test_withdrawing_stops_the_app_at_once(
        self, client: AsyncClient, session: AsyncSession, acting_user
    ):
        a = await acting_user(guild_role=GuildRole.member)
        app = await _installed_for(session, a)
        await client.put(
            a.g(f"/apps/{app.id}/delegation"),
            headers=a.headers,
            json={"can_write": True},
        )

        revoked = await client.delete(
            a.g(f"/apps/{app.id}/delegation"), headers=a.headers
        )
        assert revoked.status_code == 204

        response = await client.get(
            "/api/v1/users/me", headers=_delegated(a.user.id, a.guild.id)
        )
        assert response.status_code == 401

    @pytest.mark.integration
    async def test_a_withdrawal_is_a_record_not_a_blank(
        self, client: AsyncClient, session: AsyncSession, acting_user
    ):
        """A member who stopped and one who was never asked are different
        answers, so the page can say which happened."""
        a = await acting_user(guild_role=GuildRole.member)
        app = await _installed_for(session, a)
        await client.put(
            a.g(f"/apps/{app.id}/delegation"),
            headers=a.headers,
            json={"can_write": True},
        )
        await client.delete(a.g(f"/apps/{app.id}/delegation"), headers=a.headers)

        after = await client.get(a.g(f"/apps/{app.id}/delegation"), headers=a.headers)
        assert after.status_code == 200
        body = after.json()
        assert body["granted"] is False
        assert body["revoked_at"] is not None

    @pytest.mark.integration
    async def test_one_member_authorizing_does_not_authorize_another(
        self, client: AsyncClient, session: AsyncSession, acting_user
    ):
        a = await acting_user(guild_role=GuildRole.member)
        b = await acting_user(guild_role=GuildRole.member, guild=a.guild)
        app = await _installed_for(session, a)
        await client.put(
            a.g(f"/apps/{app.id}/delegation"),
            headers=a.headers,
            json={"can_write": True},
        )

        response = await client.get(
            "/api/v1/users/me", headers=_delegated(b.user.id, a.guild.id)
        )
        assert response.status_code == 401

    @pytest.mark.integration
    async def test_an_app_that_never_acts_as_anyone_is_not_offered(
        self, client: AsyncClient, session: AsyncSession, acting_user
    ):
        """The question comes from the operator's grant, not the install, so an
        app without it has nothing to ask."""
        a = await acting_user(guild_role=GuildRole.member)
        app = await _installed_for(session, a)
        await _clear_the_grant(session)

        response = await client.put(
            a.g(f"/apps/{app.id}/delegation"),
            headers=a.headers,
            json={"can_write": True},
        )
        assert response.status_code == 404
        assert response.json()["detail"] == "GUILD_APP_DELEGATION_NOT_OFFERED"

    @pytest.mark.integration
    async def test_the_detail_payload_carries_the_viewers_own_answer(
        self, client: AsyncClient, session: AsyncSession, acting_user
    ):
        """The settings page draws the question from the install it already
        fetched rather than a second request."""
        a = await acting_user(guild_role=GuildRole.member)
        app = await _installed_for(session, a)

        before = await client.get(a.g(f"/apps/{app.id}"), headers=a.headers)
        assert before.json()["delegates"] is True
        assert before.json()["delegation"]["granted"] is False

        await client.put(
            a.g(f"/apps/{app.id}/delegation"),
            headers=a.headers,
            json={"can_write": True},
        )

        after = await client.get(a.g(f"/apps/{app.id}"), headers=a.headers)
        assert after.json()["delegation"]["granted"] is True
        assert after.json()["delegation"]["can_write"] is True


class TestWhoMayGrantIt:
    @pytest.mark.integration
    async def test_the_app_cannot_authorize_itself(
        self, client: AsyncClient, session: AsyncSession, acting_user
    ):
        """Authorizing is the member's own act, made while they are signed in,
        so the app is not among the parties that can make it."""
        a = await acting_user(guild_role=GuildRole.member)
        app = await _installed_for(session, a)
        await client.put(
            a.g(f"/apps/{app.id}/delegation"),
            headers=a.headers,
            json={"can_write": False},
        )

        response = await client.put(
            a.g(f"/apps/{app.id}/delegation"),
            headers=_delegated(a.user.id, a.guild.id),
            json={"can_write": True},
        )
        # The write it is trying to make is not one its read-only grant covers,
        # so it never authenticates as delegated at all.
        assert response.status_code == 401

        still = await client.get(a.g(f"/apps/{app.id}/delegation"), headers=a.headers)
        assert still.json()["can_write"] is False

    @pytest.mark.integration
    async def test_the_native_app_can_grant_it(
        self, client: AsyncClient, session: AsyncSession, acting_user
    ):
        """A device token is how somebody signs in on their phone, so it grants
        exactly as a web session does. The line is between a person being here
        and something acting for them, not between two clients."""
        from app.services.platform import user_tokens

        a = await acting_user(guild_role=GuildRole.member)
        app = await _installed_for(session, a)
        device_token = await user_tokens.create_device_token(
            session, user_id=a.user.id, device_name="Phone"
        )
        await session.commit()

        response = await client.put(
            a.g(f"/apps/{app.id}/delegation"),
            headers={"Authorization": f"DeviceToken {device_token}"},
            json={"can_write": True},
        )
        assert response.status_code == 200, response.text
        assert response.json()["granted"] is True
        assert response.json()["confirmed_factor"] == "device_token"

    @pytest.mark.integration
    async def test_an_api_key_cannot_grant_it(
        self, client: AsyncClient, session: AsyncSession, acting_user
    ):
        """Handing out authority is done while the person is here, not through
        a credential running without them."""
        from app.services.platform import api_keys as api_keys_service

        a = await acting_user(guild_role=GuildRole.member)
        app = await _installed_for(session, a)
        secret, _row = await api_keys_service.create_api_key(
            session, user=a.user, name="script"
        )
        await session.commit()

        response = await client.put(
            a.g(f"/apps/{app.id}/delegation"),
            headers={"Authorization": f"Bearer {secret}"},
            json={"can_write": True},
        )
        assert response.status_code == 403
        assert response.json()["detail"] == "SESSION_REQUIRED"

    @pytest.mark.integration
    async def test_a_guild_admin_cannot_grant_it_for_somebody_else(
        self, client: AsyncClient, session: AsyncSession, acting_user
    ):
        """There is no endpoint that takes a user id: an admin governs the
        install, and whose name the app may carry is not theirs to answer."""
        a = await acting_user(guild_role=GuildRole.admin)
        b = await acting_user(guild_role=GuildRole.member, guild=a.guild)
        app = await _installed_for(session, a)

        response = await client.put(
            a.g(f"/apps/{app.id}/delegation"),
            headers=a.headers,
            json={"can_write": True},
        )
        assert response.status_code == 200

        # The admin authorized themselves and nobody else.
        acting_as_b = await client.get(
            "/api/v1/users/me", headers=_delegated(b.user.id, a.guild.id)
        )
        assert acting_as_b.status_code == 401


class TestWhatAnAdminGoverns:
    @pytest.mark.integration
    async def test_an_admin_sees_who_authorized_the_app(
        self, client: AsyncClient, session: AsyncSession, acting_user
    ):
        a = await acting_user(guild_role=GuildRole.admin)
        b = await acting_user(guild_role=GuildRole.member, guild=a.guild)
        app = await _installed_for(session, a)
        await client.put(
            a.g(f"/apps/{app.id}/delegation"),
            headers=b.headers,
            json={"can_write": True},
        )

        members = await client.get(a.g(f"/apps/{app.id}/members"), headers=a.headers)
        assert members.status_code == 200
        rows = members.json()["delegations"]
        assert [row["user_id"] for row in rows] == [b.user.id]
        assert rows[0]["can_write"] is True

    @pytest.mark.integration
    async def test_a_member_does_not_get_the_members_view(
        self, client: AsyncClient, session: AsyncSession, acting_user
    ):
        a = await acting_user(guild_role=GuildRole.member)
        app = await _installed_for(session, a)

        response = await client.get(a.g(f"/apps/{app.id}/members"), headers=a.headers)
        assert response.status_code == 403

    @pytest.mark.integration
    async def test_an_admin_can_end_one_members_authorization(
        self, client: AsyncClient, session: AsyncSession, acting_user
    ):
        a = await acting_user(guild_role=GuildRole.admin)
        b = await acting_user(guild_role=GuildRole.member, guild=a.guild)
        app = await _installed_for(session, a)
        await client.put(
            a.g(f"/apps/{app.id}/delegation"),
            headers=b.headers,
            json={"can_write": True},
        )

        revoked = await client.delete(
            a.g(f"/apps/{app.id}/members/{b.user.id}/delegation"), headers=a.headers
        )
        assert revoked.status_code == 204

        response = await client.get(
            "/api/v1/users/me", headers=_delegated(b.user.id, a.guild.id)
        )
        assert response.status_code == 401

    @pytest.mark.integration
    async def test_an_admin_can_end_everyones_at_once(
        self, client: AsyncClient, session: AsyncSession, acting_user
    ):
        """For a suspected app compromise: reacting fast should not cost the
        guild its install."""
        a = await acting_user(guild_role=GuildRole.admin)
        b = await acting_user(guild_role=GuildRole.member, guild=a.guild)
        app = await _installed_for(session, a)
        for actor in (a, b):
            await client.put(
                a.g(f"/apps/{app.id}/delegation"),
                headers=actor.headers,
                json={"can_write": True},
            )

        stopped = await client.post(
            a.g(f"/apps/{app.id}/delegations/revoke-all"), headers=a.headers
        )
        assert stopped.status_code == 204

        for actor in (a, b):
            response = await client.get(
                "/api/v1/users/me", headers=_delegated(actor.user.id, a.guild.id)
            )
            assert response.status_code == 401

    @pytest.mark.integration
    async def test_a_member_cannot_end_everyones(
        self, client: AsyncClient, session: AsyncSession, acting_user
    ):
        a = await acting_user(guild_role=GuildRole.member)
        app = await _installed_for(session, a)

        response = await client.post(
            a.g(f"/apps/{app.id}/delegations/revoke-all"), headers=a.headers
        )
        assert response.status_code == 403


class TestWhenTheRelationshipEnds:
    @pytest.mark.integration
    async def test_leaving_the_guild_takes_the_authorization(
        self, client: AsyncClient, session: AsyncSession, acting_user
    ):
        """A member who leaves has not left an app able to act as them."""
        owner = await acting_user(guild_role=GuildRole.admin)
        leaver = await acting_user(guild_role=GuildRole.member, guild=owner.guild)
        app = await _installed_for(session, owner)
        await client.put(
            owner.g(f"/apps/{app.id}/delegation"),
            headers=leaver.headers,
            json={"can_write": True},
        )

        left = await client.delete(
            f"/api/v1/guilds/{owner.guild.id}/leave", headers=leaver.headers
        )
        assert left.status_code == 204, left.text

        response = await client.get(
            "/api/v1/users/me", headers=_delegated(leaver.user.id, owner.guild.id)
        )
        assert response.status_code == 401

    @pytest.mark.integration
    async def test_uninstalling_takes_every_authorization(
        self, client: AsyncClient, session: AsyncSession, acting_user
    ):
        a = await acting_user(guild_role=GuildRole.admin)
        app = await _installed_for(session, a)
        await client.put(
            a.g(f"/apps/{app.id}/delegation"),
            headers=a.headers,
            json={"can_write": True},
        )

        removed = await client.delete(a.g(f"/apps/{app.id}"), headers=a.headers)
        assert removed.status_code == 204, removed.text

        response = await client.get(
            "/api/v1/users/me", headers=_delegated(a.user.id, a.guild.id)
        )
        assert response.status_code == 401


@pytest.mark.unit
def test_the_delegate_is_the_app_these_cases_talk_about():
    """Guards the shared helper's identity against a rename that would make
    every case above pass for the wrong reason."""
    assert DELEGATE_PUBLIC_ID == "acme.auto"
