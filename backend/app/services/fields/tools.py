"""The datasets that are a tool, one declaration each.

Where a dataset *is* a tool, almost everything about it is already derivable —
its name is the tool's plural, its sharing is the tool's own, and its fields are
its model's columns. So each of these is a name, a tool, and whatever the table
cannot say for itself.

They live together rather than one module each because there is nothing to say
about any of them individually. A dataset that grows a computed field or a
relation worth explaining earns its own module then, the way tasks and counters
have.
"""

from __future__ import annotations

from app.core.tools import Tool
from app.models.tenant.calendar import Calendar
from app.models.tenant.dashboard import Dashboard
from app.models.tenant.document import Document
from app.models.tenant.post import Post
from app.models.tenant.queue import Queue, QueueItem
from app.services.fields.derive import derive_fields
from app.services.fields.spec import Dataset, Hop, Relation

#: A document's body is the document. It is a structured blob rather than a
#: value, so there is nothing a comparison would mean against it — the
#: derivation drops it, and this says why.
_DOCUMENT_INTERNAL = frozenset({"content"})


def build_documents() -> Dataset:
    return Dataset(
        model=Document,
        tool=Tool.document,
        fields=derive_fields(Document, internal=_DOCUMENT_INTERNAL),
    )


def build_queues() -> Dataset:
    return Dataset(model=Queue, tool=Tool.queue, fields=derive_fields(Queue))


def build_queue_items() -> Dataset:
    """One item in a queue. Its own dataset because the question worth asking
    is about the items, and the queue is what they are grouped by."""
    return Dataset(
        model=QueueItem,
        tool=Tool.queue,
        name_override="queue_items",
        fields=derive_fields(QueueItem),
        relations=(
            Relation(
                name="queue",
                hops=(Hop(dataset="queues", left="queue_id", right="id"),),
            ),
        ),
    )


def build_calendars() -> Dataset:
    return Dataset(model=Calendar, tool=Tool.calendar, fields=derive_fields(Calendar))


def build_dashboards() -> Dataset:
    #: What a dashboard is made of is a definition, and a definition is not a
    #: value to compare against.
    return Dataset(
        model=Dashboard,
        tool=Tool.dashboard,
        fields=derive_fields(Dashboard, internal=frozenset({"definition", "config"})),
    )


def build_posts() -> Dataset:
    return Dataset(
        model=Post,
        tool=Tool.post,
        fields=derive_fields(Post, internal=frozenset({"body"})),
    )
