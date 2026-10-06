"""Migrations 20261003_0445, 20261003_0446 and 20261003_0448 rename the stored
guild values to community and back. Loaded by path and run on rows an older
release would have written, the way ``upload_initiative_backfill_test`` runs its
revision."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

from sqlalchemy import text

from app.models.platform.notification import NotificationType
from app.services.platform import notice_outbox, user_notifications
from app.testing import (
    create_plugin_service_registration,
    create_export_job,
    create_guild,
    create_guild_plugin,
    create_marketplace_listing,
    create_user,
)

_VERSIONS = Path(__file__).resolve().parents[2] / "alembic" / "versions"


def _load(name: str) -> ModuleType:
    path = _VERSIONS / name
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def _sql(session, sql, params=None):
    return await (await session.connection()).execute(sql, params or {})


async def _scalar(session, sql, params=None):
    return (await _sql(session, sql, params)).scalar()


async def _stored(session, schema: str, job_id: int) -> dict:
    notification = (
        await _sql(session, text("SELECT type, data FROM public.notifications"))
    ).one()
    outbox = (
        await _sql(
            session, text("SELECT type, data, push_data FROM public.notice_outbox")
        )
    ).one()
    source = await _scalar(
        session,
        text(f'SELECT source FROM "{schema}".export_jobs WHERE id = :id'),
        {"id": job_id},
    )
    return {
        "notification": (notification.type, notification.data),
        "outbox": (outbox.type, outbox.data, outbox.push_data),
        "source": source,
    }


async def test_stored_values_say_community_and_back(session) -> None:
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    schema = f"guild_{guild.id}"
    job = await create_export_job(session, guild, user, source="guild")
    await user_notifications.create_notification(
        session,
        user_id=user.id,
        notification_type=NotificationType.export_ready,
        data={},
    )
    await notice_outbox.enqueue(
        session,
        [notice_outbox.row(user.id, guild.id, NotificationType.export_ready, {})],
    )
    old_data = {"guild_id": guild.id, "guild_name": None, "source": "guild"}
    await _sql(
        session,
        text("UPDATE public.notifications SET type = 'guild_welcome', data = :d"),
        {"d": json.dumps({"guild_id": guild.id, "guild_name": "Acme"})},
    )
    await _sql(
        session,
        text(
            "UPDATE public.notice_outbox SET type = 'export_ready', "
            "data = CAST(:d AS jsonb), push_data = CAST(:p AS jsonb)"
        ),
        {"d": json.dumps(old_data), "p": json.dumps({"guild_id": str(guild.id)})},
    )
    await session.commit()

    migration = _load("20261003_0445_stored_values_say_community.py")
    old = await _stored(session, schema, job.id)

    def upgrade(sync_session) -> None:
        bind = sync_session.connection()
        migration._public(
            bind,
            migration.NOTIFICATION_TYPES,
            migration.PAYLOAD_KEYS,
            ("guild", "community"),
            {"guild": "community"},
        )
        bind.execute(
            text("SELECT set_config('search_path', :sp, true)"),
            {"sp": f"{schema}, public"},
        )
        migration._guild(bind, {"guild": "community"}, {"guild": "community"})

    await session.run_sync(upgrade)
    await session.commit()
    assert await _stored(session, schema, job.id) == {
        "notification": (
            "community_welcome",
            {"community_id": guild.id, "community_name": "Acme"},
        ),
        "outbox": (
            "export_ready",
            {"community_id": guild.id, "community_name": None, "source": "community"},
            {"community_id": str(guild.id)},
        ),
        "source": "community",
    }

    def downgrade(sync_session) -> None:
        bind = sync_session.connection()
        bind.execute(
            text("SELECT set_config('search_path', :sp, true)"),
            {"sp": f"{schema}, public"},
        )
        migration._guild(bind, {"community": "guild"}, {"community": "guild"})
        migration._public(
            bind,
            {new: o for o, new in migration.NOTIFICATION_TYPES.items()},
            {new: o for o, new in migration.PAYLOAD_KEYS.items()},
            ("community", "guild"),
            {"community": "guild"},
        )

    await session.run_sync(downgrade)
    await session.commit()
    assert await _stored(session, schema, job.id) == old


_OLD_DEFINITION = {
    "plugin_kind": "service",
    "service": {
        "public_id": "tests.plugin-service",
        "protocol": 1,
        "scopes": ["documents:read", "guild:admin"],
    },
    "embeds": [
        {"id": "board", "path": "/b", "scopes": ["guild", "initiative"]},
        {"id": "inside", "path": "/i", "scopes": ["initiative"]},
        {"id": "legacy", "path": "/l"},
    ],
    "guild_summary": "app.tests.plugin-service.summary",
}


async def _plugin_contract(session, schema: str, listing_id: int, registration_id: int):
    install = (
        await _sql(
            session,
            text(f'SELECT definition, granted_scopes FROM "{schema}".guild_plugins'),
        )
    ).one()
    listed = await _scalar(
        session,
        text(
            "SELECT definition FROM public.marketplace_listing_versions "
            "WHERE listing_id = :id"
        ),
        {"id": listing_id},
    )
    ceiling = await _scalar(
        session,
        text(
            "SELECT scope_ceiling FROM public.plugin_service_registrations WHERE id = :id"
        ),
        {"id": registration_id},
    )
    return {
        "installed": install.definition,
        "granted": install.granted_scopes,
        "listed": listed,
        "ceiling": ceiling,
    }


async def test_plugin_contract_says_community_and_back(session) -> None:
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    schema = f"guild_{guild.id}"
    await create_guild_plugin(session, guild, user, definition=_OLD_DEFINITION)
    listing = await create_marketplace_listing(session)
    registration = await create_plugin_service_registration(
        session, scope_ceiling=["documents:read", "guild:admin"]
    )
    migration = _load("20261003_0446_app_contract_says_community.py")

    def route(bind) -> None:
        bind.execute(
            text("SELECT set_config('search_path', :sp, true)"),
            {"sp": f"{schema}, public"},
        )

    def seed(sync_session) -> None:
        bind = sync_session.connection()
        bind.execute(
            text(
                "UPDATE public.marketplace_listing_versions "
                "SET definition = CAST(:d AS jsonb) WHERE listing_id = :id"
            ),
            {"d": json.dumps(_OLD_DEFINITION), "id": listing.id},
        )
        route(bind)
        migration._unforced(
            bind,
            ("guild_plugins",),
            lambda: bind.execute(
                text("UPDATE guild_plugins SET granted_scopes = :g"),
                {"g": ["documents:read", "guild:admin"]},
            ),
        )

    await session.run_sync(seed)
    await session.commit()
    old = await _plugin_contract(session, schema, listing.id, registration.id)
    assert old["granted"] == ["documents:read", "guild:admin"]

    def run(names):
        def apply(sync_session) -> None:
            bind = sync_session.connection()
            migration._public(bind, names)
            route(bind)
            migration._guild(bind, names)

        return apply

    await session.run_sync(run(migration.FORWARD))
    await session.commit()
    definition = {
        "plugin_kind": "service",
        "service": {
            "public_id": "tests.plugin-service",
            "protocol": 1,
            "scopes": ["documents:read", "community:admin"],
        },
        "embeds": [
            {"id": "board", "path": "/b", "scopes": ["community", "initiative"]},
            {"id": "inside", "path": "/i", "scopes": ["initiative"]},
            {"id": "legacy", "path": "/l"},
        ],
        "community_summary": "app.tests.plugin-service.summary",
    }
    assert await _plugin_contract(session, schema, listing.id, registration.id) == {
        "installed": definition,
        "granted": ["documents:read", "community:admin"],
        "listed": definition,
        "ceiling": ["documents:read", "community:admin"],
    }

    await session.run_sync(run(migration.BACKWARD))
    await session.commit()
    assert await _plugin_contract(session, schema, listing.id, registration.id) == old


_PREFERENCES = {
    "my-tasks:focus": {
        "open": True,
        "pins": [{"guild_id": 3, "task_id": 4}, {"guild_id": None, "task_id": 5}, "x"],
    },
    "initiative-my-tasks-filters": {"statusFilters": ["todo"], "guildFilters": [3]},
    "initiative-my-calendar-prefs": {"calendarViewMode": "week", "guildFilters": []},
    "project:1:view-filters": {"guildFilters": [3]},
}


async def _view_state(session, user_id: int) -> dict:
    rows = (
        await _sql(
            session,
            text(
                "SELECT scope_key, value FROM public.user_view_preferences "
                "WHERE user_id = :u"
            ),
            {"u": user_id},
        )
    ).all()
    notification = await _scalar(session, text("SELECT data FROM public.notifications"))
    queued = await _scalar(session, text("SELECT data FROM public.notice_outbox"))
    return {
        "preferences": {row.scope_key: row.value for row in rows},
        "links": (notification["smart_link"], queued["smart_link"]),
    }


async def test_view_preferences_say_community_and_back(session) -> None:
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    for scope, value in _PREFERENCES.items():
        await _sql(
            session,
            text(
                "INSERT INTO public.user_view_preferences (user_id, scope_key, value) "
                "VALUES (:u, :s, CAST(:v AS json))"
            ),
            {"u": user.id, "s": scope, "v": json.dumps(value)},
        )
    await user_notifications.create_notification(
        session,
        user_id=user.id,
        notification_type=NotificationType.export_ready,
        data={},
    )
    await notice_outbox.enqueue(
        session,
        [notice_outbox.row(user.id, guild.id, NotificationType.export_ready, {})],
    )
    link = {"smart_link": "https://app.example/navigate?guild_id=3&target=%2Fi"}
    await _sql(
        session,
        text("UPDATE public.notifications SET data = :d"),
        {"d": json.dumps(link)},
    )
    await _sql(
        session,
        text("UPDATE public.notice_outbox SET data = CAST(:d AS jsonb)"),
        {"d": json.dumps(link)},
    )
    await session.commit()
    migration = _load("20261003_0448_view_preferences_say_community.py")
    old = await _view_state(session, user.id)

    def run(names):
        return lambda sync_session: migration._rewrite(sync_session.connection(), names)

    await session.run_sync(run(migration.FORWARD))
    await session.commit()
    new_link = "https://app.example/navigate?community_id=3&target=%2Fi"
    assert await _view_state(session, user.id) == {
        "preferences": {
            "my-tasks:focus": {
                "open": True,
                "pins": [
                    {"community_id": 3, "task_id": 4},
                    {"community_id": None, "task_id": 5},
                    "x",
                ],
            },
            "initiative-my-tasks-filters": {
                "statusFilters": ["todo"],
                "communityFilters": [3],
            },
            "initiative-my-calendar-prefs": {
                "calendarViewMode": "week",
                "communityFilters": [],
            },
            "project:1:view-filters": {"guildFilters": [3]},
        },
        "links": (new_link, new_link),
    }

    await session.run_sync(run(migration.BACKWARD))
    await session.commit()
    assert await _view_state(session, user.id) == old
