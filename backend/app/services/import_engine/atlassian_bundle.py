"""The one zip an Atlassian fetch writes, whichever products it read.

Jira projects become project envelopes, their sprints calendar envelopes,
their images assets; Confluence spaces become wiki envelopes. All of it goes
into one backup-shaped bundle naming the one initiative the person picked, so
the apply is a single restore — and a link between an issue and a page read in
the same fetch has both of its ends in the same job to be joined.
"""

from __future__ import annotations

import io
import json
import zipfile
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Sequence

from app.services.import_engine.common import handle_key
from app.services.import_engine.jira_attachments import StoredImage

_MANIFEST_NAME = "manifest.json"


def _safe(name: str, fallback: str) -> str:
    return "".join(c for c in name if c.isalnum() or c in "-_") or fallback


def merge_people(
    jira: list[dict[str, Any]], confluence: Counter[str]
) -> list[dict[str, Any]]:
    """Everyone either product names, once each.

    The same person is usually in both — they wrote the pages and work the
    issues — and they are asked about once: keyed the way a handle is
    matched, Jira's spelling first, ordered by how much hangs on them.
    """
    seen: dict[str, dict[str, Any]] = {}
    weight: Counter[str] = Counter()
    for person in jira:
        key = handle_key(str(person["handle"]))
        seen.setdefault(key, dict(person))
        weight[key] += 1 + int(person.get("comment_count") or 0)
    for name, count in confluence.items():
        key = handle_key(name)
        seen.setdefault(key, {"handle": name, "name": name, "comment_count": 0})
        weight[key] += count
    return sorted(
        seen.values(),
        key=lambda person: (-weight[handle_key(person["handle"])], person["handle"]),
    )


def write_bundle(
    *,
    projects: Sequence[tuple[str, dict[str, Any]]] = (),
    calendars: Sequence[dict[str, Any]] = (),
    images: Sequence[StoredImage] = (),
    wikis: Sequence[tuple[str, dict[str, Any]]] = (),
    people: list[dict[str, Any]],
    guild_id: int,
    guild_name: str,
    target_initiative_id: int,
    app_version: str,
    site_url: str,
) -> bytes:
    """The zip the applier reads.

    The manifest names **one** initiative and gives it
    ``target_initiative_id`` — the one the person picked — so the applier
    files everything into it rather than creating one named after a site.
    """
    entries: list[dict[str, Any]] = []
    files: dict[str, bytes] = {}

    def add(
        tool: str, envelope_type: str, path: str, title: str, envelope: dict
    ) -> None:
        files[path] = json.dumps(envelope).encode("utf-8")
        entries.append(
            {
                "path": path,
                "tool": tool,
                "type": envelope_type,
                "schema_version": 1,
                "entity_id": len(entries) + 1,
                "title": title,
                "initiative_id": 1,
                "tags": [],
                "properties": [],
                "asset": None,
            }
        )

    for index, (key, envelope) in enumerate(projects, start=1):
        add(
            "project",
            "initiative-project",
            f"initiatives/1-imported/projects/{index}-{_safe(key, 'project')}"
            ".initiative-project.json",
            envelope["project"]["name"],
            envelope,
        )
    for index, calendar in enumerate(calendars, start=1):
        add(
            "calendar",
            "initiative-calendar",
            f"initiatives/1-imported/calendars/{index}-{_safe(calendar['name'], 'sprints')}"
            ".initiative-calendar.json",
            calendar["name"],
            calendar,
        )
    for index, (key, envelope) in enumerate(wikis, start=1):
        add(
            "wiki",
            "initiative-wiki",
            f"initiatives/1-imported/wikis/{index}-{_safe(key, 'space')}"
            ".initiative-wiki.json",
            envelope["name"],
            envelope,
        )

    assets = []
    for image in images:
        path = f"assets/{image.storage_key}"
        files[path] = image.data
        assets.append(
            {
                "path": path,
                "storage_key": image.storage_key,
                "original_filename": image.filename,
                "content_type": image.content_type,
                "size_bytes": len(image.data),
            }
        )

    tools = {
        tool: "included"
        for tool, present in (
            ("project", projects),
            ("calendar", calendars),
            ("wiki", wikis),
        )
        if present
    }
    manifest = {
        "type": "initiative-backup",
        "schema_version": 1,
        "app_version": app_version,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "source_instance_url": site_url,
        "guild": {"id": guild_id, "name": guild_name},
        "include_uploads": bool(assets),
        "initiatives": [
            {
                "id": 1,
                "name": "Imported from Atlassian",
                "tools": tools,
                # Apply into the initiative the person chose. Without this the
                # applier would create one, which is the wrong answer for a
                # fetch: they already said where it goes.
                "target_initiative_id": target_initiative_id,
            }
        ],
        "entries": entries,
        "assets": assets,
        "skipped": [],
        "people": people,
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(_MANIFEST_NAME, json.dumps(manifest))
        for path, blob in files.items():
            archive.writestr(path, blob)
    return buffer.getvalue()
