"""The sweep that keeps installs on the versions their publishers ship.

Auto is the resting state, so the tests are mostly about the edges of that: an
install a guild took off the track stays where it is, and a version this
deployment cannot run is applied to nobody. Those are the cases where sweeping
the wrong install has a cost, and neither shows up on the happy path.

The inner pass is driven with the test session — routed into the guild the way
the worker routes itself — because ``process_app_auto_updates`` opens its own
system-engine session against the configured database rather than the test one.
"""

import pytest
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.tenant.guild_app import GuildApp
from app.services.tenant.app_updates import _update_guild, update_version
from app.testing import (
    create_guild,
    create_guild_app,
    create_marketplace_listing,
    create_user,
    marketplace_uid,
    route_session_to_guild,
)

pytestmark = pytest.mark.asyncio


def _definition(name: str = "Cal") -> dict:
    return {"app_kind": "tool_instance", "tool": "calendar", "default_name": name}


async def _publish(session: AsyncSession, uid: str, version: str, **overrides):
    """Publish one version of a test app listing.

    Re-publishing the same uid at a new version is what a publisher shipping an
    update looks like, and is what the sweep is meant to notice.
    """
    return await create_marketplace_listing(
        session,
        uid=uid,
        public_id=f"tests.{uid.lower()}",
        kind="app",
        version=version,
        definition=overrides.pop("definition", _definition()),
        **overrides,
    )


async def _installed(session: AsyncSession, uid: str, **overrides) -> tuple:
    """A guild with one install of that listing, pinned at 1.0.0."""
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    app = await create_guild_app(
        session,
        guild,
        user,
        definition=_definition(),
        listing_uid=uid,
        listing_version="1.0.0",
        **overrides,
    )
    return guild, app


async def _reread(session: AsyncSession, guild_id: int, app_id: int) -> GuildApp:
    session.expunge_all()
    await route_session_to_guild(session, guild_id)
    return (await session.exec(select(GuildApp).where(GuildApp.id == app_id))).one()


class TestTheSweep:
    async def test_a_tracking_install_moves_to_the_published_version(
        self, session: AsyncSession
    ):
        uid = marketplace_uid("autotracks")
        await _publish(session, uid, "1.0.0")
        guild, app = await _installed(session, uid)

        await _publish(session, uid, "1.1.0", definition=_definition("Cal v2"))

        await route_session_to_guild(session, guild.id)
        assert await _update_guild(session, guild.id) == 1
        await session.commit()

        updated = await _reread(session, guild.id, app.id)
        assert updated.listing_version == "1.1.0"
        assert updated.definition["default_name"] == "Cal v2"
        # The app has not seen the new shape yet, so its old verdict is not an
        # answer to the current question.
        assert updated.config_state == "unverified"

    async def test_an_install_that_opted_out_is_left_where_it_is(
        self, session: AsyncSession
    ):
        """The whole of what turning it off buys: the guild's own copy stops
        moving until somebody here asks for it."""
        uid = marketplace_uid("automanual")
        await _publish(session, uid, "1.0.0")
        guild, app = await _installed(session, uid, auto_update=False)

        await _publish(session, uid, "1.1.0", definition=_definition("Cal v2"))

        await route_session_to_guild(session, guild.id)
        assert await _update_guild(session, guild.id) == 0
        await session.commit()

        assert (await _reread(session, guild.id, app.id)).listing_version == "1.0.0"

    async def test_a_disabled_install_still_tracks(self, session: AsyncSession):
        """Turning an app off is not the same answer as taking it off the
        track: one switched back on months later should not come back on a
        version its publisher replaced long ago."""
        uid = marketplace_uid("autooffbut")
        await _publish(session, uid, "1.0.0")
        guild, app = await _installed(session, uid, enabled=False)

        await _publish(session, uid, "1.1.0", definition=_definition("Cal v2"))

        await route_session_to_guild(session, guild.id)
        assert await _update_guild(session, guild.id) == 1
        await session.commit()

        updated = await _reread(session, guild.id, app.id)
        assert updated.listing_version == "1.1.0"
        assert updated.enabled is False

    async def test_a_pass_with_nothing_published_changes_nothing(
        self, session: AsyncSession
    ):
        uid = marketplace_uid("autosteady")
        await _publish(session, uid, "1.0.0")
        guild, app = await _installed(session, uid)

        await route_session_to_guild(session, guild.id)
        assert await _update_guild(session, guild.id) == 0
        await session.commit()

        assert (await _reread(session, guild.id, app.id)).listing_version == "1.0.0"

    async def test_a_version_needing_a_newer_build_is_not_applied(
        self, session: AsyncSession
    ):
        """Better a working old version than one this deployment cannot run.

        The install is not silently moved to some older compatible version
        either: it stays exactly where the guild had it until this deployment
        is new enough for what the publisher shipped.
        """
        uid = marketplace_uid("autofuture")
        await _publish(session, uid, "1.0.0")
        guild, app = await _installed(session, uid)

        await _publish(
            session,
            uid,
            "2.0.0",
            definition=_definition("Cal v2"),
            min_app_version="999.0.0",
        )

        await route_session_to_guild(session, guild.id)
        assert await _update_guild(session, guild.id) == 0
        await session.commit()

        assert (await _reread(session, guild.id, app.id)).listing_version == "1.0.0"

    async def test_a_withdrawn_listing_leaves_its_installs_alone(
        self, session: AsyncSession
    ):
        """A publisher pulling a listing does not un-install it: the guild keeps
        what it has, on the version it pinned."""
        uid = marketplace_uid("autogone")
        listing = await _publish(session, uid, "1.0.0")
        guild, app = await _installed(session, uid)

        await _publish(session, uid, "1.1.0", definition=_definition("Cal v2"))
        listing.available = False
        session.add(listing)
        await session.commit()

        await route_session_to_guild(session, guild.id)
        assert await _update_guild(session, guild.id) == 0
        await session.commit()

        assert (await _reread(session, guild.id, app.id)).listing_version == "1.0.0"


class TestUpdateVersion:
    """What the settings page is told there is to move to."""

    async def test_it_names_the_version_an_update_would_apply(
        self, session: AsyncSession
    ):
        uid = marketplace_uid("autooffer")
        await _publish(session, uid, "1.0.0")
        guild, app = await _installed(session, uid)
        await _publish(session, uid, "1.2.0", definition=_definition("Cal v2"))

        await route_session_to_guild(session, guild.id)
        assert await update_version(session, app) == "1.2.0"

    async def test_an_install_on_the_newest_is_offered_nothing(
        self, session: AsyncSession
    ):
        uid = marketplace_uid("autocurrent")
        await _publish(session, uid, "1.0.0")
        guild, app = await _installed(session, uid)

        await route_session_to_guild(session, guild.id)
        assert await update_version(session, app) is None
