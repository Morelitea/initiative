"""What an app service may read and report about its own installs.

Three things carry the weight here.

**An app sees its own installs and nothing else.** The catalog records what was
published, never who installed it, so "which guilds have me?" is answered by
visiting guild schemas — and the filter that decides has to be exact. A
registration reading a guild where a *different* app is installed gets the same
answer as one reading a guild that never installed anything, because it is
entitled to distinguish neither.

**Plaintext leaves on exactly one route.** The config channel is the custody
channel and returns decrypted values to the app that uses them; the connections
route reports which handles are live and carries no value at all. Both are
asserted against the whole response body rather than the one field somebody
remembered to hide.

**The app is the only party that can say whether credentials work.** Nothing in
this build moves ``config_state`` off ``unverified``; the status route is what
does, and an admin sees the answer without leaving Initiative.
"""

from datetime import datetime, timezone

import pytest
from httpx import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.encryption import SALT_APP_CONFIG, encrypt_field
from app.core.messages import AppChannelMessages, GuildAppMessages
from app.models.tenant.guild_app import GuildApp
from app.models.tenant.guild_app_user_connection import GuildAppUserConnection
from app.testing import (
    channel_headers,
    create_guild,
    create_guild_app,
    create_guild_membership,
    create_user,
    encode_body,
    register_app_service,
    route_session_to_guild,
)
from app.testing.delegation import (
    DELEGATE_PUBLIC_ID,
    authorize_delegate,
    delegate_subject,
    register_delegate,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]

BASE = "/api/v1/app-service"
SHOP_UID = "TESTAPP0000001"
OTHER_UID = "TESTAPP0000002"

GUILD_TOKEN = "shpat_the_guilds_own_token"
MEMBER_TOKEN = "gho_one_members_own_token"


def _field(key: str, field_type: str, **extra) -> dict:
    return {"key": key, "type": field_type, "label": {"en": key}, **extra}


ADMIN_CONNECTION = {
    "id": "admin",
    "scope": "static",
    "label": {"en": "Admin API"},
    "fields": [
        _field("shop_domain", "string", required=True),
        _field("admin_token", "secret", required=True),
    ],
}

MEMBER_CONNECTION = {
    "id": "github",
    "scope": "interactive",
    "label": {"en": "GitHub"},
    "connect_path": "/connect/github",
    "fields": [_field("access_token", "secret", managed=True)],
}


def _definition(public_id: str = "tests.shop") -> dict:
    return {
        "app_kind": "service",
        "service": {"public_id": public_id, "protocol": 1},
        "features": ["events"],
        "connections": [ADMIN_CONNECTION, MEMBER_CONNECTION],
        "events": [f"app.{public_id}.order_created"],
    }


async def _install(
    session: AsyncSession,
    *,
    definition: dict | None = None,
    listing_uid: str = SHOP_UID,
    with_values: bool = False,
    **overrides,
):
    """A guild with a service app installed, optionally already configured."""
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    if with_values:
        overrides.setdefault("config", {"admin": {"shop_domain": "example.test"}})
        overrides.setdefault(
            "config_secrets",
            {"admin": {"admin_token": encrypt_field(GUILD_TOKEN, SALT_APP_CONFIG)}},
        )
    app = await create_guild_app(
        session,
        guild,
        user,
        definition=definition or _definition(),
        listing_uid=listing_uid,
        **overrides,
    )
    return guild, user, app


async def _member_connection(
    session: AsyncSession,
    *,
    guild,
    app,
    user,
    connection_id: str = "github",
    connection_ref: str = "cr_member_one",
    with_secret: bool = True,
    blocked: bool = False,
) -> GuildAppUserConnection:
    await route_session_to_guild(session, guild.id)
    row = GuildAppUserConnection(
        guild_id=guild.id,
        app_id=app.id,
        connection_id=connection_id,
        user_id=user.id,
        connection_ref=connection_ref,
        config={},
        config_secrets=(
            {"access_token": encrypt_field(MEMBER_TOKEN, SALT_APP_CONFIG)}
            if with_secret
            else {}
        ),
        status="connected" if with_secret else "pending",
    )
    if blocked:
        row.blocked_at = datetime.now(timezone.utc)
        row.status = "blocked"
        row.config_secrets = {}
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


