"""What a tool item becomes when it is shared to the marketplace.

A listing is the tool's export envelope, but not all of an export: what belongs
to the community rather than to the work stays behind. This module is that
difference, applied to every tool listing wherever it arrives from — a member
sharing an item, an operator's file, a registry — because a listing that
carried a person or a link would carry it into every community that installs
it.

What goes:

* **People.** Authors, assignees, attendees, comments and the people a mention
  or a person-type property names. A mention stays as the words it was written
  with, and names nobody.
* **Links to anything outside the item.** A task's link to another task in the
  same project survives; one to anything else is dropped, and a reference in a
  body is reduced to its label.
* **Uploads.** A file in the community's own storage stays there. A picture
  shared with the item travels as the catalogue's own copy
  (``listing_assets``), named by the path the catalogue serves it from; any
  other reference into a community's uploads is dropped.
* **When it happened.** Created, updated and archived times describe the
  original, not the copy.

What changes:

* **Dates become offsets.** Every date an item plans with is moved so that the
  earliest one falls on :data:`DATE_ANCHOR`. Installing moves them again, to
  the start date the installer picks, so a sprint template lands on next
  Monday rather than on the day its publisher happened to plan it.

Everything here is a pure function of the envelope, and applying it twice
changes nothing — the catalog compares a re-published version against what it
stored, so the stored form has to be a fixed point.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import date, datetime, timedelta
from typing import Any

from app.core.tools import Tool, tool_export_source

__all__ = [
    "DATE_ANCHOR",
    "anchor_dates",
    "export_for_listing",
    "shift_dates",
    "strip_for_listing",
]

#: The day a listing's earliest date falls on. A Monday, so a template planned
#: by the week reads naturally before anyone installs it.
DATE_ANCHOR = date(2000, 1, 3)

#: Property types whose value is a person, and whose value therefore stays
#: behind.
_PERSON_PROPERTY_TYPES = frozenset({"user_reference"})

#: Property types whose value is a date the item plans with.
_DATE_PROPERTY_TYPES = frozenset({"date", "datetime"})

#: Editor nodes that name a person.
_MENTION_NODES = frozenset({"mention", "custom-mention"})

#: Editor nodes that name something else in the community by id. A wikilink is
#: not among them: it names a page by title, and a link between two pages of
#: the same wiki is part of the wiki.
_REFERENCE_NODES = frozenset({"entity-mention", "smart-chip"})

#: Editor nodes that carry a picture.
_IMAGE_NODES = frozenset({"image"})


# --- editor bodies ----------------------------------------------------------


def _text_node(text: str, node: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "text",
        "version": 1,
        "text": text,
        "format": node.get("format") or 0,
        "style": "",
        "mode": "normal",
        "detail": 0,
    }


def _mention_text(node: dict[str, Any]) -> str:
    name = str(node.get("mentionName") or node.get("text") or "").lstrip("@")
    return f"@{name}" if name else ""


def _carried(value: Any) -> bool:
    """Whether a reference names a picture the catalogue keeps."""
    from app.services.marketplace.media import digest_of

    return digest_of(value) is not None


def _clean_editor_state(content: Any) -> Any:
    """An editor body with its mentions and references as plain words, and
    every picture the catalogue does not keep gone."""
    if not isinstance(content, dict) or not isinstance(content.get("root"), dict):
        return content

    def walk(node: Any) -> Any:
        if not isinstance(node, dict):
            return node
        kind = node.get("type")
        if kind in _MENTION_NODES:
            return _text_node(_mention_text(node), node)
        if kind in _REFERENCE_NODES:
            return _text_node(str(node.get("text") or ""), node)
        children = node.get("children")
        if isinstance(children, list):
            return {
                **node,
                "children": [
                    walk(child)
                    for child in children
                    if not (
                        isinstance(child, dict)
                        and child.get("type") in _IMAGE_NODES
                        and not _carried(child.get("src"))
                    )
                ],
            }
        return node

    return {**content, "root": walk(content["root"])}


def _clean_markdown(text: Any, handles: list[str]) -> Any:
    """A markdown body with its references reduced to their labels and each
    mention written as the name alone, without the number that picks out one
    account."""
    from app.services.import_engine.references import place_markdown_references

    if not isinstance(text, str) or not text:
        return text
    cleaned = place_markdown_references(text, lambda _ref: None) or ""
    for handle in handles:
        name = handle.split("#", 1)[0]
        cleaned = cleaned.replace(f"@{handle}", f"@{name}")
    return cleaned


def _clean_properties(values: Any) -> list[Any]:
    if not isinstance(values, list):
        return []
    return [
        value
        for value in values
        if not (
            isinstance(value, dict)
            and value.get("property_type") in _PERSON_PROPERTY_TYPES
        )
    ]


# --- per tool ---------------------------------------------------------------


def _strip_project(env: dict[str, Any]) -> None:
    env["exported_by_handle"] = None
    env["exported_at"] = datetime(
        DATE_ANCHOR.year, DATE_ANCHOR.month, DATE_ANCHOR.day
    ).isoformat()
    project = env.get("project")
    if isinstance(project, dict):
        project["archived_at"] = None
        project["description"] = _clean_markdown(project.get("description"), [])
    tasks = [task for task in env.get("tasks") or [] if isinstance(task, dict)]
    internal = {task.get("external_ref") for task in tasks if task.get("external_ref")}
    for task in tasks:
        handles = [
            *(task.get("mention_handles") or []),
            *(task.get("assignee_handles") or []),
        ]
        task["description"] = _clean_markdown(task.get("description"), handles)
        task["assignee_handles"] = []
        task["comments"] = []
        task["mention_handles"] = []
        task["archived_at"] = None
        task["created_at"] = None
        task["updated_at"] = None
        task["property_values"] = _clean_properties(task.get("property_values"))
        task["links"] = [
            link
            for link in task.get("links") or []
            if isinstance(link, dict) and link.get("target_external_ref") in internal
        ]


def _strip_document(env: dict[str, Any]) -> None:
    env["mention_handles"] = []
    env["properties"] = _clean_properties(env.get("properties"))
    content = env.get("content")
    if env.get("document_type") == "native":
        env["content"] = _clean_editor_state(content)


def _strip_post(env: dict[str, Any]) -> None:
    env["mention_handles"] = []
    env["body"] = _clean_editor_state(env.get("body"))


def _strip_wiki(env: dict[str, Any]) -> None:
    for page in env.get("pages") or []:
        if not isinstance(page, dict):
            continue
        page["content"] = _clean_editor_state(page.get("content"))
        page["mention_handles"] = []
        page["comments"] = []
        page["author_handle"] = None
        page["author_name"] = None
        page["created_at"] = None
        page["updated_at"] = None


def _strip_calendar(env: dict[str, Any]) -> None:
    for event in env.get("events") or []:
        if not isinstance(event, dict):
            continue
        event["attendees"] = []
        event["created_at"] = None
        event["properties"] = _clean_properties(event.get("properties"))


def _strip_queue(env: dict[str, Any]) -> None:
    for item in env.get("items") or []:
        if isinstance(item, dict):
            item["member"] = None


def _strip_gallery(env: dict[str, Any]) -> None:
    env["images"] = [
        image
        for image in env.get("images") or []
        if isinstance(image, dict) and _carried(image.get("storage_key"))
    ]
    if not _carried(env.get("cover")):
        env["cover"] = None


def _strip_nothing(env: dict[str, Any]) -> None:
    """A counter group and a dashboard name nobody and point at nothing a
    listing could carry. (A dashboard's configuration, which does, is dropped
    by the dashboard's own canonical form.)"""


_STRIPPERS: dict[Tool, Callable[[dict[str, Any]], None]] = {
    Tool.project: _strip_project,
    Tool.document: _strip_document,
    Tool.queue: _strip_queue,
    Tool.counter_group: _strip_nothing,
    Tool.calendar: _strip_calendar,
    Tool.dashboard: _strip_nothing,
    Tool.post: _strip_post,
    Tool.gallery: _strip_gallery,
    Tool.wiki: _strip_wiki,
}


def strip_for_listing(tool: Tool, envelope: dict[str, Any]) -> dict[str, Any]:
    """``envelope`` with everything that belongs to the community removed.

    Works on a copy; the argument is left as it was.
    """
    import copy

    from app.services.tenant.attachments import (
        extract_upload_urls,
        replace_upload_urls,
    )

    stripped = copy.deepcopy(envelope)
    _STRIPPERS[tool](stripped)
    # Whatever still points into a community's uploads — a whiteboard's
    # picture, a link in a body — points nowhere once it leaves.
    return replace_upload_urls(
        stripped, {url: "" for url in extract_upload_urls(stripped)}
    )


# --- dates ------------------------------------------------------------------


def _property_date_slots(values: Any) -> Iterator[tuple[dict[str, Any], str]]:
    for value in values or []:
        if (
            isinstance(value, dict)
            and value.get("property_type") in _DATE_PROPERTY_TYPES
        ):
            yield value, "value_text"


def _recurrence_slot(owner: dict[str, Any]) -> Iterator[tuple[dict[str, Any], str]]:
    recurrence = owner.get("recurrence")
    if isinstance(recurrence, dict):
        yield recurrence, "end_date"


def _date_slots(tool: Tool, env: dict[str, Any]) -> list[tuple[dict[str, Any], str]]:
    """Every place an item keeps a date it plans with."""
    slots: list[tuple[dict[str, Any], str]] = []
    if tool is Tool.project:
        project = env.get("project")
        if isinstance(project, dict):
            slots += [(project, "start_date"), (project, "end_date")]
        for task in env.get("tasks") or []:
            if isinstance(task, dict):
                slots += [
                    (task, "start_date"),
                    (task, "due_date"),
                    (task, "completed_at"),
                ]
                slots += _recurrence_slot(task)
                slots += _property_date_slots(task.get("property_values"))
    elif tool is Tool.calendar:
        for event in env.get("events") or []:
            if isinstance(event, dict):
                slots += [(event, "start_at"), (event, "end_at")]
                slots += _recurrence_slot(event)
                slots += _property_date_slots(event.get("properties"))
    elif tool is Tool.document:
        slots += _property_date_slots(env.get("properties"))
    return slots


def _parse(value: Any) -> date | datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        if "T" in value or " " in value:
            return datetime.fromisoformat(value)
        return date.fromisoformat(value)
    except ValueError:
        return None


def _day_of(value: date | datetime) -> date:
    return value.date() if isinstance(value, datetime) else value


def shift_dates(tool: Tool, envelope: dict[str, Any], days: int) -> dict[str, Any]:
    """``envelope`` with every planning date moved by ``days``. Works on a
    copy; a value that is not a date is left as it was."""
    import copy

    shifted = copy.deepcopy(envelope)
    if days == 0:
        return shifted
    delta = timedelta(days=days)
    for owner, key in _date_slots(tool, shifted):
        parsed = _parse(owner.get(key))
        if parsed is not None:
            owner[key] = (parsed + delta).isoformat()
    return shifted


def anchor_dates(tool: Tool, envelope: dict[str, Any]) -> dict[str, Any]:
    """``envelope`` with its earliest planning date on :data:`DATE_ANCHOR`,
    and every other date moved with it."""
    days = [
        _day_of(parsed)
        for owner, key in _date_slots(tool, envelope)
        if (parsed := _parse(owner.get(key))) is not None
    ]
    if not days:
        return envelope
    return shift_dates(tool, envelope, (DATE_ANCHOR - min(days)).days)


# --- the export -------------------------------------------------------------


async def export_for_listing(
    session: Any, *, tool: Tool, entity_id: int, user: Any, guild_id: int
) -> dict[str, Any]:
    """One item's export envelope, read the way its exporter reads it.

    The exporter's own fetch is the access check — the member must be able to
    read the item, or, for a project, to write it, exactly as exporting it to
    a file asks — and it runs on the member's session. The caller normalizes
    the result into a listing, which is where :func:`strip_for_listing` and
    :func:`anchor_dates` apply.
    """
    from app.services.export.adapters import ADAPTERS

    adapter = ADAPTERS[tool_export_source(tool)]
    request = await adapter.build(
        session,
        user=user,
        guild_id=guild_id,
        params={f"{tool.value}_id": entity_id},
        format="json",
    )
    return dict(request.batch[0].data)
