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

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.guild import GuildRole
from app.models.platform.notification import Notification, NotificationType
from app.models.tenant.guild_app import GuildApp
from app.services.tenant import app_updates
from app.services.tenant.app_updates import (
    AskedUpdate,
    _update_guild,
    decline_version,
    notify_pending_updates,
    update_version,
)
from app.testing import (
    create_app_service_registration,
    create_guild,
    create_guild_app,
    create_guild_membership,
    create_marketplace_listing,
    create_user,
    marketplace_uid,
    route_session_to_guild,
)


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

    async def test_a_service_the_deployment_stopped_running_still_updates(
        self, session: AsyncSession
    ):
        """Whether this deployment runs an app's service decides whether a
        guild may *take* it. An install that is already here is the guild's
        either way, so it keeps following the version its publisher ships —
        switching the service back on finds the app current rather than a
        version behind."""
        uid = marketplace_uid("autounwired")
        definition = _connection_definition()
        await _publish(session, uid, "1.0.0", definition=definition)
        guild, app = await _installed(session, uid, definition=definition)
        await _publish(
            session,
            uid,
            "1.3.0",
            definition=_connection_definition("Shop v2", keys=("shop_domain", "token")),
        )

        await route_session_to_guild(session, guild.id)
        assert await update_version(session, app) == "1.3.0"


# --- versions that ask for more ----------------------------------------------

ASKING_SERVICE = "tests.asksmore"


def _asking_definition(
    *, scopes=("projects:read",), inside=(), name: str = "Asks"
) -> dict:
    """A service app requesting ``scopes``, with one initiative surface per id
    in ``inside``."""
    return {
        "app_kind": "service",
        "service": {
            "public_id": ASKING_SERVICE,
            "protocol": 1,
            "scopes": list(scopes),
        },
        "features": ["embeds"] if inside else [],
        "default_name": name,
        **(
            {
                "embeds": [
                    {
                        "id": surface,
                        "path": f"/embed/{surface}",
                        "scopes": ["initiative"],
                        "admin_only": False,
                        "name": {"en": surface.title()},
                    }
                    for surface in inside
                ]
            }
            if inside
            else {}
        ),
    }


async def _asking_install(
    session: AsyncSession,
    uid: str,
    *,
    granted=("projects:read",),
    mandatory: bool = False,
    **definition,
):
    """An install of a registered service app pinned at 1.0.0, granted
    ``granted``, whose community has a seat holder."""
    await create_app_service_registration(
        session,
        public_id=ASKING_SERVICE,
        listing_uid=uid,
        scope_ceiling=["projects:read", "projects:write", "comments:read"],
        mandatory=mandatory,
    )
    await _publish(session, uid, "1.0.0", definition=_asking_definition(**definition))
    seat = await create_user(session)
    guild = await create_guild(session, creator=seat)
    await create_guild_membership(
        session, user=seat, guild=guild, role=GuildRole.superadmin
    )
    app = await create_guild_app(
        session,
        guild,
        seat,
        definition=_asking_definition(**definition),
        listing_uid=uid,
        listing_version="1.0.0",
        granted_scopes=list(granted),
    )
    return seat, guild, app


async def _sweep(session: AsyncSession, guild_id: int) -> tuple[int, list[AskedUpdate]]:
    asked: list[AskedUpdate] = []
    await route_session_to_guild(session, guild_id)
    moved = await _update_guild(session, guild_id, asked=asked)
    await session.commit()
    return moved, asked


