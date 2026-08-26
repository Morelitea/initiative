"""The sweep that keeps installs on the versions their publishers ship.

Auto is the resting state, so the tests are mostly about the edges of that: an
install a guild took off the track stays where it is, and a version this
deployment cannot run is applied to nobody. Those are the cases where sweeping
the wrong install has a cost, and neither shows up on the happy path.

The inner pass is driven with the test session — routed into the guild the way
the worker routes itself — because ``process_app_auto_updates`` opens its own
system-engine session against the configured database rather than the test one.
"""

import asyncio

import pytest
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.tenant.guild_app import GuildApp
from app.services.tenant import app_updates
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


def _connection_definition(name: str = "Shop", *, keys=("shop_domain",)) -> dict:
    """A service app declaring one connection with the given fields.

    The field list is what varies between versions: an upgrade that drops one is
    what makes the pass *write* the config column at all. Where the new version
    declares everything the old one did, pruning produces a value equal to what
    was loaded, SQLAlchemy computes no net change, and the column stays out of
    the UPDATE entirely — so a version that drops a field is the shape in which
    a stale read can reach the database.
    """
    return {
        "app_kind": "service",
        "service": {"public_id": "tests.autoconcur", "protocol": 1},
        "features": [],
        "default_name": name,
        "connections": [
            {
                "id": "admin",
                "scope": "static",
                "label": {"en": "Admin API"},
                "fields": [
                    {"key": key, "type": "string", "label": {"en": key}} for key in keys
                ],
            }
        ],
    }


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
        definition=overrides.pop("definition", None) or _definition(),
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

    async def test_a_credential_saved_during_the_pass_is_not_overwritten(
        self, session: AsyncSession, engine, monkeypatch
    ):
        """An admin saving configuration while the pass runs keeps their values.

        Resolving the catalog sits between reading an install and writing it,
        and an admin typing a credential is exactly what happens in that gap, so
        the write below is launched from inside the catalog read on its own
        connection — the moment the pass is genuinely mid-flight.

        The shape matters: the new version here **drops a field**, which is what
        makes the pass write the config column at all. An upgrade that prunes
        nothing produces a value equal to what it loaded, and the column never
        reaches the UPDATE. So this is the case where working from the earlier
        read puts a stale copy in the database on top of what the admin had just
        committed. Reading the row again under a lock orders the two instead:
        their write waits for the pass and lands after it.
        """
        uid = marketplace_uid("autoconcur")
        old_shape = _connection_definition(keys=("shop_domain", "legacy_key"))
        await _publish(session, uid, "1.0.0", definition=old_shape)
        guild, app = await _installed(
            session,
            uid,
            definition=old_shape,
            # What the install already held. The admin is about to replace the
            # domain, and this is the value a stale write-back would restore.
            config={"admin": {"shop_domain": "before.example", "legacy_key": "x"}},
        )
        # The new version drops ``legacy_key``, which is what makes the pass
        # write the config column rather than leave it untouched.
        await _publish(
            session,
            uid,
            "1.1.0",
            definition=_connection_definition("Shop v2", keys=("shop_domain",)),
        )
        # Committed so the admin's own connection can see the install at all.
        await session.commit()
        guild_id, app_id = guild.id, app.id

        # Set once the admin's own connection is up and has read the row, so
        # the wait below covers their write rather than the cost of connecting.
        ready = asyncio.Event()

        async def admin_saves_a_credential() -> None:
            async with AsyncSession(engine) as admin:
                await route_session_to_guild(admin, guild_id)
                row = (
                    await admin.exec(select(GuildApp).where(GuildApp.id == app_id))
                ).one()
                ready.set()
                row.config = {
                    "admin": {
                        "shop_domain": "typed-just-now.example",
                        "legacy_key": "x",
                    }
                }
                admin.add(row)
                await admin.commit()

        saved = None
        real_resolve = app_updates._resolve_pending

        async def resolve_while_the_admin_writes(inner_session, install):
            nonlocal saved
            if saved is None:
                saved = asyncio.create_task(admin_saves_a_credential())
                await ready.wait()
                # Their write now either commits outright or waits on the lock.
                await asyncio.sleep(0.3)
            return await real_resolve(inner_session, install)

        monkeypatch.setattr(
            app_updates, "_resolve_pending", resolve_while_the_admin_writes
        )

        await route_session_to_guild(session, guild_id)
        assert await _update_guild(session, guild_id) == 1
        await session.commit()
        # The hook fired, so the write below really did happen mid-pass rather
        # than never being launched — without which this asserts nothing.
        assert saved is not None
        await saved

        updated = await _reread(session, guild_id, app_id)
        assert updated.listing_version == "1.1.0"
        # Theirs, not the copy the pass started from. Working off the earlier
        # read stores ``before.example`` here instead.
        assert updated.config["admin"]["shop_domain"] == "typed-just-now.example"

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