async def _get(client: AsyncClient, path: str, *, query: str = "", **kwargs):
    """A signed GET. The signature covers the path the server reads
    (``request.url.path``), so the query string is appended after signing
    rather than folded into it."""
    return await client.get(
        f"{path}{query}", headers=channel_headers(method="GET", path=path, **kwargs)
    )


async def _post(client: AsyncClient, path: str, payload, **kwargs):
    body = encode_body(payload)
    return await client.post(
        path,
        headers=channel_headers(method="POST", path=path, body=body, **kwargs),
        content=body,
    )


async def _put(client: AsyncClient, path: str, payload, **kwargs):
    body = encode_body(payload)
    return await client.put(
        path,
        headers=channel_headers(method="PUT", path=path, body=body, **kwargs),
        content=body,
    )


async def _disable_delegate(session: AsyncSession) -> None:
    """The operator's kill switch on the delegating app, as an edit to its
    registration — which is the only place that decision lives."""
    from app.models.platform.app_service_registration import AppServiceRegistration
    from app.services.marketplace.registration_lookup import invalidate_registrations

    row = (
        await session.exec(
            select(AppServiceRegistration).where(
                AppServiceRegistration.public_id == DELEGATE_PUBLIC_ID
            )
        )
    ).one()
    row.enabled = False
    session.add(row)
    await session.commit()
    invalidate_registrations()


async def _reload(session: AsyncSession, guild_id: int, app_id: int) -> GuildApp:
    await route_session_to_guild(session, guild_id)
    session.expunge_all()
    return (await session.exec(select(GuildApp).where(GuildApp.id == app_id))).one()


# ---------------------------------------------------------------------------
# Which installs an app can see
# ---------------------------------------------------------------------------


class TestInstalls:
    async def test_installs_reports_the_guilds_that_have_this_app(
        self, client: AsyncClient, session: AsyncSession
    ):
        await register_app_service(session, listing_uid=SHOP_UID)
        guild, _, app = await _install(session)

        response = await _get(client, f"{BASE}/installs")

        assert response.status_code == 200, response.text
        items = response.json()["items"]
        assert len(items) == 1
        assert items[0]["guild_id"] == guild.id
        assert items[0]["install_id"] == app.id
        assert items[0]["listing_version"] == "1.0.0"
        assert items[0]["enabled"] is True
        # Nothing about who is in the guild travels with an install summary.
        assert "members" not in items[0]
        assert "created_by" not in items[0]

    async def test_another_apps_install_is_not_listed(
        self, client: AsyncClient, session: AsyncSession
    ):
        await register_app_service(session, listing_uid=SHOP_UID)
        mine, _, _ = await _install(session)
        await _install(
            session,
            definition=_definition("tests.other"),
            listing_uid=OTHER_UID,
        )

        response = await _get(client, f"{BASE}/installs")

        assert response.status_code == 200, response.text
        assert [item["guild_id"] for item in response.json()["items"]] == [mine.id]

    async def test_an_install_pinning_another_apps_definition_is_not_ours(
        self, client: AsyncClient, session: AsyncSession
    ):
        """Both statements have to agree. A row carrying this registration's
        catalog uid but pinning a definition that names a different service is
        not an install this caller may reach."""
        await register_app_service(session, listing_uid=SHOP_UID)
        await _install(session, definition=_definition("tests.someone-else"))

        response = await _get(client, f"{BASE}/installs")

        assert response.status_code == 200, response.text
        assert response.json()["items"] == []

    async def test_a_registration_that_never_verified_has_no_installs(
        self, client: AsyncClient, session: AsyncSession
    ):
        """A handshake is what records which listing a registration speaks for.
        Without one there is nothing to match an install against."""
        await register_app_service(session, listing_uid=None)
        await _install(session)

        response = await _get(client, f"{BASE}/installs")

        assert response.status_code == 200, response.text
        assert response.json()["items"] == []


# ---------------------------------------------------------------------------
# The custody channel
# ---------------------------------------------------------------------------


