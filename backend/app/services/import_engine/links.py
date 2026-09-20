"""The deferred pass that turns what an import *said* into edges.

An envelope names the far end of a link by an **external ref** — a string the
source chose (``"jira:ACME-123"``, ``"task:41"``) — and not by an id, because
at the moment the link is read the far end usually does not exist yet. It can
be later in the same envelope, in a different envelope, or created by a
different importer entirely: a task blocked by another task, a sub-task under
its epic, and a task in its sprint are three rows written by two importers,
and only one of those pairs is ever in the same file.

So nothing resolves as it goes. Every importer does two things and knows
nothing about any other: it **registers** what it created under the ref the
envelope gave it, and it **records** the links it read. Once the last entry
has flushed, the job resolves the whole collection at once — every ref that
found both ends becomes an edge, and every ref that did not is counted.

An envelope imported on its own runs the same code: it resolves the links
whose far end it also carried, and counts the rest. There is no second path.

What this is not: a permission decision. Edges are written on the caller's
routed session, so RLS gates every insert exactly as it gates a link made by
hand. A ref that names something the importer cannot reach resolves to
nothing, which is the same answer as a ref that names nothing at all.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.relationships import Provenance, RelationshipType
from app.core.search import SearchEntityType
from app.services.tenant import relationships as relationships_service
from app.services.tenant.relationships import Endpoint

logger = logging.getLogger(__name__)

#: How an imported edge is known. ``manual``, because the source asserted it:
#: a Jira "blocks" link and a sub-task's parent are statements somebody made,
#: not something read out of a sentence (``content``) or offered by a model
#: and accepted (``inferred``). It also means taking one back is remembered.
IMPORT_PROVENANCE = Provenance.manual


@dataclass(frozen=True)
class PendingLink:
    """One edge an envelope asserted, both ends named by ref."""

    source_ref: str
    relationship_type: RelationshipType
    target_ref: str


@dataclass
class LinkResolution:
    """What the pass managed to write.

    ``unresolved`` is the honest half of the report: a link whose far end was
    never imported is not an error — a Jira project links to issues outside
    the selection all the time — but it is something the person who ran the
    import is owed a number for.
    """

    created: int = 0
    unresolved: int = 0
    duplicate: int = 0


@dataclass
class LinkCollector:
    """One job's refs and the links waiting on them.

    Lives for the length of a job and is never persisted: a ref is a name the
    source used, meaningful only while the import that read it is running.
    """

    _refs: dict[str, Endpoint] = field(default_factory=dict)
    _pending: list[PendingLink] = field(default_factory=list)

    def register(
        self, ref: str | None, kind: SearchEntityType, entity_id: int | None
    ) -> None:
        """Say that ``ref`` is now this row.

        A ref the envelope did not give, and a row that somehow has no id, are
        both nothing to record rather than something to fail over — a task
        with no external ref is simply a task nothing can point at.

        A repeated ref keeps the **first** row it named. Two things claiming
        one name is the source's ambiguity, and picking the earlier one at
        least makes the outcome the same on every re-run.
        """
        if not ref or entity_id is None:
            return
        if ref in self._refs:
            logger.info("import link ref claimed twice ref=%s", ref)
            return
        self._refs[ref] = Endpoint(kind=kind, id=entity_id)

    def link(
        self,
        source_ref: str | None,
        relationship_type: RelationshipType,
        target_ref: str | None,
    ) -> None:
        """Record an edge to resolve later. Either end missing means there is
        no edge to make — a link with nothing on one side says nothing."""
        if not source_ref or not target_ref:
            return
        self._pending.append(
            PendingLink(
                source_ref=source_ref,
                relationship_type=relationship_type,
                target_ref=target_ref,
            )
        )

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    async def resolve(
        self, session: AsyncSession, *, created_by: int | None = None
    ) -> LinkResolution:
        """Write every edge whose both ends were imported; count the rest.

        Runs after the last entry has flushed, on the caller's session, and
        leaves the collection empty so a second call is a no-op rather than a
        second set of edges.
        """
        resolution = LinkResolution()
        pending, self._pending = self._pending, []
        for item in pending:
            source = self._refs.get(item.source_ref)
            target = self._refs.get(item.target_ref)
            if source is None or target is None:
                resolution.unresolved += 1
                continue
            if source.node == target.node:
                # A ref pointing at itself — a source that named one thing
                # twice. Nothing to write, and nothing worth failing over.
                resolution.unresolved += 1
                continue
            row = await relationships_service.create(
                session,
                source=source,
                relationship_type=item.relationship_type,
                target=target,
                provenance=IMPORT_PROVENANCE,
                created_by=created_by,
            )
            if row is None:
                resolution.duplicate += 1
            else:
                resolution.created += 1
        return resolution
