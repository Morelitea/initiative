"""Import-side pydantic mirrors of the export envelopes.

Each model parses the dict shape its export adapter emits (see
``services/export/adapters/{document,queue,counter_group,calendar,post}.py``)
with ``extra="ignore"``: informational export fields (queue member/document/
task display text, event ids and timestamps, linked document titles) parse
and drop — they reference guild-local state an import cannot rebind.

Every envelope is schema version 1. There is no support for reading an
earlier shape: the app imports what this build exports, and nothing else.
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import ConfigDict, model_validator

from app.models.tenant.property import PropertyType
from app.schemas.base import SanitizedBaseModel

CURRENT_SCHEMA_VERSION = 1
MIN_SUPPORTED_IMPORT_VERSION = 1


class _EnvelopeBase(SanitizedBaseModel):
    model_config = ConfigDict(extra="ignore")

    schema_version: int = CURRENT_SCHEMA_VERSION


class EnvelopePropertyValue(SanitizedBaseModel):
    """Flat, by-name property value — the shared encoding written by
    ``export/property_values.py::property_export_dict``."""

    model_config = ConfigDict(extra="ignore")

    property_name: str
    property_type: PropertyType
    value_text: Optional[str] = None
    value_number: Optional[float] = None
    value_boolean: Optional[bool] = None
    value_json: Any = None
    value_handle: Optional[str] = None


class DocumentEnvelope(_EnvelopeBase):
    type: Literal["initiative-document"]
    document_type: str  # native | spreadsheet | smart_link | whiteboard
    name: str
    content: dict[str, Any] = {}
    tags: list[str] = []
    properties: list[EnvelopePropertyValue] = []


class WikiPageEnvelope(SanitizedBaseModel):
    """One page: its body, where it sits, and what it is filed under.

    ``parent`` is a **slug**, not an id, and it is resolved after every page
    exists — the export writes pages in navigation order, which can put a
    child before its parent.
    """

    model_config = ConfigDict(extra="ignore")

    title: str
    slug: str
    parent: Optional[str] = None
    position: int = 0
    is_draft: bool = False
    content: dict[str, Any] = {}
    tags: list[str] = []
    #: When the page was written and when it was last edited. Absent in an
    #: export taken before they were carried, and absent is not "now" — the
    #: importer only uses a value it was actually given.
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    #: Who wrote it, where it came from: a handle the people step places, and
    #: the name to show when nobody answers to it.
    author_handle: Optional[str] = None
    author_name: Optional[str] = None
    #: The handles the body's mention nodes name without an account yet. Each
    #: one the people step places is linked to that account on apply.
    mention_handles: list[str] = []


class WikiEnvelope(_EnvelopeBase):
    """A wiki, its pages, and the shape they sit in.

    What it deliberately drops is the sharing, for the reason every envelope
    drops it: who may read this is a fact about the community it was written
    in, not about the writing. ``home_page`` crosses as a slug like the tree.
    """

    type: Literal["initiative-wiki"]
    name: str
    description: Optional[str] = None
    home_page: Optional[str] = None
    tags: list[str] = []
    pages: list[WikiPageEnvelope] = []


class GalleryImageEnvelope(SanitizedBaseModel):
    """One picture: what the row says about it, and the key naming its bytes.

    ``storage_key`` is the blob's name under ``assets/`` in the backup zip. A
    picture whose bytes did not travel is skipped on apply and counted — a
    gallery row pointing at a file that is not there would render as a broken
    tile forever.
    """

    model_config = ConfigDict(extra="ignore")

    storage_key: str
    title: Optional[str] = None
    caption: Optional[str] = None
    content_type: Optional[str] = None
    size_bytes: Optional[int] = None
    original_filename: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    tags: list[str] = []


class GalleryEnvelope(_EnvelopeBase):
    """A gallery and its pictures.

    Only meaningful inside a backup: the bytes ride under ``assets/`` and the
    images name them by key. Thumbnails are not carried — the app makes those
    from the picture.
    """

    type: Literal["initiative-gallery"]
    name: str
    description: Optional[str] = None
    cover: Optional[str] = None
    tags: list[str] = []
    images: list[GalleryImageEnvelope] = []


class QueueEnvelopeItem(SanitizedBaseModel):
    model_config = ConfigDict(extra="ignore")

    label: str
    position: float = 0.0
    color: Optional[str] = None
    notes: Optional[str] = None
    is_visible: bool = True
    held_at_round: Optional[int] = None
    is_current: bool = False
    tags: list[str] = []
    # `member`, `documents`, `tasks` are informational display text in the
    # export — ignored here (extra="ignore"), counted as a warning on apply.
    member: Optional[str] = None


class QueueEnvelope(_EnvelopeBase):
    type: Literal["initiative-queue"]
    name: str
    description: Optional[str] = None
    is_active: bool = False
    current_round: int = 1
    items: list[QueueEnvelopeItem] = []


class CounterEnvelopeItem(SanitizedBaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    color: Optional[str] = None
    count: float = 0
    min: Optional[float] = None
    max: Optional[float] = None
    step: float = 1
    initial_count: float = 0
    view_mode: str = "number"
    position: float = 0


class CounterGroupEnvelope(_EnvelopeBase):
    type: Literal["initiative-counter-group"]
    name: str
    description: Optional[str] = None
    counters: list[CounterEnvelopeItem] = []


class DashboardEnvelope(_EnvelopeBase):
    """A dashboard as a backup carries it: a presentation spec and its canvas
    config, and no content of its own.

    ``definition`` is ``dict`` here rather than a modelled shape on purpose —
    it is re-validated on import by
    ``dashboard_definition.normalize_dashboard_definition``, which is the same
    check the create endpoint runs. A file is not a trusted source, and there
    is no second definition validator.
    """

    type: Literal["initiative-dashboard"]
    name: str
    description: Optional[str] = None
    # Present only for a dashboard built on a built-in app. Dropped on import
    # when the destination has no such listing, so the dashboard arrives as an
    # ordinary one rather than pointing at nothing.
    listing_uid: Optional[str] = None
    listing_version: Optional[str] = None
    definition: dict[str, Any] = {}
    config: dict[str, Any] = {}
    tags: list[str] = []


class PostPollEnvelope(SanitizedBaseModel):
    """The question a notice asks, as a backup carries it.

    The **choices** cross; the **answers** do not. A ballot is one person in
    one community saying something, and the ids naming them mean nothing in the
    guild this is restored into — the same reason the sharing is not carried
    either. So an imported poll arrives open and unanswered, which is what a
    question somebody has just asked is.

    ``closes_at`` is dropped for the reason the pin and the schedule are: it
    said when this question stopped mattering on the board it came from.
    """

    model_config = ConfigDict(extra="ignore")

    question: Optional[str] = None
    options: list[str] = []
    allows_multiple: bool = False
    is_anonymous: bool = False
    hide_results: bool = False

    @model_validator(mode="after")
    def _options_within_limits(self) -> "PostPollEnvelope":
        # The same bounds the endpoints hold a poll to. An import is a write
        # like any other, and one that skipped them would store a question the
        # app would refuse to accept or to save again.
        from app.models.tenant.post_poll import (
            MAX_POLL_OPTION_CHARS,
            MAX_POLL_OPTIONS,
            MIN_POLL_OPTIONS,
        )

        cleaned = [option.strip() for option in self.options]
        if not MIN_POLL_OPTIONS <= len(cleaned) <= MAX_POLL_OPTIONS:
            raise ValueError("poll has more or fewer choices than a poll may have")
        if any(not option or len(option) > MAX_POLL_OPTION_CHARS for option in cleaned):
            raise ValueError("a poll choice is empty or longer than one may be")
        if len({option.casefold() for option in cleaned}) != len(cleaned):
            raise ValueError("two poll choices say the same thing")
        self.options = cleaned
        return self


class PostEnvelope(_EnvelopeBase):
    """One bulletin-board notice: its headline, its Lexical body, its tags,
    and the question it asks.

    The pin is deliberately not carried. A pin says "this matters on this
    board right now", which is a fact about the board it was pinned to, not
    about the notice — an import that restored it would put a stranger's
    notice at the top of somebody else's board.

    The body's ceiling is enforced here rather than left to the column: an
    import is a write like any other, and one that skipped the limit would
    store a post the endpoints would refuse to accept or to save again. The
    headline is not — it is display text, so the importer trims it and says
    so rather than failing a whole restore over a long title.
    """

    type: Literal["initiative-post"]
    name: str
    body: dict[str, Any] = {}
    tags: list[str] = []
    poll: Optional[PostPollEnvelope] = None

    @model_validator(mode="after")
    def _body_within_limits(self) -> "PostEnvelope":
        # The same rule the endpoints apply, not a second copy of it: an
        # envelope that checked only the character count let a large, low-text
        # Lexical structure through, which a normal write would then refuse.
        # Imported here because the schema module is dependency-light on
        # purpose, and this is the one place it needs the post rules.
        from app.schemas.tenant.post import post_body_too_long

        if post_body_too_long(self.body):
            raise ValueError("post body exceeds the limits a post is held to")
        return self


class EventEnvelopeAttendee(SanitizedBaseModel):
    model_config = ConfigDict(extra="ignore")

    name: Optional[str] = None
    #: ``foobar#1234`` — the handle names one account and is what the export
    #: writes. An address is not a person's identifier here.
    handle: Optional[str] = None
    rsvp: str = "pending"


class EventEnvelopeItem(SanitizedBaseModel):
    model_config = ConfigDict(extra="ignore")

    title: str
    description: Optional[str] = None
    location: Optional[str] = None
    start_at: str
    end_at: str
    all_day: bool = False
    recurrence: Optional[dict[str, Any]] = None
    attendees: list[EventEnvelopeAttendee] = []
    tags: list[str] = []
    properties: list[EnvelopePropertyValue] = []
    #: What this event was called where it came from. An event is a thing
    #: other entries point at — a sprint with its tasks in it — so it needs a
    #: name the job's deferred link pass can resolve, exactly as a task does.
    external_ref: Optional[str] = None
    #: When the event was written down (not when it happens — that is
    #: ``start_at``). The export has always emitted it; it is read now.
    created_at: Optional[str] = None


class CalendarEnvelope(_EnvelopeBase):
    type: Literal["initiative-calendar"]
    name: str
    description: Optional[str] = None
    color: Optional[str] = None
    events: list[EventEnvelopeItem] = []