class TestConfigChannel:
    async def test_config_returns_the_decrypted_values(
        self, client: AsyncClient, session: AsyncSession
    ):
        await register_app_service(session, listing_uid=SHOP_UID)
        guild, user, app = await _install(session, with_values=True)
        await _member_connection(session, guild=guild, app=app, user=user)

        response = await _get(client, f"{BASE}/installs/{guild.id}/config")

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["connections"]["admin"] == {
            "shop_domain": "example.test",
            "admin_token": GUILD_TOKEN,
        }
        member = body["member_connections"][0]
        assert member["connection_ref"] == "cr_member_one"
        assert member["values"] == {"access_token": MEMBER_TOKEN}
        # The app is told which member by handle, and by nothing else.
        assert "user_id" not in member
        assert user.email not in response.text

    async def test_a_blocked_members_values_are_not_served(
        self, client: AsyncClient, session: AsyncSession
    ):
        """A block ends that member's access; the tombstone it leaves must not
        keep handing the app a credential to act with."""
        await register_app_service(session, listing_uid=SHOP_UID)
        guild, user, app = await _install(session, with_values=True)
        await _member_connection(session, guild=guild, app=app, user=user, blocked=True)

        response = await _get(client, f"{BASE}/installs/{guild.id}/config")

        assert response.status_code == 200, response.text
        assert response.json()["member_connections"] == []

    async def test_another_apps_install_is_unreadable(
        self, client: AsyncClient, session: AsyncSession
    ):
        """The whole point of the channel: one app's credentials are not
        reachable by another, and the refusal says nothing about what is there."""
        await register_app_service(session, listing_uid=SHOP_UID)
        theirs, _, _ = await _install(
            session,
            definition=_definition("tests.other"),
            listing_uid=OTHER_UID,
            with_values=True,
        )

        response = await _get(client, f"{BASE}/installs/{theirs.id}/config")

        assert response.status_code == 404
        assert response.json()["detail"] == AppChannelMessages.INSTALL_NOT_FOUND
        assert GUILD_TOKEN not in response.text

    async def test_a_guild_that_never_installed_is_the_same_answer(
        self, client: AsyncClient, session: AsyncSession
    ):
        await register_app_service(session, listing_uid=SHOP_UID)
        user = await create_user(session)
        bare = await create_guild(session, creator=user)

        response = await _get(client, f"{BASE}/installs/{bare.id}/config")

        assert response.status_code == 404
        assert response.json()["detail"] == AppChannelMessages.INSTALL_NOT_FOUND

    async def test_a_guild_that_does_not_exist_is_the_same_answer(
        self, client: AsyncClient, session: AsyncSession
    ):
        await register_app_service(session, listing_uid=SHOP_UID)

        response = await _get(client, f"{BASE}/installs/999999/config")

        assert response.status_code == 404
        assert response.json()["detail"] == AppChannelMessages.INSTALL_NOT_FOUND

    async def test_an_install_the_guild_turned_off_refuses(
        self, client: AsyncClient, session: AsyncSession
    ):
        """The guild's own switch stops the pull, exactly as the operator's
        does — a disabled app holds no live credential channel."""
        await register_app_service(session, listing_uid=SHOP_UID)
        guild, _, _ = await _install(session, with_values=True, enabled=False)

        response = await _get(client, f"{BASE}/installs/{guild.id}/config")

        assert response.status_code == 409
        assert response.json()["detail"] == AppChannelMessages.INSTALL_DISABLED
        assert GUILD_TOKEN not in response.text

    async def test_a_disabled_registration_refuses(
        self, client: AsyncClient, session: AsyncSession
    ):
        await register_app_service(session, listing_uid=SHOP_UID, enabled=False)
        guild, _, _ = await _install(session, with_values=True)

        response = await _get(client, f"{BASE}/installs/{guild.id}/config")

        assert response.status_code == 403
        assert response.json()["detail"] == AppChannelMessages.APP_DISABLED
        assert GUILD_TOKEN not in response.text


# ---------------------------------------------------------------------------
# Who connected — status, never values
# ---------------------------------------------------------------------------


