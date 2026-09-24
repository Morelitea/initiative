"""Helpers shared by the source adapters, and the base every per-tool source
is built on.

A tool's export is the same shape every time: take the selection out of the
job params, fetch each entity under the caller's RLS session, count the rows
it is worth, and turn it into a render item named after the entity and the
date. ``ToolExportAdapter`` holds that shape and derives the registry key and
the envelope suffix from the tool's own ``Tool`` value, the way
``tool_envelope_type`` already does — so a per-tool module states only which
rows it loads and how one row serialises.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.messages import ExportMessages
from app.core.tools import Tool, tool_envelope_type, tool_export_source
from app.models.platform.user import User
from app.services.export.contract import RenderItem, RenderRequest
from app.services.export.engine import ExportError
from app.services.export.i18n import localize_now
from app.services.platform.csv_export import safe_filename_component

# Bound on a single selection: page-size multiples, not initiative dumps —
# each id costs a fetch+authorize round trip at count AND build time.
MAX_SELECTION = 100


def selection_ids(params: dict, *, single_key: str, multi_key: str) -> list[int]:
    """Normalize a selection selector to a validated id list. Accepts either
    the legacy single-id key or the multi-id key (job params round-trip
    through JSON — validate, don't trust). Order-preserving dedupe."""
    raw = params.get(multi_key)
    if raw is None and params.get(single_key) is not None:
        raw = [params[single_key]]
    if not isinstance(raw, list) or not raw or len(raw) > MAX_SELECTION:
        raise ExportError(ExportMessages.EXPORT_INVALID_PARAMS)
    try:
        ids = [int(value) for value in raw]
    except (TypeError, ValueError):
        raise ExportError(ExportMessages.EXPORT_INVALID_PARAMS)
    return list(dict.fromkeys(ids))


def export_stem(name: str, date: str) -> str:
    """The filename stem an export item is keyed by: the entity's own name,
    reduced to filename-safe characters, and the date the export was taken."""
    return f"{safe_filename_component(name).lower()}-{date}"


def envelope_key(tool: Tool, name: str, date: str) -> str:
    """The item key for a tool's importable envelope: the entity's stem plus
    the ``initiative-<tool>`` suffix the importer answers to."""
    return f"{export_stem(name, date)}.{tool_envelope_type(tool)}"


@dataclass(frozen=True)
class BuildContext:
    """What one batch of render items is built against: the requested format,
    the creator (locale and attribution), the guild, a single clock read, and
    whatever ``ToolExportAdapter.prepare`` loaded for the whole batch."""

    format: str
    user: User
    guild_id: int
    now: datetime
    prepared: Any = None

    @property
    def date(self) -> str:
        return self.now.strftime("%Y-%m-%d")


class ToolExportAdapter:
    """The per-tool export source: a selection of entities, each rendered as
    one item.

    A subclass names its ``Tool`` and fills in the three tool-shaped hooks —
    :meth:`fetch` (which rows, and the RLS seam that authorizes them),
    :meth:`rows` (how many rows one entity is worth) and :meth:`item` (how one
    entity serialises). Everything else — the registry key, the selection
    params, counting, and the ``RenderRequest`` — is the same for every tool
    and lives here.
    """

    tool: Tool
    source: str
    # Required by the SourceAdapter protocol; a json envelope renders no
    # template. A tool with report formats names its own.
    template_id: str = "data-table"
    formats: frozenset[str] = frozenset({"json"})

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        cls.source = tool_export_source(cls.tool)

    # -- what a tool states --------------------------------------------------

    async def fetch(
        self, session: AsyncSession, user: User, guild_id: int, entity_id: int, /
    ) -> Any:
        """Load and authorize one selected entity under the caller's RLS
        session — that query IS the access check."""
        raise NotImplementedError

    def rows(self, entity: Any, /) -> int:
        """How many rows one entity is worth, for the inline-vs-job decision
        and the size bound. One per entity unless its contents are the size."""
        return 1

    def item(self, entity: Any, ctx: BuildContext, /) -> RenderItem:
        """Serialise one entity into its render item."""
        raise NotImplementedError

    async def prepare(self, session: AsyncSession, entities: list[Any], /) -> Any:
        """Anything the item builders need across the whole batch, loaded in
        one pass (they are synchronous and hold no session)."""
        return None

    # -- the shape every tool shares -----------------------------------------

    def selection(self, params: dict) -> list[int]:
        """The ids this request selected, read from the tool's own selector
        keys (``{tool}_ids``, or the single ``{tool}_id``)."""
        return selection_ids(
            params,
            single_key=f"{self.tool.value}_id",
            multi_key=f"{self.tool.value}_ids",
        )

    async def load(
        self,
        session: AsyncSession,
        user: User,
        guild_id: int,
        params: dict,
        format: str,
    ) -> list[Any]:
        """Every selected entity, fetched and authorized one by one."""
        return [
            await self.fetch(session, user, guild_id, entity_id)
            for entity_id in self.selection(params)
        ]

    async def count(
        self,
        session: AsyncSession,
        *,
        user: User,
        guild_id: int,
        params: dict,
        format: str,
    ) -> int:
        entities = await self.load(session, user, guild_id, params, format)
        return sum(self.rows(entity) for entity in entities)

    async def build(
        self,
        session: AsyncSession,
        *,
        user: User,
        guild_id: int,
        params: dict,
        format: str,
    ) -> RenderRequest:
        entities = await self.load(session, user, guild_id, params, format)
        ctx = BuildContext(
            format=format,
            user=user,
            guild_id=guild_id,
            # One clock read: the filename date and the subtitle timestamp
            # must not straddle midnight into disagreeing dates.
            now=localize_now(datetime.now(timezone.utc), params.get("tz")),
            prepared=await self.prepare(session, entities),
        )
        batch = tuple(self.item(entity, ctx) for entity in entities)
        if format == "json":
            # An envelope names people by handle, never by id — including the
            # people its body mentions, which the item builders cannot look
            # up because they hold no session.
            from app.services.import_engine.mentions import detach_envelope_mentions

            for item in batch:
                await detach_envelope_mentions(session, item.data)
        return RenderRequest(
            guild_id=guild_id,
            template_id=self.template_id,
            format=format,
            batch=batch,
        )