class TestVersionsThatAskForMore:
    async def test_a_version_asking_nothing_new_applies(self, session: AsyncSession):
        uid = marketplace_uid("asksnothing")
        _, guild, app = await _asking_install(session, uid)
        await _publish(
            session, uid, "1.1.0", definition=_asking_definition(name="Asks v2")
        )

        moved, asked = await _sweep(session, guild.id)

        assert (moved, asked) == (1, [])
        updated = await _reread(session, guild.id, app.id)
        assert updated.listing_version == "1.1.0"
        assert updated.pending_version is None

    async def test_a_scope_the_seat_left_out_is_not_asked_again(
        self, session: AsyncSession
    ):
        """The pinned version requested ``comments:read`` and the seat did not
        grant it: a version requesting it again has answered nothing new."""
        uid = marketplace_uid("asksanswered")
        _, guild, app = await _asking_install(
            session, uid, scopes=("projects:read", "comments:read")
        )
        await _publish(
            session,
            uid,
            "1.1.0",
            definition=_asking_definition(scopes=("projects:read", "comments:read")),
        )

        moved, asked = await _sweep(session, guild.id)

        assert (moved, asked) == (1, [])

    async def test_a_new_scope_waits_and_the_seat_is_told(self, session: AsyncSession):
        uid = marketplace_uid("asksscope")
        seat, guild, app = await _asking_install(session, uid)
        await _publish(
            session,
            uid,
            "1.1.0",
            definition=_asking_definition(scopes=("projects:read", "projects:write")),
        )

        moved, asked = await _sweep(session, guild.id)

        assert moved == 0
        assert asked == [AskedUpdate(app_id=app.id, app_name=app.name, version="1.1.0")]
        waiting = await _reread(session, guild.id, app.id)
        assert waiting.listing_version == "1.0.0"
        assert waiting.pending_version == "1.1.0"
        assert waiting.granted_scopes == ["projects:read"]

        await notify_pending_updates(session, guild.id, asked)
        await session.commit()
        notices = (
            await session.exec(
                select(Notification).where(
                    Notification.user_id == seat.id,
                    Notification.type == NotificationType.app_update_pending,
                )
            )
        ).all()
        assert [notice.data["version"] for notice in notices] == ["1.1.0"]
        assert notices[0].guild_id == guild.id
        assert notices[0].data["app_id"] == app.id

        # Already waiting: the next pass neither applies it nor asks again.
        moved, asked = await _sweep(session, guild.id)
        assert (moved, asked) == (0, [])

    async def test_a_required_app_applies_and_takes_its_new_scopes(
        self, session: AsyncSession
    ):
        """The registration granted what a required app requests at install,
        with no seat asked, so a newer version is applied the same way."""
        uid = marketplace_uid("asksrequired")
        _, guild, app = await _asking_install(session, uid, mandatory=True, scopes=())
        await _publish(
            session,
            uid,
            "1.1.0",
            definition=_asking_definition(
                scopes=("projects:read", "projects:write", "tags:read")
            ),
        )

        moved, asked = await _sweep(session, guild.id)

        assert (moved, asked) == (1, [])
        updated = await _reread(session, guild.id, app.id)
        assert updated.listing_version == "1.1.0"
        assert updated.pending_version is None
        # What the version asks for within the ceiling; tags:read is above it.
        assert sorted(updated.granted_scopes) == ["projects:read", "projects:write"]

    async def test_a_required_app_already_waiting_is_applied(
        self, session: AsyncSession
    ):
        uid = marketplace_uid("askswaiting")
        _, guild, app = await _asking_install(session, uid, mandatory=True)
        await _publish(
            session,
            uid,
            "1.1.0",
            definition=_asking_definition(scopes=("projects:read", "projects:write")),
        )
        await route_session_to_guild(session, guild.id)
        row = await _reread(session, guild.id, app.id)
        row.pending_version = "1.1.0"
        session.add(row)
        await session.commit()

        moved, _ = await _sweep(session, guild.id)

        assert moved == 1
        updated = await _reread(session, guild.id, app.id)
        assert (updated.listing_version, updated.pending_version) == ("1.1.0", None)
        assert "projects:write" in updated.granted_scopes

    async def test_a_new_initiative_surface_waits(self, session: AsyncSession):
        uid = marketplace_uid("askssurface")
        _, guild, app = await _asking_install(session, uid, inside=("board",))
        await _publish(
            session,
            uid,
            "1.1.0",
            definition=_asking_definition(inside=("board", "planner")),
        )

        moved, asked = await _sweep(session, guild.id)

        assert moved == 0
        assert [one.version for one in asked] == ["1.1.0"]
        offer = await app_updates.update_offer(
            session, await _reread(session, guild.id, app.id)
        )
        assert offer is not None
        assert offer.asks.added_scopes == ()
        assert [surface["id"] for surface in offer.asks.added_surfaces] == ["planner"]

    async def test_a_declined_version_is_not_asked_again_until_a_newer_one(
        self, session: AsyncSession
    ):
        uid = marketplace_uid("asksdecline")
        _, guild, app = await _asking_install(session, uid)
        wider = _asking_definition(scopes=("projects:read", "projects:write"))
        await _publish(session, uid, "1.1.0", definition=wider)
        await _sweep(session, guild.id)

        waiting = await _reread(session, guild.id, app.id)
        decline_version(waiting, "1.1.0")
        session.add(waiting)
        await session.commit()

        moved, asked = await _sweep(session, guild.id)
        assert (moved, asked) == (0, [])
        declined = await _reread(session, guild.id, app.id)
        assert declined.declined_version == "1.1.0"
        assert declined.pending_version is None
        assert declined.listing_version == "1.0.0"

        await _publish(session, uid, "1.2.0", definition=wider)
        moved, asked = await _sweep(session, guild.id)
        assert moved == 0
        assert [one.version for one in asked] == ["1.2.0"]
        assert (await _reread(session, guild.id, app.id)).pending_version == "1.2.0"

    async def test_accepting_applies_and_grants(self, session: AsyncSession):
        uid = marketplace_uid("asksaccept")
        _, guild, app = await _asking_install(session, uid)
        await _publish(
            session,
            uid,
            "1.1.0",
            definition=_asking_definition(scopes=("projects:read", "projects:write")),
        )
        await _sweep(session, guild.id)

        waiting = await _reread(session, guild.id, app.id)
        offer = await app_updates.update_offer(session, waiting)
        assert offer is not None
        await app_updates.apply_version(
            session, waiting, offer.update, add_scopes=offer.asks.added_scopes
        )
        await session.commit()

        accepted = await _reread(session, guild.id, app.id)
        assert accepted.listing_version == "1.1.0"
        assert accepted.granted_scopes == ["projects:read", "projects:write"]
        assert accepted.pending_version is None
        assert accepted.declined_version is None


