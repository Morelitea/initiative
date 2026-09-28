"""Migration 20260928_0414 places every existing upload in the initiative
whose content shows it. Loaded by path and run on a guild the test builds, the
way ``role_permission_backfill_migration_test`` runs its revision."""

from __future__ import annotations

import importlib.util
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType

from sqlmodel import select

from app.core.config import settings
from app.models.tenant.task import Task
from app.models.tenant.upload import Upload
from app.services.storage import get_guild_storage
from app.testing import (
    create_calendar,
    create_calendar_event,
    create_document,
    create_guild,
    create_initiative,
    create_project,
    create_task,
    create_upload,
    create_user,
)
from app.testing.schema_harness import route_session_to_guild

_MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "20260928_0414_an_upload_belongs_to_an_initiative.py"
)


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(_MIGRATION.stem, _MIGRATION)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def test_the_backfill_places_copies_and_leaves_alone(
    session, tmp_path, monkeypatch
) -> None:
    """Shown in one initiative: kept there. Shown in several: the oldest
    showing row's initiative keeps it and each other initiative gets one copy
    that all its rows show. Shown only by the guild's own calendar: kept for
    the guild. Shown by nothing: left unclaimed, and not deleted."""
    monkeypatch.setattr(settings, "UPLOADS_DIR", str(tmp_path / "uploads"))
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    first = await create_initiative(session, guild, user)
    second = await create_initiative(session, guild, user)
    project = await create_project(session, second, user)
    for name in ("one.png", "shared.png", "guild.png"):
        await create_upload(session, guild, user, filename=name)
    await create_upload(
        session,
        guild,
        user,
        filename="nothing.png",
        claimed_at=datetime.now(timezone.utc),
    )
    get_guild_storage(guild.id).write("shared.png", b"shared")

    def shows(name: str) -> str:
        return f"![shot](/uploads/{guild.id}/{name})"

    await create_document(
        session, first, user, featured_image_url=f"/uploads/{guild.id}/shared.png"
    )
    once = await create_task(session, project, description=shows("one.png"))
    tasks = [
        await create_task(session, project, description=shows("shared.png"))
        for _ in range(2)
    ]
    calendar = await create_calendar(session, first, user, initiative_id=None)
    await create_calendar_event(session, calendar, user, description=shows("guild.png"))

    schema = f"guild_{guild.id}"
    await session.run_sync(lambda s: _load()._place(s.connection(), schema))
    await session.commit()

    await route_session_to_guild(session, guild.id)
    kept = {
        u.filename: (u.initiative_id, u.claimed_at is not None)
        for u in await session.exec(
            select(Upload).execution_options(populate_existing=True)
        )
    }
    [copy] = set(kept) - {"one.png", "shared.png", "guild.png", "nothing.png"}
    assert kept == {
        "one.png": (second.id, True),
        "shared.png": (first.id, True),
        copy: (second.id, True),
        "guild.png": (None, True),
        "nothing.png": (None, False),
    }
    descriptions = await session.exec(
        select(Task.description)
        .where(Task.id.in_([once.id, *(t.id for t in tasks)]))
        .execution_options(populate_existing=True)
    )
    assert sorted(descriptions.all()) == sorted(
        [shows("one.png"), shows(copy), shows(copy)]
    )
    assert get_guild_storage(guild.id).exists(copy)