class TestConnectionsChannel:
    async def test_connections_report_state_and_never_a_value(
        self, client: AsyncClient, session: AsyncSession
    ):
        await register_app_service(session, listing_uid=SHOP_UID)
        guild, user, app = await _install(session, with_values=True)
        await _member_connection(session, guild=guild, app=app, user=user)

        response = await _get(client, f"{BASE}/installs/{guild.id}/connections")

        assert response.status_code == 200, response.text
        items = response.json()["items"]
        assert len(items) == 1
        assert items[0]["connection_ref"] == "cr_member_one"
        assert items[0]["connection_id"] == "github"
        assert items[0]["status"] == "connected"
        assert items[0]["blocked"] is False
        # Neither the member's own credential nor the guild's appears here.
        assert MEMBER_TOKEN not in response.text
        assert GUILD_TOKEN not in response.text
        assert "values" not in items[0]

    async def test_connections_never_name_the_member(
        self, client: AsyncClient, session: AsyncSession
    ):
        await register_app_service(session, listing_uid=SHOP_UID)
        guild, user, app = await _install(session)
        await _member_connection(session, guild=guild, app=app, user=user)

        response = await _get(client, f"{BASE}/installs/{guild.id}/connections")

        assert response.status_code == 200, response.text
        assert "user_id" not in response.text
        assert user.email not in response.text
        assert str(user.id) not in [
            item["connection_ref"] for item in response.json()["items"]
        ]

    async def test_a_blocked_connection_is_reported_as_blocked(
        self, client: AsyncClient, session: AsyncSession
    ):
        """An app reconciling needs to know the handle is finished; that is the
        whole of what a block tells it."""
        await register_app_service(session, listing_uid=SHOP_UID)
        guild, user, app = await _install(session)
        await _member_connection(session, guild=guild, app=app, user=user, blocked=True)

        response = await _get(client, f"{BASE}/installs/{guild.id}/connections")

        assert response.status_code == 200, response.text
        assert response.json()["items"][0]["blocked"] is True

    async def test_another_apps_connections_are_unreachable(
        self, client: AsyncClient, session: AsyncSession
    ):
        await register_app_service(session, listing_uid=SHOP_UID)
        theirs, user, app = await _install(
            session, definition=_definition("tests.other"), listing_uid=OTHER_UID
        )
        await _member_connection(session, guild=theirs, app=app, user=user)

        response = await _get(client, f"{BASE}/installs/{theirs.id}/connections")

        assert response.status_code == 404
        assert response.json()["detail"] == AppChannelMessages.INSTALL_NOT_FOUND


# ---------------------------------------------------------------------------
# Resolving a delegate's subject to this app's own handle
# ---------------------------------------------------------------------------


SECOND_CONNECTION = {
    "id": "gitlab",
    "scope": "interactive",
    "label": {"en": "GitLab"},
    "connect_path": "/connect/gitlab",
    "fields": [_field("access_token", "secret", managed=True)],
}


