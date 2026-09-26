from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from pydantic import ConfigDict, Field

from app.models.tenant.wiki import WikiPageOrder, WikiReadingWidth
from app.schemas.base import SanitizedBaseModel, TitleStr
from app.schemas.query import PageMeta
from app.schemas.tenant.resource_grant import ResourceGrantSchema, initiative_readable
from app.schemas.tenant.document import smart_link_url
from app.schemas.tenant.tag import TagSummary, annotated_tags
from app.schemas.tenant.tool import ToolSummaryBase, from_row

if TYPE_CHECKING:  # pragma: no cover
    from app.db.guild_standing import GuildContext


class WikiBase(SanitizedBaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = Field(default=None, max_length=2000)


class WikiCreate(WikiBase):
    name: TitleStr = Field(..., min_length=1, max_length=255)
    initiative_id: int
    tag_ids: Optional[List[int]] = None
    # Initial sharing — the same grant list the PUT /grants endpoint takes. A
    # wiki defaults to readable by the whole initiative: it is written to be
    # read.
    grants: List[ResourceGrantSchema] = Field(default_factory=initiative_readable)


class WikiSettings(SanitizedBaseModel):
    """What a wiki is *for*, as the handful of choices that differ.

    Every field is optional on the way in and only what is sent is written, so
    one switch is one request rather than a whole form.
    """

    #: How siblings are ordered in the tree.
    page_order: Optional[WikiPageOrder] = None
    #: Whether the tree shows how many pages sit under each one.
    #: How deep the contents rail goes — 2 to 4 heading levels.
    contents_depth: Optional[int] = Field(default=None, ge=2, le=4)
    #: Whether a page shows what links to it.
    show_connections: Optional[bool] = None
    show_updated_at: Optional[bool] = None
    #: Whether a page's body fills the screen or holds to a reading measure.
    reading_width: Optional[WikiReadingWidth] = None
    #: The wiki's own accent, as a CSS colour. ``null`` takes the app's.
    accent_color: Optional[str] = Field(default=None, max_length=32)
    #: A page whose body seeds every new one. ``null`` clears it; a set value
    #: has to be one of this wiki's own pages.
    template_page_id: Optional[int] = None


class WikiUpdate(WikiSettings):
    name: Optional[TitleStr] = Field(default=None, min_length=1, max_length=255)
    description: Optional[str] = Field(default=None, max_length=2000)
    #: The page the wiki opens on. ``null`` clears the choice and it opens on
    #: the first top-level page; a set value has to be one of its own pages.
    home_page_id: Optional[int] = None


class WikiSummary(WikiBase, ToolSummaryBase):
    #: How many pages it holds. Served with the row so a list of wikis can say
    #: so without a request per card.
    page_count: int = 0
    #: The page it opens on, or ``null`` where none was chosen.
    home_page_id: Optional[int] = None
    #: What this wiki is for — see :class:`WikiSettings`.
    page_order: WikiPageOrder = WikiPageOrder.manual
    contents_depth: int = 3
    show_connections: bool = True
    show_updated_at: bool = True
    reading_width: WikiReadingWidth = WikiReadingWidth.wide
    accent_color: Optional[str] = None
    template_page_id: Optional[int] = None
    comment_count: int = 0


class WikiRead(WikiSummary):
    """A wiki on its own page. The same shape as its summary: the pages are
    fetched as a tree of their own, because a wiki is navigated rather than
    read end to end."""


class WikiListResponse(PageMeta):
    items: List[WikiSummary]


class WikiPageCreate(SanitizedBaseModel):
    #: Optional, and usually absent: a page is made before it is about
    #: anything, so it starts with no name rather than one somebody has to
    #: delete before typing their own. Every surface that draws a page falls
    #: back to "Untitled" for one that has not been named yet.
    title: Optional[TitleStr] = Field(default=None, max_length=255)
    #: What to file the new page under. Absent means the top of the wiki.
    parent_page_id: Optional[int] = None
    #: A page starts as a draft, and is published when somebody says so. A new
    #: page is empty and unnamed for as long as it takes to write it, and a
    #: wiki people read should not be showing them that — so the default is the
    #: safe half of the answer, and publishing is a decision.
    is_draft: bool = True
    content: Optional[Dict[str, Any]] = None
    tag_ids: Optional[List[int]] = None


class WikiPageUpdate(SanitizedBaseModel):
    """A change to one page.

    Every field is optional and only what is sent is written, so renaming a
    page is the same request shape as editing its body.
    """

    title: Optional[TitleStr] = Field(default=None, min_length=1, max_length=255)
    is_draft: Optional[bool] = None
    content: Optional[Dict[str, Any]] = None
    tag_ids: Optional[List[int]] = None


class WikiPageMove(SanitizedBaseModel):
    """Where a page should sit after a drag — two facts, sent together.

    What it is filed under and where it sits among what else is filed there.
    One request, because a drag is one gesture and half of it landing is a
    tree nobody arranged.
    """

    #: What the page is now filed under. Absent — the default — is the top of
    #: the wiki, so a move that says nothing about filing unfiles the page.
    parent_page_id: Optional[int] = None
    #: Index among the pages filed in the same place, after the move.
    #: Out-of-range clamps.
    position: int = Field(default=0, ge=0)


class WikiPageKind(str, Enum):
    """What a row in a wiki's navigation actually is.

    A wiki holds pages of its own and documents somebody put in it. The second
    kind is a document still — it is not copied in, it keeps its own address,
    its own sharing and its own history — so the navigation has to say which it
    is looking at rather than pretend they are the same row.
    """

    #: A page belonging to this wiki, written here.
    page = "page"
    #: A document placed in this wiki by a ``part_of`` edge.
    document = "document"


class WikiPageHeading(SanitizedBaseModel):
    """One heading written on a page.

    Carried with the page rather than read from an editor: the navigation draws
    the headings of every page in a wiki, and only one of them is ever open.
    """

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    text: str
    #: 1-6, from the heading tag.
    level: int
    #: What the rendered heading's ``id`` is, so a link from the navigation
    #: lands on it.
    anchor: str


class WikiPageSummary(SanitizedBaseModel):
    """One page as the navigation draws it — no body.

    The navigation renders every page of a wiki at once, so this carries what a
    row needs and nothing that would make the payload grow with what people
    have written.
    """

    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

    id: int
    wiki_id: int
    guild_id: int
    #: Which of the two things this row is. A document keeps its own id, so a
    #: client keys rows on the pair rather than on the number alone.
    kind: WikiPageKind = WikiPageKind.page
    #: What this row is filed under: a page, or ``None`` for the top. A
    #: document is filed like a page is, but never holds anything itself.
    parent_page_id: Optional[int] = None
    position: int = 0
    #: A document placed in a wiki is never a draft: it is not this wiki's to
    #: hold back, and it is readable wherever else it already lives.
    is_draft: bool = False
    title: str
    slug: str
    created_by: int | None = None
    created_at: datetime
    updated_at: datetime
    #: What is written on the page, so the navigation can nest it without
    #: opening it.
    headings: List[WikiPageHeading] = Field(default_factory=list)
    tags: List[TagSummary] = Field(default_factory=list)
    #: A document row's kind of document and the facts its icon is drawn
    #: from — a PDF, a spreadsheet and a link to a design tool each look like
    #: what they are. ``None`` on a page.
    document_type: Optional[str] = None
    file_content_type: Optional[str] = None
    original_filename: Optional[str] = None
    smart_link_url: Optional[str] = None


class WikiPageRead(WikiPageSummary):
    """One page, opened."""

    content: Dict[str, Any] = Field(default_factory=dict)
    comment_count: int = 0


class WikiPageTree(SanitizedBaseModel):
    """Every page of a wiki, in reading order — each page, then what is filed
    under it.

    Flat on the wire and a tree by ``parent_page_id``: the navigation draws all
    of it at once, and the order it arrives in is the order it reads in.
    """

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    items: List[WikiPageSummary]


class WikiPageLink(SanitizedBaseModel):
    """One end of a connection a page has.

    Deliberately not a page-shaped object: the other end of an edge is often
    not a page at all — a task, a calendar event — so this is what any of them
    have in common, and the kind says which route addresses it.
    """

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    #: The ``SearchEntityType`` value — ``task``, ``wiki_page``, ``document``, …
    entity_type: str
    entity_id: int
    title: str
    #: How the two are connected: ``references`` for a link somebody wrote in
    #: the body, or the relationship type they asserted by hand.
    relationship_type: str
    #: Where the far end lives, so a client can address it without a second
    #: request. A page of another wiki is reached through that wiki, and a task
    #: through its project — which is what ``tool``/``tool_id`` name. Null where
    #: the target belongs to no initiative (a guild-level tag).
    initiative_id: Optional[int] = None
    #: The governing tool and its id — the resolver works both out already.
    tool: Optional[str] = None
    tool_id: Optional[int] = None


class WikiPageLinks(SanitizedBaseModel):
    """What a page connects to, both ways.

    ``outgoing`` is what this page names; ``incoming`` is what names it — the
    backlinks, which are the thing that makes a wiki more than a folder.
    """

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    outgoing: List[WikiPageLink] = Field(default_factory=list)
    incoming: List[WikiPageLink] = Field(default_factory=list)


def serialize_wiki_page_summary(
    page: "Any", *, context: GuildContext
) -> WikiPageSummary:
    from app.services.tenant.wikis import page_headings

    return from_row(
        WikiPageSummary,
        page,
        guild_id=context.guild_id,
        headings=[WikiPageHeading(**h) for h in page_headings(page.content)],
        tags=annotated_tags(page),
    )


def serialize_document_as_page(
    document: "Any",
    *,
    context: GuildContext,
    wiki_id: int,
    position: int,
    parent_page_id: Optional[int] = None,
) -> WikiPageSummary:
    """A document, as the wiki's navigation draws it.

    Everything a row needs, read off the document itself — including its
    headings, so a document in a wiki opens in the sidebar exactly as a page
    written here does.
    """
    from app.services.tenant.names import slugify
    from app.services.tenant.wikis import page_headings

    return WikiPageSummary(
        id=document.id,
        wiki_id=wiki_id,
        guild_id=context.guild_id,
        kind=WikiPageKind.document,
        parent_page_id=parent_page_id,
        position=position,
        is_draft=False,
        title=document.name,
        slug=slugify(document.name, fallback=f"document-{document.id}"),
        created_by=document.created_by,
        created_at=document.created_at,
        updated_at=document.updated_at,
        headings=[WikiPageHeading(**h) for h in page_headings(document.content)],
        document_type=getattr(document.document_type, "value", document.document_type),
        file_content_type=document.file_content_type,
        original_filename=document.original_filename,
        smart_link_url=smart_link_url(document),
    )


def serialize_wiki_page(page: "Any", *, context: GuildContext) -> WikiPageRead:
    return WikiPageRead(
        **serialize_wiki_page_summary(page, context=context).model_dump(),
        content=page.content or {},
        comment_count=getattr(page, "comment_count", 0),
    )
