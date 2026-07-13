"""Queue source adapter: importable backup envelope (json) and turn-order
reports (pdf/csv/xlsx/md).

The json envelope round-trips the queue's own state — items with rotation
order, colors, notes, visibility, and held/current markers, tags by name.
Member assignments and linked documents/tasks ship as display text only
(names and titles): they reference guild-local rows that won't exist wherever
the envelope is imported, so an import can't rebind them.

The report formats list every item in rotation order (position descending,
matching the on-screen timeline) with hidden/held/current flagged in a status
column, so the printout is the full queue, not just the visible rotation.
Markdown renders as a numbered turn-order list rather than a table.

Access rule for every format: READ on the queue (exporting is a formatted
read), enforced by the ``get_queue_for_export`` seam at both count and build
time, under the caller's RLS session.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.messages import ExportMessages
from app.models.platform.user import User
from app.models.tenant.queue import Queue, QueueItem
from app.services.export.contract import RenderItem, RenderRequest
from app.services.export.engine import ExportError
from app.services.platform.csv_export import safe_filename_component

_COLUMNS = (
    {"key": "order", "label": "#"},
    {"key": "title", "label": "Item", "width": "2fr"},
    {"key": "member", "label": "Member", "width": "1fr"},
    {"key": "tags", "label": "Tags", "width": "1fr"},
    {"key": "notes", "label": "Notes", "width": "2fr"},
    {"key": "status", "label": "Status"},
)


class QueueAdapter:
    source = "queue"
    template_id = "data-table"
    formats = frozenset({"json", "pdf", "csv", "xlsx", "md"})

    async def count(
        self,
        session: AsyncSession,
        *,
        user: User,
        guild_id: int,
        params: dict,
        format: str,
    ) -> int:
        queue = await self._queue(session, user, guild_id, params)
        return len(queue.items)

    async def build(
        self,
        session: AsyncSession,
        *,
        user: User,
        guild_id: int,
        params: dict,
        format: str,
    ) -> RenderRequest:
        queue = await self._queue(session, user, guild_id, params)
        items = _rotation_order(queue.items)
        # One clock read: the filename date and the subtitle timestamp must
        # not straddle midnight into disagreeing dates.
        now = datetime.now(timezone.utc)
        date = now.strftime("%Y-%m-%d")
        stem = safe_filename_component(queue.name).lower()
        if format == "json":
            item = RenderItem(
                key=f"{stem}-{date}.initiative-queue",
                data=_envelope(queue, items),
            )
        else:
            item = RenderItem(
                key=f"{stem}-{date}", data=_report_payload(queue, items, user, now)
            )
        return RenderRequest(
            guild_id=guild_id,
            template_id=self.template_id,
            format=format,
            batch=(item,),
        )

    async def _queue(
        self, session: AsyncSession, user: User, guild_id: int, params: dict
    ) -> Queue:
        from app.services.tenant.queues import get_queue_for_export

        return await get_queue_for_export(
            session, user, guild_id, queue_id=_queue_id(params)
        )


def _rotation_order(items: list[QueueItem]) -> list[QueueItem]:
    """Position descending — the rotation's acting order (see
    ``queues.py:_visible_items_desc``), with id as the deterministic
    tiebreaker the timeline also uses."""
    return sorted(items, key=lambda i: (-i.position, i.id or 0))


def _envelope(queue: Queue, items: list[QueueItem]) -> dict[str, Any]:
    return {
        "kind": "initiative-queue",
        "schema_version": 1,
        "name": queue.name,
        "description": queue.description,
        "is_active": queue.is_active,
        "current_round": queue.current_round,
        "items": [
            {
                "label": item.label,
                "position": item.position,
                "color": item.color,
                "notes": item.notes,
                "is_visible": item.is_visible,
                "held_at_round": item.held_at_round,
                "is_current": item.id == queue.current_item_id,
                # Informational only: user/document/task ids are guild-local,
                # so an import can't rebind them — names and titles it is.
                "member": _member(item),
                "tags": _tags(item),
                "documents": sorted(
                    link.document.title
                    for link in item.document_links
                    if link.document is not None
                ),
                "tasks": sorted(
                    link.task.title for link in item.task_links if link.task is not None
                ),
            }
            for item in items
        ],
    }


def _report_payload(
    queue: Queue, items: list[QueueItem], user: User, now: datetime
) -> dict[str, Any]:
    generated_at = now.strftime("%Y-%m-%d %H:%M UTC")
    # Both attribution fields can be absent (some OAuth-provisioned accounts
    # carry neither) — never render the literal "None".
    author = user.full_name or user.email or "unknown"
    round_part = f" · round {queue.current_round}" if queue.is_active else ""
    return {
        "title": queue.name,
        "subtitle": (
            f"{len(items)} item{'s' if len(items) != 1 else ''}{round_part}"
            f" · generated {generated_at} by {author}"
        ),
        "footer": f"{queue.name} — queue export",
        "description": queue.description or "",
        # Markdown renders the rotation as a numbered turn-order list; the
        # other formats consume the columns/rows table.
        "layout": "numbered",
        "columns": [dict(c) for c in _COLUMNS],
        "rows": [_row(queue, item, order) for order, item in enumerate(items, 1)],
    }


def _row(queue: Queue, item: QueueItem, order: int) -> dict[str, Any]:
    flags = []
    if item.id == queue.current_item_id:
        flags.append("Current")
    if item.held_at_round is not None:
        flags.append("Held")
    if not item.is_visible:
        flags.append("Hidden")
    return {
        "order": order,
        "title": item.label,
        "member": _member(item) or "",
        "tags": ", ".join(_tags(item)),
        "notes": item.notes or "",
        "status": ", ".join(flags),
        # Not a projected column: drives the numbered layout's current marker.
        "current": item.id == queue.current_item_id,
    }


def _member(item: QueueItem) -> str | None:
    if item.user is None:
        return None
    return item.user.full_name or item.user.email or None


def _tags(item: QueueItem) -> list[str]:
    return sorted(link.tag.name for link in item.tag_links if link.tag is not None)


def _queue_id(params: dict) -> int:
    """The job row's params round-trip through JSON — validate, don't trust."""
    try:
        return int(params["queue_id"])
    except (KeyError, TypeError, ValueError):
        raise ExportError(ExportMessages.EXPORT_INVALID_PARAMS)