class TestResolveDelegatedConnection:
    """One app is handed a token naming a member by another app's subject, and
    has to find its *own* credential for that person. Both sides hold an
    identifier and neither can turn one into the other, so this is the lookup —
    and everything it will not answer matters as much as what it will."""

    async def _delegated(
        self,
        session: AsyncSession,
        *,
        definition: dict | None = None,
        authorize: bool = True,
        connected: bool = True,
        blocked: bool = False,
    ):
        """A guild where the delegate may act as a member who has also
        connected their own account to the calling app."""
        await register_app_service(session, listing_uid=SHOP_UID)
        guild, owner, app = await _install(session, definition=definition)
        member = await create_user(session)
        await create_guild_membership(session, user=member, guild=guild)
        await register_delegate(session)
        subject = await delegate_subject(session, guild, member)
        if authorize:
            await authorize_delegate(session, guild, member)
        if connected:
            await _member_connection(
                session, guild=guild, app=app, user=member, blocked=blocked
            )
        return guild, app, member, subject

    def _path(self, guild_id: int) -> str:
        return f"{BASE}/installs/{guild_id}/connections/resolve"

    async def test_a_subject_resolves_to_this_apps_own_reference(
        self, client: AsyncClient, session: AsyncSession
    ):
        guild, _, _, subject = await self._delegated(session)

        response = await _get(
            client,
            self._path(guild.id),
            query=f"?delegate={DELEGATE_PUBLIC_ID}&subject={subject}",
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["connection_ref"] == "cr_member_one"
        assert body["connection_id"] == "github"
        assert body["status"] == "connected"

    async def test_the_answer_names_nobody(
        self, client: AsyncClient, session: AsyncSession
    ):
        """The app learns one thing: that it already knew this person by that
        reference. Not a name, not an address, not a user id."""
        guild, _, member, subject = await self._delegated(session)

        response = await _get(
            client,
            self._path(guild.id),
            query=f"?delegate={DELEGATE_PUBLIC_ID}&subject={subject}",
        )

        assert response.status_code == 200, response.text
        assert "user_id" not in response.text
        assert member.email not in response.text
        assert MEMBER_TOKEN not in response.text

    async def test_a_member_who_has_not_connected_is_a_miss(
        self, client: AsyncClient, session: AsyncSession
    ):
        """The ordinary steady state for somebody who never connected an
        account, and it reads the same as every other miss."""
        guild, _, _, subject = await self._delegated(session, connected=False)

        response = await _get(
            client,
            self._path(guild.id),
            query=f"?delegate={DELEGATE_PUBLIC_ID}&subject={subject}",
        )

        assert response.status_code == 404
        assert response.json()["detail"] == AppChannelMessages.CONNECTION_NOT_FOUND

    async def test_a_blocked_connection_does_not_resolve(
        self, client: AsyncClient, session: AsyncSession
    ):
        """A block ended that member's access. The tombstone must not hand back
        a handle for the app to act with."""
        guild, _, _, subject = await self._delegated(session, blocked=True)

        response = await _get(
            client,
            self._path(guild.id),
            query=f"?delegate={DELEGATE_PUBLIC_ID}&subject={subject}",
        )

        assert response.status_code == 404
        assert response.json()["detail"] == AppChannelMessages.CONNECTION_NOT_FOUND

    async def test_a_member_who_has_not_authorized_the_delegate_is_a_miss(
        self, client: AsyncClient, session: AsyncSession
    ):
        """Installing the delegate is the guild's decision; carrying one
        person's name is that person's, and it is asked here rather than
        assumed from the subject existing."""
        guild, _, _, subject = await self._delegated(session, authorize=False)

        response = await _get(
            client,
            self._path(guild.id),
            query=f"?delegate={DELEGATE_PUBLIC_ID}&subject={subject}",
        )

        assert response.status_code == 404

    async def test_a_switched_off_delegate_resolves_nothing(
        self, client: AsyncClient, session: AsyncSession
    ):
        """The operator's kill switch reaches this the way it reaches the
        published key set: an edit, not a key rotation."""
        guild, _, _, subject = await self._delegated(session)
        await _disable_delegate(session)

        response = await _get(
            client,
            self._path(guild.id),
            query=f"?delegate={DELEGATE_PUBLIC_ID}&subject={subject}",
        )

        assert response.status_code == 404

    async def test_a_registration_without_the_delegation_grant_resolves_nothing(
        self, client: AsyncClient, session: AsyncSession
    ):
        """An app the operator never granted delegation cannot be the reason
        another app acts as somebody."""
        await register_app_service(session, listing_uid=SHOP_UID)
        guild, owner, app = await _install(session)
        await register_delegate(session, grants=())
        subject = await delegate_subject(session, guild, owner)
        await authorize_delegate(session, guild, owner)
        await _member_connection(session, guild=guild, app=app, user=owner)

        response = await _get(
            client,
            self._path(guild.id),
            query=f"?delegate={DELEGATE_PUBLIC_ID}&subject={subject}",
        )

        assert response.status_code == 404

    async def test_a_subject_minted_for_another_app_does_not_resolve(
        self, client: AsyncClient, session: AsyncSession
    ):
        """A subject is pairwise: it resolves for the delegate it was minted
        for and for no other, so the delegate named has to be that one."""
        guild, _, _, subject = await self._delegated(session)

        response = await _get(
            client,
            self._path(guild.id),
            query=f"?delegate=tests.shop&subject={subject}",
        )

        assert response.status_code == 404

    async def test_an_unknown_subject_is_a_miss(
        self, client: AsyncClient, session: AsyncSession
    ):
        guild, _, _, _ = await self._delegated(session)

        response = await _get(
            client,
            self._path(guild.id),
            query=f"?delegate={DELEGATE_PUBLIC_ID}&subject=notasubjectatall",
        )

        assert response.status_code == 404

    async def test_another_apps_install_cannot_be_resolved_against(
        self, client: AsyncClient, session: AsyncSession
    ):
        """The install bounds the answer, so a caller never learns a handle
        belonging to somebody else's install."""
        await register_app_service(session, listing_uid=SHOP_UID)
        theirs, owner, app = await _install(
            session, definition=_definition("tests.other"), listing_uid=OTHER_UID
        )
        await register_delegate(session)
        subject = await delegate_subject(session, theirs, owner)
        await authorize_delegate(session, theirs, owner)
        await _member_connection(session, guild=theirs, app=app, user=owner)

        response = await _get(
            client,
            self._path(theirs.id),
            query=f"?delegate={DELEGATE_PUBLIC_ID}&subject={subject}",
        )

        assert response.status_code == 404
        assert response.json()["detail"] == AppChannelMessages.INSTALL_NOT_FOUND

    async def test_two_connections_are_not_guessed_between(
        self, client: AsyncClient, session: AsyncSession
    ):
        """An app declaring several per-member connections is asked which one
        it means rather than handed whichever sorted first."""
        definition = _definition()
        definition["connections"] = [*definition["connections"], SECOND_CONNECTION]
        guild, app, member, subject = await self._delegated(
            session, definition=definition
        )
        await _member_connection(
            session,
            guild=guild,
            app=app,
            user=member,
            connection_id="gitlab",
            connection_ref="cr_member_two",
        )

        response = await _get(
            client,
            self._path(guild.id),
            query=f"?delegate={DELEGATE_PUBLIC_ID}&subject={subject}",
        )

        assert response.status_code == 422
        assert response.json()["detail"] == AppChannelMessages.CONNECTION_UNSPECIFIED

    async def test_naming_the_connection_settles_it(
        self, client: AsyncClient, session: AsyncSession
    ):
        definition = _definition()
        definition["connections"] = [*definition["connections"], SECOND_CONNECTION]
        guild, app, member, subject = await self._delegated(
            session, definition=definition
        )
        await _member_connection(
            session,
            guild=guild,
            app=app,
            user=member,
            connection_id="gitlab",
            connection_ref="cr_member_two",
        )

        response = await _get(
            client,
            self._path(guild.id),
            query=(
                f"?delegate={DELEGATE_PUBLIC_ID}&subject={subject}&connection=gitlab"
            ),
        )

        assert response.status_code == 200, response.text
        assert response.json()["connection_ref"] == "cr_member_two"

    async def test_an_unsigned_request_resolves_nothing(
        self, client: AsyncClient, session: AsyncSession
    ):
        """The caller is established before anything is read — the query names
        what to look up, never who is asking."""
        guild, _, _, subject = await self._delegated(session)
        path = self._path(guild.id)

        response = await client.get(
            f"{path}?delegate={DELEGATE_PUBLIC_ID}&subject={subject}"
        )

        assert response.status_code == 401


# ---------------------------------------------------------------------------
# Writing back what a vendor flow produced
# ---------------------------------------------------------------------------


class TestConnectionWriteBack:
    async def test_a_managed_value_is_stored_and_served_only_on_config(
        self, client: AsyncClient, session: AsyncSession
    ):
        await register_app_service(session, listing_uid=SHOP_UID)
        guild, user, app = await _install(session)
        row = await _member_connection(
            session, guild=guild, app=app, user=user, with_secret=False
        )

        written = await _put(
            client,
            f"{BASE}/installs/{guild.id}/connections/{row.connection_ref}",
            {
                "values": {"access_token": "gho_freshly_minted"},
                "account_label": "@alice",
            },
        )

        assert written.status_code == 200, written.text
        assert written.json()["status"] == "connected"
        assert written.json()["account_label"] == "@alice"
        # The write-back answer reports state; the value comes back only where
        # values are meant to.
        assert "gho_freshly_minted" not in written.text

        config = await _get(client, f"{BASE}/installs/{guild.id}/config")
        assert config.status_code == 200, config.text
        assert config.json()["member_connections"][0]["values"] == {
            "access_token": "gho_freshly_minted"
        }

    async def test_a_refresh_replaces_the_stored_value(
        self, client: AsyncClient, session: AsyncSession
    ):
        """Rotation runs down the same path as first connect, which is what
        keeps a token rotated at 03:00 revocable at 03:05."""
        await register_app_service(session, listing_uid=SHOP_UID)
        guild, user, app = await _install(session)
        row = await _member_connection(session, guild=guild, app=app, user=user)
        path = f"{BASE}/installs/{guild.id}/connections/{row.connection_ref}"

        assert (
            await _put(client, path, {"values": {"access_token": "gho_rotated"}})
        ).status_code == 200

        config = await _get(client, f"{BASE}/installs/{guild.id}/config")
        assert config.json()["member_connections"][0]["values"] == {
            "access_token": "gho_rotated"
        }

    async def test_a_blocked_connection_refuses_a_write_back(
        self, client: AsyncClient, session: AsyncSession
    ):
        await register_app_service(session, listing_uid=SHOP_UID)
        guild, user, app = await _install(session)
        row = await _member_connection(
            session, guild=guild, app=app, user=user, blocked=True
        )

        response = await _put(
            client,
            f"{BASE}/installs/{guild.id}/connections/{row.connection_ref}",
            {"values": {"access_token": "gho_sneaking_back"}},
        )

        assert response.status_code == 403
        assert response.json()["detail"] == AppChannelMessages.CONNECTION_BLOCKED

    async def test_an_unknown_reference_is_refused(
        self, client: AsyncClient, session: AsyncSession
    ):
        await register_app_service(session, listing_uid=SHOP_UID)
        guild, _, _ = await _install(session)

        response = await _put(
            client,
            f"{BASE}/installs/{guild.id}/connections/cr_not_a_handle",
            {"values": {"access_token": "x"}},
        )

        assert response.status_code == 404
        assert response.json()["detail"] == AppChannelMessages.CONNECTION_NOT_FOUND

    async def test_a_field_the_definition_does_not_declare_is_refused(
        self, client: AsyncClient, session: AsyncSession
    ):
        await register_app_service(session, listing_uid=SHOP_UID)
        guild, user, app = await _install(session)
        row = await _member_connection(session, guild=guild, app=app, user=user)

        response = await _put(
            client,
            f"{BASE}/installs/{guild.id}/connections/{row.connection_ref}",
            {"values": {"not_a_field": "x"}},
        )

        assert response.status_code == 400
        assert response.json()["detail"] == GuildAppMessages.CONFIG_UNKNOWN_FIELD


# ---------------------------------------------------------------------------
# The app's own verdict
# ---------------------------------------------------------------------------


class TestStatusReport:
    async def test_reporting_ok_moves_the_state(
        self, client: AsyncClient, session: AsyncSession
    ):
        """Nothing else in this build writes ``ok``. Before the app reports,
        an install has no verdict at all."""
        await register_app_service(session, listing_uid=SHOP_UID)
        guild, _, app = await _install(session, with_values=True)
        assert app.config_state == "unverified"

        response = await _post(
            client, f"{BASE}/installs/{guild.id}/status", {"state": "ok"}
        )

        assert response.status_code == 200, response.text
        assert response.json()["config_state"] == "ok"
        stored = await _reload(session, guild.id, app.id)
        assert stored.config_state == "ok"
        assert stored.config_state_detail is None

    async def test_reporting_invalid_carries_the_reason(
        self, client: AsyncClient, session: AsyncSession
    ):
        """An admin whose token lacks a scope should read that, not an empty
        widget."""
        await register_app_service(session, listing_uid=SHOP_UID)
        guild, _, app = await _install(session, with_values=True)

        response = await _post(
            client,
            f"{BASE}/installs/{guild.id}/status",
            {"state": "invalid", "detail": "missing_read_orders"},
        )

        assert response.status_code == 200, response.text
        stored = await _reload(session, guild.id, app.id)
        assert stored.config_state == "invalid"
        assert stored.config_state_detail == "missing_read_orders"

    async def test_a_state_outside_the_vocabulary_is_refused(
        self, client: AsyncClient, session: AsyncSession
    ):
        await register_app_service(session, listing_uid=SHOP_UID)
        guild, _, app = await _install(session)

        response = await _post(
            client, f"{BASE}/installs/{guild.id}/status", {"state": "wonderful"}
        )

        assert response.status_code == 422
        assert response.json()["detail"] == AppChannelMessages.INVALID_PAYLOAD
        stored = await _reload(session, guild.id, app.id)
        assert stored.config_state == "unverified"

    async def test_another_apps_install_cannot_be_reported_on(
        self, client: AsyncClient, session: AsyncSession
    ):
        await register_app_service(session, listing_uid=SHOP_UID)
        theirs, _, app = await _install(
            session, definition=_definition("tests.other"), listing_uid=OTHER_UID
        )

        response = await _post(
            client, f"{BASE}/installs/{theirs.id}/status", {"state": "ok"}
        )

        assert response.status_code == 404
        stored = await _reload(session, theirs.id, app.id)
        assert stored.config_state == "unverified"
