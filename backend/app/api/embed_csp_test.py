"""Which document may frame which app.

The property under test is narrowness. A page that opens one app's embed is
allowed to frame **that app's** origins; every other page, and every other app,
gets nothing. A policy that listed every registered app would work just as well
for the app being opened — and would also hand every page in the product the
address of every integration the deployment has ever approved, growing with the
catalog forever. So the assertions are as much about what is *absent* from the
header as about what is present.

The other half is who is asking. Only a member of the guild in the path gets the
permission, so the header describes an app to people who already see it in their
sidebar.
"""

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.embed_csp import parse_embed_path, resolve_frame_origins
from app.core.config import settings
from app.models.platform.guild import GuildRole
from app.services.marketplace.registration_lookup import invalidate_registrations
from app.testing import (
    create_app_service_registration,
    create_guild,
    create_guild_app,
    create_guild_membership,
    create_user,
    marketplace_uid,
)

pytestmark = pytest.mark.asyncio

APP_ID = "tests.framed"
OTHER_ID = "tests.other"


def _definition(public_id: str = APP_ID) -> dict:
    return {
        "app_kind": "service",
        "service": {"public_id": public_id, "protocol": 1},
        "features": ["embeds"],
        "embeds": [
            {
                "id": "board",
                "path": "/embed/board",
                "visibility": "member",
                "name": {"en": "Board"},
            }
        ],
    }


class TestParsingTheRoute:
    @pytest.mark.unit
    def test_it_reads_the_embed_route(self):
        assert parse_embed_path("/g/7/apps/12") == (7, 12)
        assert parse_embed_path("g/7/apps/12") == (7, 12)

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "path",
        [
            "",
            "/",
            "/g/7/apps",
            "/g/7/apps/12/extra",
            "/g/seven/apps/12",
            "/g/7/projects/12",
            "/g/0/apps/12",
            "/g/-1/apps/12",
            "/api/v1/g/7/apps/12",
        ],
    )
    def test_everything_else_is_not_an_embed_document(self, path: str):
        assert parse_embed_path(path) is None


class TestResolvingOrigins:
    async def test_a_member_gets_the_opened_app_and_nothing_else(
        self, session: AsyncSession
    ):
        user = await create_user(session, email="framed@example.com")
        guild = await create_guild(session, creator=user)
        await create_guild_membership(
            session, user=user, guild=guild, role=GuildRole.admin
        )
        app = await create_guild_app(
            session,
            guild,
            user,
            definition=_definition(),
            listing_uid=marketplace_uid("framed"),
        )
        await create_app_service_registration(
            session,
            public_id=APP_ID,
            base_url="https://framed.example.test",
            allowed_origins=["https://framed.example.test"],
        )
        # A second registered app the guild is not opening. Its origins must not
        # appear anywhere near this document.
        await create_app_service_registration(
            session,
            public_id=OTHER_ID,
            base_url="https://other.example.test",
            allowed_origins=["https://other.example.test"],
        )

        origins = await resolve_frame_origins(
            guild_id=guild.id, app_id=app.id, user_id=user.id
        )
        assert origins == ("https://framed.example.test",)

        policy = settings.content_security_policy_with_frames(origins)
        frame_src = _directive(policy, "frame-src")
        assert "https://framed.example.test" in frame_src
        assert "https://other.example.test" not in policy

    async def test_a_non_member_gets_nothing(self, session: AsyncSession):
        owner = await create_user(session, email="owner@example.com")
        guild = await create_guild(session, creator=owner)
        await create_guild_membership(
            session, user=owner, guild=guild, role=GuildRole.admin
        )
        app = await create_guild_app(
            session,
            guild,
            owner,
            definition=_definition(),
            listing_uid=marketplace_uid("framed"),
        )
        await create_app_service_registration(
            session, public_id=APP_ID, base_url="https://framed.example.test"
        )
        outsider = await create_user(session, email="outsider@example.com")

        assert (
            await resolve_frame_origins(
                guild_id=guild.id, app_id=app.id, user_id=outsider.id
            )
            == ()
        )

    async def test_a_deactivated_registration_frames_nothing(
        self, session: AsyncSession
    ):
        """The kill switch reaches the header too: a stopped app is not framed
        while it is stopped."""
        user = await create_user(session, email="stopped@example.com")
        guild = await create_guild(session, creator=user)
        await create_guild_membership(
            session, user=user, guild=guild, role=GuildRole.admin
        )
        app = await create_guild_app(
            session,
            guild,
            user,
            definition=_definition(),
            listing_uid=marketplace_uid("framed"),
        )
        registration = await create_app_service_registration(
            session, public_id=APP_ID, base_url="https://framed.example.test"
        )

        registration.enabled = False
        session.add(registration)
        await session.commit()
        invalidate_registrations()

        assert (
            await resolve_frame_origins(
                guild_id=guild.id, app_id=app.id, user_id=user.id
            )
            == ()
        )

    async def test_an_app_with_no_service_frames_nothing(self, session: AsyncSession):
        """A tool instance mounts one of this build's own tools; there is no
        third-party frame in it to permit."""
        user = await create_user(session, email="tool@example.com")
        guild = await create_guild(session, creator=user)
        await create_guild_membership(
            session, user=user, guild=guild, role=GuildRole.admin
        )
        app = await create_guild_app(
            session,
            guild,
            user,
            definition={"app_kind": "tool_instance", "tool": "calendar"},
            listing_uid=marketplace_uid("calendarapp"),
        )

        assert (
            await resolve_frame_origins(
                guild_id=guild.id, app_id=app.id, user_id=user.id
            )
            == ()
        )


@pytest.mark.unit
def test_the_ordinary_policy_frames_no_app():
    """Every document that is not opening an embed carries this one."""
    policy = settings.content_security_policy
    frame_src = _directive(policy, "frame-src")
    assert "example.test" not in frame_src


def _directive(policy: str, name: str) -> str:
    for directive in policy.split(";"):
        cleaned = directive.strip()
        if cleaned.startswith(f"{name} "):
            return cleaned
    raise AssertionError(f"{name} missing from {policy!r}")
