"""Migrations 20261003_0445 and 20261003_0446 rename the stored guild values
to community and back. Loaded by path and run on rows an older release would
have written, the way ``upload_initiative_backfill_test`` runs its revision."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

from sqlalchemy import text

from app.models.platform.notification import NotificationType
from app.services.platform import notice_outbox, user_notifications
from app.testing import (
    create_app_service_registration,
    create_export_job,
    create_guild,
    create_guild_app,
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
    "app_kind": "service",
    "service": {
        "public_id": "tests.app-service",
        "protocol": 1,
        "scopes": ["documents:read", "guild:admin"],
    },
    "embeds": [
        {"id": "board", "path": "/b", "scopes": ["guild", "initiative"]},
        {"id": "inside", "path": "/i", "scopes": ["initiative"]},
        {"id": "legacy", "path": "/l"},
    ],
    "guild_summary": "app.tests.app-service.summary",
}


async def _app_contract(session, schema: str, listing_id: int, registration_id: int):
    install = (
        await _sql(
            session,
            text(f'SELECT definition, granted_scopes FROM "{schema}".guild_apps'),
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
            "SELECT scope_ceiling FROM public.app_service_registrations WHERE id = :id"
        ),
        {"id": registration_id},
    )
    return {
        "installed": install.definition,
        "granted": install.granted_scopes,
        "listed": listed,
        "ceiling": ceiling,
    }


async def test_app_contract_says_community_and_back(session) -> None:
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    schema = f"guild_{guild.id}"
    await create_guild_app(session, guild, user, definition=_OLD_DEFINITION)
    listing = await create_marketplace_listing(session)
    registration = await create_app_service_registration(
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
            ("guild_apps",),
            lambda: bind.execute(
                text("UPDATE guild_apps SET granted_scopes = :g"),
                {"g": ["documents:read", "guild:admin"]},
            ),
        )

    await session.run_sync(seed)
    await session.commit()
    old = await _app_contract(session, schema, listing.id, registration.id)
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
        "app_kind": "service",
        "service": {
            "public_id": "tests.app-service",
            "protocol": 1,
            "scopes": ["documents:read", "community:admin"],
        },
        "embeds": [
            {"id": "board", "path": "/b", "scopes": ["community", "initiative"]},
            {"id": "inside", "path": "/i", "scopes": ["initiative"]},
            {"id": "legacy", "path": "/l"},
        ],
        "community_summary": "app.tests.app-service.summary",
    }
    assert await _app_contract(session, schema, listing.id, registration.id) == {
        "installed": definition,
        "granted": ["documents:read", "community:admin"],
        "listed": definition,
        "ceiling": ["documents:read", "community:admin"],
    }

    await session.run_sync(run(migration.BACKWARD))
    await session.commit()
    assert await _app_contract(session, schema, listing.id, registration.id) == old
