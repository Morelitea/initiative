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

from app.models.platform.user import User
from app.models.tenant.queue import Queue, QueueItem
from app.services.export.contract import RenderItem, RenderRequest
from app.services.export.i18n import et, export_locale, localize_now
from app.services.platform.csv_export import safe_filename_component

# (row key, ``exports`` label key, Typst width hint) — labels resolve to the
# creator's locale at build time.
_COLUMNS = (
    ("order", "columns.order", "auto"),
    ("title", "columns.item", "2fr"),
    ("member", "columns.member", "1fr"),
    ("tags", "columns.tags", "1fr"),
    ("notes", "columns.notes", "2fr"),
    ("status", "columns.status", "auto"),
)


def _columns(locale: str) -> list[dict]:
    return [
        {"key": key, "label": et(label_key, locale), "width": width}
        for key, label_key, width in _COLUMNS
    ]


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
        queues = await self._queues(session, user, guild_id, params)
        return sum(len(queue.items) for queue in queues)

    async def build(
        self,
        session: AsyncSession,
        *,
        user: User,
        guild_id: int,
        params: dict,
        format: str,
    ) -> RenderRequest:
        queues = await self._queues(session, user, guild_id, params)
        # One clock read: the filename date and the subtitle timestamp must
        # not straddle midnight into disagreeing dates.
        now = localize_now(datetime.now(timezone.utc), params.get("tz"))
        return RenderRequest(
            guild_id=guild_id,
            template_id=self.template_id,
            format=format,
            batch=tuple(build_queue_item(queue, format, user, now) for queue in queues),
        )

    async def _queues(
        self, session: AsyncSession, user: User, guild_id: int, params: dict
    ) -> list[Queue]:
        from app.services.export.adapters._common import selection_ids
        from app.services.tenant.queues import get_queue_for_export

        return [
            await get_queue_for_export(session, user, guild_id, queue_id=queue_id)
            for queue_id in selection_ids(
                params, single_key="queue_id", multi_key="queue_ids"
            )
        ]


def build_queue_item(
    queue: Queue, format: str, user: User, now: datetime
) -> RenderItem:
    items = _rotation_order(queue.items)
    date = now.strftime("%Y-%m-%d")
    stem = safe_filename_component(queue.name).lower()
    if format == "json":
        # The envelope is importable machine data — stays canonical, never
        # localized (translating field keys / enum values breaks import).
        return RenderItem(
            key=f"{stem}-{date}.initiative-queue",
            data=_envelope(queue, items),
        )
    return RenderItem(
        key=f"{stem}-{date}", data=_report_payload(queue, items, user, now)
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
    loc = export_locale(user)
    generated_at = now.strftime("%Y-%m-%d %H:%M %Z")
    # Both attribution fields can be absent (some OAuth-provisioned accounts
    # carry neither) — never render the literal "None".
    author = user.full_name or user.email or et("fallback.unknownAuthor", loc)
    parts = [et("summary.items", loc, count=len(items))]
    if queue.is_active:
        parts.append(et("round", loc, round=queue.current_round))
    parts.append(et("generatedBy", loc, date=generated_at, author=author))
    return {
        # The queue name is user data — never translated.
        "title": queue.name,
        "subtitle": " · ".join(parts),
        "footer": et("footer.queue", loc, name=queue.name),
        "page_of": et("pageOf", loc),
        "description": queue.description or "",
        # Markdown renders the rotation as a numbered turn-order list; the
        # other formats consume the columns/rows table.
        "layout": "numbered",
        "columns": _columns(loc),
        "empty_message": et("empty.generic", loc),
        "untitled": et("fallback.untitled", loc),
        "rows": [_row(queue, item, order, loc) for order, item in enumerate(items, 1)],
    }


def _row(queue: Queue, item: QueueItem, order: int, locale: str) -> dict[str, Any]:
    flags = []
    if item.id == queue.current_item_id:
        flags.append(et("status.current", locale))
    if item.held_at_round is not None:
        flags.append(et("status.held", locale))
    if not item.is_visible:
        flags.append(et("status.hidden", locale))
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
