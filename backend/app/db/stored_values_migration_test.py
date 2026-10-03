"""Migration 20261003_0445 renames the stored guild values to community and
back. Loaded by path and run on rows an older release would have written, the
way ``upload_initiative_backfill_test`` runs its revision."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

from sqlalchemy import text

from app.models.platform.notification import NotificationType
from app.services.platform import notice_outbox, user_notifications
from app.testing import create_export_job, create_guild, create_user

_MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "20261003_0445_stored_values_say_community.py"
)


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(_MIGRATION.stem, _MIGRATION)
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

    migration = _load()
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
