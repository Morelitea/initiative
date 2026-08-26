"""Seeding, slugs, defaults, and cloning for project filter presets."""

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.tenant import filter_presets as filter_presets_service
from app.testing.factories import (
    create_guild,
    create_initiative,
    create_project,
    create_task_status,
    create_user,
)

pytestmark = [pytest.mark.integration, pytest.mark.service]


async def _project(session: AsyncSession):
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    initiative = await create_initiative(session, guild, user)
    return await create_project(session, initiative, user)


async def test_seeds_the_four_defaults(session: AsyncSession):
    project = await _project(session)

    presets = await filter_presets_service.ensure_default_presets(session, project.id)

    assert [p.slug for p in presets] == ["all", "incomplete", "unassigned", "mine"]
    assert [p.position for p in presets] == [0, 1, 2, 3]
    assert [p.name for p in presets] == ["All", "Incomplete", "Unassigned", "Mine"]


async def test_seeding_is_idempotent(session: AsyncSession):
    project = await _project(session)

    await filter_presets_service.ensure_default_presets(session, project.id)
    again = await filter_presets_service.ensure_default_presets(session, project.id)

    assert len(again) == 4


async def test_all_is_the_default_so_behaviour_is_unchanged(session: AsyncSession):
    project = await _project(session)
    await filter_presets_service.ensure_default_presets(session, project.id)

    default = await filter_presets_service.get_default_preset(session, project.id)

    assert default is not None
    assert default.slug == "all"
    assert default.filters == {}


async def test_incomplete_filters_on_categories_not_status_ids(session: AsyncSession):
    """Status ids are per-project rows; a preset carrying them would not
    survive being shared, duplicated, or copied from a template."""
    project = await _project(session)
    presets = await filter_presets_service.ensure_default_presets(session, project.id)

    incomplete = next(p for p in presets if p.slug == "incomplete")

    assert incomplete.filters == {
        "status_categories": ["backlog", "todo", "in_progress"]
    }
    assert "status_ids" not in incomplete.filters


async def test_mine_and_unassigned_use_portable_tokens(session: AsyncSession):
    project = await _project(session)
    presets = await filter_presets_service.ensure_default_presets(session, project.id)
    by_slug = {p.slug: p for p in presets}

    assert by_slug["mine"].filters == {"assignees": ["me"]}
    assert by_slug["unassigned"].filters == {"assignees": ["none"]}


async def test_slugify_unique_suffixes_on_collision(session: AsyncSession):
    project = await _project(session)
    await filter_presets_service.ensure_default_presets(session, project.id)

    assert (
        await filter_presets_service.slugify_unique(session, project.id, "My Sprint")
        == "my-sprint"
    )
    # A user preset must not steal a seeded preset's slug — links already point
    # at it.
    assert (
        await filter_presets_service.slugify_unique(session, project.id, "Mine")
        == "mine-2"
    )


async def test_normalize_defaults_promotes_when_the_default_is_demoted(
    session: AsyncSession,
):
    project = await _project(session)
    presets = await filter_presets_service.ensure_default_presets(session, project.id)
    await session.commit()
    all_preset = next(p for p in presets if p.slug == "all")

    chosen = await filter_presets_service.normalize_defaults(
        session, project.id, demote_id=all_preset.id
    )
    await session.commit()

    assert chosen != all_preset.id
    survivors = await filter_presets_service.list_presets(session, project.id)
    assert sum(1 for p in survivors if p.is_default) == 1


async def test_normalize_defaults_prefers_the_named_preset(session: AsyncSession):
    project = await _project(session)
    presets = await filter_presets_service.ensure_default_presets(session, project.id)
    await session.commit()
    mine = next(p for p in presets if p.slug == "mine")

    await filter_presets_service.normalize_defaults(
        session, project.id, prefer_id=mine.id
    )
    await session.commit()

    survivors = await filter_presets_service.list_presets(session, project.id)
    assert [p.slug for p in survivors if p.is_default] == ["mine"]


def test_remap_filters_translates_status_ids_and_drops_unmapped():
    remapped = filter_presets_service.remap_filters(
        {"status_ids": [1, 2, 99]},
        status_mapping={1: 10, 2: 20},
    )

    assert remapped["status_ids"] == [10, 20]


def test_remap_filters_drops_properties_the_target_does_not_have():
    remapped = filter_presets_service.remap_filters(
        {"properties": [{"property_id": 5, "op": "eq", "value": "x"}]},
        status_mapping={},
        allowed_property_ids={7},
    )

    assert remapped["properties"] == []


async def test_clone_presets_copies_rows_and_remaps_status_ids(session: AsyncSession):
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    initiative = await create_initiative(session, guild, user)
    source = await create_project(session, initiative, user, name="Source")
    target = await create_project(session, initiative, user, name="Target")

    source_status = await create_task_status(session, project=source, name="Review")
    target_status = await create_task_status(session, project=target, name="Review")

    presets = await filter_presets_service.ensure_default_presets(session, source.id)
    mine = next(p for p in presets if p.slug == "mine")
    mine.filters = {"status_ids": [source_status.id], "assignees": ["me"]}
    session.add(mine)
    await session.commit()

    await filter_presets_service.clone_presets(
        session,
        source_project_id=source.id,
        target_project_id=target.id,
        status_mapping={source_status.id: target_status.id},
    )
    await session.commit()

    cloned = await filter_presets_service.list_presets(session, target.id)
    by_slug = {p.slug: p for p in cloned}
    assert set(by_slug) == {"all", "incomplete", "unassigned", "mine"}
    assert by_slug["mine"].filters["status_ids"] == [target_status.id]
    assert by_slug["all"].is_default is True
