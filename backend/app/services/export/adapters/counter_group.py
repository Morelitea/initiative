"""Counter-group source adapter: importable backup envelope (json) and a
counter table (pdf/csv/xlsx/md).

The json envelope round-trips the group's full configuration — every counter
with its current value, bounds, step, initial value, view mode, color, and
position — so an import can rebuild the group exactly.

The report formats project the counters into the shared columns/rows payload:
name and the numeric fields, in the group's display order. Numeric cells stay
numbers (int when integral, float otherwise) so xlsx keeps them typed and the
json envelope stays plain-JSON serializable (the render path's ``json.dumps``
does not accept ``Decimal``).

Access rule for every format: READ on the group (exporting is a formatted
read), enforced by the ``get_counter_group_for_export`` seam at both count
and build time, under the caller's RLS session.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.messages import ExportMessages
from app.models.platform.user import User
from app.models.tenant.counter import Counter, CounterGroup
from app.services.export.contract import RenderItem, RenderRequest
from app.services.export.engine import ExportError
from app.services.platform.csv_export import safe_filename_component

_COLUMNS = (
    {"key": "title", "label": "Counter", "width": "2fr"},
    {"key": "count", "label": "Count"},
    {"key": "min", "label": "Min"},
    {"key": "max", "label": "Max"},
    {"key": "step", "label": "Step"},
)


class CounterGroupAdapter:
    source = "counter-group"
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
        group = await self._group(session, user, guild_id, params)
        return len(group.counters)

    async def build(
        self,
        session: AsyncSession,
        *,
        user: User,
        guild_id: int,
        params: dict,
        format: str,
    ) -> RenderRequest:
        group = await self._group(session, user, guild_id, params)
        # One clock read: the filename date and the subtitle timestamp must
        # not straddle midnight into disagreeing dates.
        now = datetime.now(timezone.utc)
        date = now.strftime("%Y-%m-%d")
        stem = safe_filename_component(group.name).lower()
        if format == "json":
            item = RenderItem(
                key=f"{stem}-{date}.initiative-counter-group",
                data=_envelope(group),
            )
        else:
            item = RenderItem(
                key=f"{stem}-{date}", data=_report_payload(group, user, now)
            )
        return RenderRequest(
            guild_id=guild_id,
            template_id=self.template_id,
            format=format,
            batch=(item,),
        )

    async def _group(
        self, session: AsyncSession, user: User, guild_id: int, params: dict
    ) -> CounterGroup:
        from app.services.tenant.counters import get_counter_group_for_export

        return await get_counter_group_for_export(
            session, user, guild_id, group_id=_group_id(params)
        )


def _envelope(group: CounterGroup) -> dict[str, Any]:
    return {
        "kind": "initiative-counter-group",
        "schema_version": 1,
        "name": group.name,
        "description": group.description,
        "counters": [
            {
                "name": counter.name,
                "color": counter.color,
                "count": _number(counter.count),
                "min": _number(counter.min),
                "max": _number(counter.max),
                "step": _number(counter.step),
                "initial_count": _number(counter.initial_count),
                "view_mode": counter.view_mode.value,
                "position": _number(counter.position),
            }
            for counter in group.counters
        ],
    }


def _report_payload(group: CounterGroup, user: User, now: datetime) -> dict[str, Any]:
    counters = group.counters
    generated_at = now.strftime("%Y-%m-%d %H:%M UTC")
    # Both attribution fields can be absent (some OAuth-provisioned accounts
    # carry neither) — never render the literal "None".
    author = user.full_name or user.email or "unknown"
    return {
        "title": group.name,
        "subtitle": (
            f"{len(counters)} counter{'s' if len(counters) != 1 else ''}"
            f" · generated {generated_at} by {author}"
        ),
        "footer": f"{group.name} — counters export",
        "description": group.description or "",
        "columns": [dict(c) for c in _COLUMNS],
        "rows": [_row(counter) for counter in counters],
    }


def _row(counter: Counter) -> dict[str, Any]:
    return {
        "title": counter.name,
        "count": _number(counter.count),
        "min": _number(counter.min) if counter.min is not None else "",
        "max": _number(counter.max) if counter.max is not None else "",
        "step": _number(counter.step),
    }


def _number(value: Decimal | None) -> int | float | None:
    """NUMERIC(20,10) comes back as ``Decimal`` — not JSON-serializable, and
    ugly as text (``5.0000000000``). Integral values become int, the rest
    float; counter values are user-clicked numbers, so float precision is a
    non-issue."""
    if value is None:
        return None
    decimal = value if isinstance(value, Decimal) else Decimal(str(value))
    if decimal == decimal.to_integral_value():
        return int(decimal)
    return float(decimal)


def _group_id(params: dict) -> int:
    """The job row's params round-trip through JSON — validate, don't trust."""
    try:
        return int(params["counter_group_id"])
    except (KeyError, TypeError, ValueError):
        raise ExportError(ExportMessages.EXPORT_INVALID_PARAMS)
