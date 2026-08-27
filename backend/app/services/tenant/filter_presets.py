"""Project filter presets — seeding, slugs, ordering, and cloning.

Mirrors ``task_statuses`` deliberately: presets are the same shape of thing —
a small, ordered, project-owned list with exactly one default — so they follow
the same lifecycle. In particular ``ensure_default_presets`` is idempotent and
called from every project-creating path, never from a read.
"""

from __future__ import annotations

import re
from typing import Any, Iterable, Sequence

from sqlmodel import delete, select, update
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.tenant.filter_preset import ProjectFilterPreset

# The four presets every project starts with. "All" is the default so a project
# that has never been configured behaves exactly as it did before presets
# existed. Note that "Incomplete" filters on status *categories*, never status
# ids: ids are per-project rows, so an id-based preset would not survive being
# shared, duplicated, or copied from a template.
DEFAULT_FILTER_PRESETS: Sequence[dict[str, Any]] = (
    {
        "slug": "all",
        "name": "All",
        "position": 0,
        "is_default": True,
        "filters": {},
    },
    {
        "slug": "incomplete",
        "name": "Incomplete",
        "position": 1,
        "is_default": False,
        "filters": {"status_categories": ["backlog", "todo", "in_progress"]},
    },
    {
        "slug": "unassigned",
        "name": "Unassigned",
        "position": 2,
        "is_default": False,
        "filters": {"assignees": ["none"]},
    },
    {
        "slug": "mine",
        "name": "Mine",
        "position": 3,
        "is_default": False,
        "filters": {"assignees": ["me"]},
    },
)

RESERVED_SLUGS = frozenset(preset["slug"] for preset in DEFAULT_FILTER_PRESETS)

MAX_PRESETS_PER_PROJECT = 30
MAX_SLUG_LENGTH = 64


def _sorted(presets: Iterable[ProjectFilterPreset]) -> list[ProjectFilterPreset]:
    return sorted(presets, key=lambda preset: (preset.position, preset.id or 0))


async def list_presets(
    session: AsyncSession, project_id: int
) -> Sequence[ProjectFilterPreset]:
    stmt = (
        select(ProjectFilterPreset)
        .where(ProjectFilterPreset.project_id == project_id)
        .order_by(ProjectFilterPreset.position.asc(), ProjectFilterPreset.id.asc())
    )
    result = await session.exec(stmt)
    return result.all()


async def ensure_default_presets(
    session: AsyncSession, project_id: int
) -> list[ProjectFilterPreset]:
    """Seed the four defaults, once. Safe to call from any write path."""
    existing = await list_presets(session, project_id)
    if existing:
        return _sorted(existing)

    created: list[ProjectFilterPreset] = []
    for payload in DEFAULT_FILTER_PRESETS:
        preset = ProjectFilterPreset(project_id=project_id, **payload)
        session.add(preset)
        created.append(preset)
    await session.flush()
    return _sorted(created)


async def get_default_preset(
    session: AsyncSession, project_id: int
) -> ProjectFilterPreset | None:
    presets = _sorted(await list_presets(session, project_id))
    for preset in presets:
        if preset.is_default:
            return preset
    return presets[0] if presets else None


