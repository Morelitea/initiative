"""Todoist's CSV export → this app's project envelope.

Pure: it takes the text of an export and returns the document an ordinary
import already applies. Nothing here talks to Todoist, and nothing on the
apply path knows Todoist exists.

**How the file is shaped.** One row per thing, discriminated by ``TYPE``:

``meta``
    The project's own settings (``view_style=board`` and the like). Skipped.
``section``
    A column. Everything after it belongs to it until the next one, so
    sections become the project's statuses and the rows between them are
    placed by position in the file rather than by any field.
``task``
    A task at ``INDENT`` 1. Deeper indents are that task's checklist —
    Todoist nests tasks arbitrarily, this app nests them once, so every
    descendant lands on the nearest top-level task's list.
``note``
    A comment on the row above it. Todoist writes no id anywhere in this
    file, so "the row above" is the only association there is.

**One thing the file cannot give us.** Todoist omits completed tasks from a
CSV export, so an imported project is the work still outstanding. Nothing
here can recover the rest, and the wizard says so before the upload.
"""

from __future__ import annotations

import csv
import io
from typing import Any, Optional

from app.models.tenant.task import TaskPriority
from app.services.import_engine.mapping import (
    DEFAULT_TAG_COLOR,
    POSITION_STEP,
    MappedProject,
    SourceOption,
    build_envelope,
    iso_from_date,
    statuses_from_names,
)

#: Todoist counts down — 1 is the urgent one — which is the opposite of how
#: it reads, and the reason this is a table rather than arithmetic.
PRIORITY_BY_TODOIST: dict[int, TaskPriority] = {
    1: TaskPriority.urgent,
    2: TaskPriority.high,
    3: TaskPriority.medium,
    4: TaskPriority.low,
}

#: What a section-less file calls its one column.
UNSECTIONED = "Tasks"

#: A Todoist export names one project and does not say which, so the whole
#: file is the only selection there is.
SINGLE_KEY = "todoist"


def _rows(content: str) -> list[dict[str, str]]:
    """Every row of the export, however the file was written out.

    A BOM survives a round trip through a spreadsheet, and so does a
    semicolon delimiter in the locales where that is what a spreadsheet
    writes; both are read here rather than refused.
    """
    text = content.lstrip("﻿")
    if not text.strip():
        return []
    sample = text[:4096]
    delimiter = ","
    try:
        delimiter = csv.Sniffer().sniff(sample, delimiters=",;\t").delimiter
    except csv.Error:
        pass
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    return [
        {(key or "").strip().upper(): (value or "") for key, value in row.items()}
        for row in reader
    ]


def _cell(row: dict[str, str], name: str) -> str:
    return (row.get(name) or "").strip()


def _int(value: str, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _person(raw: str) -> str:
    """Todoist writes a person as ``name (12345)``; the name is the part that
    means anything anywhere else."""
    name = raw.strip()
    if name.endswith(")") and "(" in name:
        name = name[: name.rindex("(")].strip()
    return name


def preview(content: str) -> list[SourceOption]:
    """What the file holds: one project, and how much of it.

    Todoist exports a project at a time and writes its name nowhere in the
    file, so there is nothing to choose between — the count is the whole
    point of showing this step at all.
    """
    tasks = sum(
        1
        for row in _rows(content)
        if _cell(row, "TYPE").lower() == "task"
        and _cell(row, "CONTENT")
        and _int(_cell(row, "INDENT"), 1) == 1
    )
    return [SourceOption(key=SINGLE_KEY, name="Todoist project", task_count=tasks)]


def build_project_envelope(
    content: str,
    *,
    selection: str,
    app_version: str,
) -> MappedProject:
    """The whole export as the envelope an ordinary import applies.

    ``selection`` is the name to give the project. Todoist writes the
    project's own name nowhere in the file, so unlike the other sources there
    is nothing to pick between — what the wizard collects is a name.
    """
    rows = _rows(content)
    section_names: list[str] = []
    current_section: Optional[str] = None
    tasks: list[dict[str, Any]] = []
    last_task: Optional[dict[str, Any]] = None
    skipped = 0

    for row in rows:
        kind = _cell(row, "TYPE").lower()
        if kind == "meta" or not kind:
            continue
        if kind == "section":
            heading = _cell(row, "CONTENT")
            if heading:
                current_section = heading
                if heading not in section_names:
                    section_names.append(heading)
            continue
        if kind == "note":
            body = _cell(row, "CONTENT")
            if body and last_task is not None:
                last_task["comments"].append(
                    {
                        "author_name": _person(_cell(row, "AUTHOR")) or None,
                        "body": body,
                    }
                )
            elif body:
                skipped += 1
            continue
        if kind != "task":
            continue

        title = _cell(row, "CONTENT")
        if not title:
            skipped += 1
            continue

        if _int(_cell(row, "INDENT"), 1) > 1:
            if last_task is None:
                skipped += 1
                continue
            last_task["checklist"].append({"text": title, "done": False})
            continue

        # Todoist's two dates mean different things: DATE is when the work is
        # scheduled, DEADLINE is when it is actually due. With both, they map
        # to the two fields they describe; with only one, it is the due date,
        # because that is what a lone Todoist date means to the person who
        # set it.
        scheduled = iso_from_date(_cell(row, "DATE"))
        deadline = iso_from_date(_cell(row, "DEADLINE"))
        due = deadline or scheduled
        start = scheduled if deadline else None

        task: dict[str, Any] = {
            "title": title,
            "description": _cell(row, "DESCRIPTION") or None,
            "status_name": current_section or UNSECTIONED,
            "priority": PRIORITY_BY_TODOIST.get(
                _int(_cell(row, "PRIORITY"), 4), TaskPriority.low
            ).value,
            "position": (len(tasks) + 1) * POSITION_STEP,
            "tags": [],
            "assignee_handles": [],
            "checklist": [],
            "property_values": [],
            "links": [],
            "comments": [],
        }
        if due:
            task["due_date"] = due
        if start:
            task["start_date"] = start
        assignee = _person(_cell(row, "RESPONSIBLE"))
        if assignee:
            task["assignee_handles"] = [assignee]
        tasks.append(task)
        last_task = task

    # Tasks that appeared before any section need a column of their own, and
    # it has to come first because that is where they are in the file.
    if any(task["status_name"] == UNSECTIONED for task in tasks):
        section_names.insert(0, UNSECTIONED)

    statuses = statuses_from_names(section_names)
    known = {status["name"] for status in statuses}
    default_name = next(
        (status["name"] for status in statuses if status["is_default"]),
        statuses[0]["name"],
    )
    for task in tasks:
        if task["status_name"] not in known:
            task["status_name"] = default_name

    warnings: list[str] = []
    if tasks:
        warnings.append("TODOIST_EXPORT_OMITS_COMPLETED")

    return MappedProject(
        envelope=build_envelope(
            name=selection or "Todoist import",
            description=None,
            statuses=statuses,
            tasks=tasks,
            app_version=app_version,
            source_url="https://todoist.com",
        ),
        skipped_rows=skipped,
        warnings=warnings,
    )


__all__ = [
    "DEFAULT_TAG_COLOR",
    "SINGLE_KEY",
    "build_project_envelope",
    "preview",
]