def _asking(*scopes: str) -> dict:
    return {
        "app_kind": "service",
        "service": {"public_id": "tests.caller", "protocol": 1, "scopes": list(scopes)},
        "features": [],
    }


def test_a_version_asking_to_use_another_app_asks_for_more():
    """An ``apps:`` scope is a new thing the seat has not answered, like any
    other scope a version adds."""
    app = GuildApp(
        listing_uid="TESTCALLER0001",
        listing_version="1.0.0",
        app_kind="service",
        name="Caller",
        definition=_asking("documents:read"),
        granted_scopes=["documents:read"],
        created_by=1,
    )
    ceiling = ("documents:read", "apps:tests.github")

    asks = app_updates.upgrade_asks(
        app, _asking("documents:read", "apps:tests.github"), ceiling
    )

    assert asks.added_scopes == ("apps:tests.github",)
    assert asks.asks_more


def test_an_app_scope_above_the_ceiling_asks_for_nothing():
    app = GuildApp(
        listing_uid="TESTCALLER0001",
        listing_version="1.0.0",
        app_kind="service",
        name="Caller",
        definition=_asking("documents:read"),
        granted_scopes=["documents:read"],
        created_by=1,
    )

    asks = app_updates.upgrade_asks(
        app, _asking("documents:read", "apps:tests.github"), ("documents:read",)
    )

    assert not asks.asks_more