def slugify(name: str) -> str:
    """Kebab-case a preset name down to the slug alphabet."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return slug[:MAX_SLUG_LENGTH].strip("-")


async def slugify_unique(session: AsyncSession, project_id: int, name: str) -> str:
    """A slug free on this project, suffixing ``-2``, ``-3``, … on collision.

    A user preset named "Mine" becomes ``mine-2`` when the seeded ``mine`` is
    still around, so a default preset's link never silently retargets.
    """
    base = slugify(name) or "preset"
    presets = await list_presets(session, project_id)
    taken = {preset.slug for preset in presets}
    if base not in taken:
        return base
    for suffix in range(2, MAX_PRESETS_PER_PROJECT + 3):
        trimmed = base[: MAX_SLUG_LENGTH - len(str(suffix)) - 1].strip("-") or "preset"
        candidate = f"{trimmed}-{suffix}"
        if candidate not in taken:
            return candidate
    raise ValueError("could not derive a unique preset slug")


async def normalize_defaults(
    session: AsyncSession,
    project_id: int,
    *,
    prefer_id: int | None = None,
    demote_id: int | None = None,
) -> int | None:
    """Leave the project with exactly one default preset.

    ``prefer_id`` becomes the default; ``demote_id`` gives up being it. With
    neither, an existing default is kept and, failing that, the lowest-position
    preset is promoted so a project is never left without one.

    Two statements rather than assigning ``is_default`` on the rows: the
    at-most-one-default index is partial, so Postgres checks it per row, and
    the outgoing default has to be lowered before the incoming one is raised.
    Callers therefore leave ``is_default`` alone and let this decide.
    """
    presets = _sorted(list(await list_presets(session, project_id)))
    if not presets:
        return None

    chosen: int | None = None
    if prefer_id is not None and any(preset.id == prefer_id for preset in presets):
        chosen = prefer_id
    else:
        held = [
            preset for preset in presets if preset.is_default and preset.id != demote_id
        ]
        if held:
            chosen = held[0].id
        else:
            fallback = [preset for preset in presets if preset.id != demote_id]
            chosen = fallback[0].id if fallback else None

    await session.exec(
        update(ProjectFilterPreset)
        .where(
            ProjectFilterPreset.project_id == project_id,
            ProjectFilterPreset.id != chosen,
            ProjectFilterPreset.is_default.is_(True),
        )
        .values(is_default=False)
    )
    await session.flush()
    if chosen is not None:
        await session.exec(
            update(ProjectFilterPreset)
            .where(
                ProjectFilterPreset.id == chosen,
                ProjectFilterPreset.is_default.is_(False),
            )
            .values(is_default=True)
        )
        await session.flush()
    return chosen


def resequence(presets: list[ProjectFilterPreset]) -> None:
    for index, preset in enumerate(presets):
        preset.position = index


def remap_filters(
    filters: dict[str, Any],
    *,
    status_mapping: dict[int, int],
    allowed_property_ids: set[int] | None = None,
) -> dict[str, Any]:
    """Rewrite a spec for a different project.

    Status ids are per-project rows, so they are translated through the clone's
    mapping and dropped when the source status has no counterpart. Property
    filters are dropped when the target initiative has no such definition.
    """
    remapped = dict(filters)

    status_ids = remapped.get("status_ids")
    if isinstance(status_ids, list):
        remapped["status_ids"] = [
            status_mapping[old]
            for old in status_ids
            if isinstance(old, int) and old in status_mapping
        ]

    properties = remapped.get("properties")
    if isinstance(properties, list) and allowed_property_ids is not None:
        remapped["properties"] = [
            entry
            for entry in properties
            if isinstance(entry, dict)
            and entry.get("property_id") in allowed_property_ids
        ]

    return remapped


async def clone_presets(
    session: AsyncSession,
    *,
    source_project_id: int,
    target_project_id: int,
    status_mapping: dict[int, int] | None = None,
    allowed_property_ids: set[int] | None = None,
) -> None:
    stmt = (
        select(ProjectFilterPreset)
        .where(ProjectFilterPreset.project_id == source_project_id)
        .order_by(ProjectFilterPreset.position.asc(), ProjectFilterPreset.id.asc())
    )
    result = await session.exec(stmt)
    source_presets = result.all()
    if not source_presets:
        return

    await session.exec(
        delete(ProjectFilterPreset).where(
            ProjectFilterPreset.project_id == target_project_id
        )
    )
    await session.flush()

    for source in source_presets:
        session.add(
            ProjectFilterPreset(
                project_id=target_project_id,
                slug=source.slug,
                name=source.name,
                position=source.position,
                is_default=source.is_default,
                filters=remap_filters(
                    source.filters or {},
                    status_mapping=status_mapping or {},
                    allowed_property_ids=allowed_property_ids,
                ),
            )
        )
    await session.flush()
