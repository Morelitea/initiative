"""The event vocabulary a subscription may name, derived not listed.

A subscription says which events it wants (``tasks.updated``) and optionally
which columns it cares about (``status_id``). Both are checked here so a typo is
a 400 at registration rather than a target that silently never fires — the
failure that started this whole line of work.

Nothing is enumerated by hand. Resources are the evented tables, actions are
what the capture trigger emits, and the field vocabulary comes from the mapped
columns plus the facet labels junctions report under. A new content table
therefore becomes subscribable the moment it joins the registry, with no edit
here.
"""

from __future__ import annotations

from functools import lru_cache

from sqlmodel import SQLModel

from app.db.event_capture import (
    HOUSEKEEPING_COLUMNS,
    HOUSEKEEPING_SUFFIXES,
    build_specs,
)

#: What the capture trigger emits. A soft delete arrives as ``deleted`` and a
#: restore as ``created``, so this is the whole vocabulary.
ACTIONS: tuple[str, ...] = ("created", "updated", "deleted")


@lru_cache(maxsize=1)
def _vocabulary() -> dict[str, frozenset[str]]:
    """Resource -> the field names events for it can report.

    A resource's own columns, minus the housekeeping ones the trigger already
    excludes, plus the facet label of every junction that reports against it —
    a row in ``task_tags`` arrives as ``tasks.updated`` with ``changed:
    ['tags']``, so ``tags`` has to be nameable even though no such column
    exists.
    """
    fields: dict[str, set[str]] = {}
    for spec in build_specs():
        bucket = fields.setdefault(spec.resource_type, set())
        if spec.facet is not None:
            bucket.add(spec.facet)
            continue
        table = SQLModel.metadata.tables[spec.table]
        bucket.update(
            column.name
            for column in table.columns
            if column.name not in HOUSEKEEPING_COLUMNS
            and not column.name.endswith(HOUSEKEEPING_SUFFIXES)
        )
    return {resource: frozenset(names) for resource, names in fields.items()}


def resources() -> frozenset[str]:
    return frozenset(_vocabulary())


def event_types() -> frozenset[str]:
    """Every ``resource.action`` a subscription may name."""
    return frozenset(
        f"{resource}.{action}" for resource in _vocabulary() for action in ACTIONS
    )


def fields_for(resource: str) -> frozenset[str]:
    return _vocabulary().get(resource, frozenset())


def unknown_event_types(candidates: list[str]) -> list[str]:
    known = event_types()
    return sorted({name for name in candidates if name not in known})


def unknown_fields(candidates: list[str], event_types_named: list[str]) -> list[str]:
    """Field names none of the named events could ever report.

    Checked against the union across the subscription's resources rather than
    per event, so a subscription watching both tasks and documents may name a
    field belonging to either.
    """
    allowed: set[str] = set()
    for event_type in event_types_named:
        resource, _, _action = event_type.rpartition(".")
        allowed |= fields_for(resource)
    return sorted({name for name in candidates if name not in allowed})
