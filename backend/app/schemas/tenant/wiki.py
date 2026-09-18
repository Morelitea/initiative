from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import ConfigDict, Field

from app.models.tenant.wiki import WikiPageOrder, WikiReadingWidth
from app.schemas.base import SanitizedBaseModel, TitleStr
from app.schemas.tenant.archive import ArchiveState
from app.schemas.tenant.resource_grant import ResourceGrantSchema
from app.schemas.tenant.tag import TagSummary


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
    grants: List[ResourceGrantSchema] = Field(
        default_factory=lambda: [
            ResourceGrantSchema(all_initiative_members=True, level="read")
        ]
    )


class WikiSettings(SanitizedBaseModel):
    """What a wiki is *for*, as the handful of choices that differ.

    Every field is optional on the way in and only what is sent is written, so
    one switch is one request rather than a whole form.
    """

    #: How siblings are ordered in the tree.
    page_order: Optional[WikiPageOrder] = None
    #: Whether the tree shows how many pages sit under each one.
    show_page_counts: Optional[bool] = None
    #: How deep the contents rail goes — 2 to 4 heading levels.
    contents_depth: Optional[int] = Field(default=None, ge=2, le=4)
    #: Whether a page shows what links to it.
    show_connections: Optional[bool] = None
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


class WikiSummary(WikiBase, ArchiveState):
    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

    id: int
    initiative_id: int
    guild_id: int
    created_by: int
    created_at: datetime
    updated_at: datetime
    #: How many pages it holds. Served with the row so a list of wikis can say
    #: so without a request per card.
    page_count: int = 0
    #: The page it opens on, or ``null`` where none was chosen.
    home_page_id: Optional[int] = None
    #: What this wiki is for — see :class:`WikiSettings`.
    page_order: WikiPageOrder = WikiPageOrder.manual
    show_page_counts: bool = False
    contents_depth: int = 3
    show_connections: bool = True
    reading_width: WikiReadingWidth = WikiReadingWidth.wide
    accent_color: Optional[str] = None
    template_page_id: Optional[int] = None
    my_permission_level: Optional[str] = None
    # When false this entity's comment thread is off — the UI renders none
    # and the API refuses to read or post one.
    comments_enabled: bool = True
    comment_count: int = 0
    tags: List[TagSummary] = Field(default_factory=list)
    grants: List[ResourceGrantSchema] = Field(default_factory=list)


class WikiRead(WikiSummary):
    """A wiki on its own page. The same shape as its summary: the pages are
    fetched as a tree of their own, because a wiki is navigated rather than
    read end to end."""


class WikiListResponse(SanitizedBaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    items: List[WikiSummary]
    total_count: int
    page: int
    page_size: int
    has_next: bool


class WikiPageCreate(SanitizedBaseModel):
    title: TitleStr = Field(..., min_length=1, max_length=255)
    #: Where it sits in the tree. ``null`` is a top-level page.
    parent_page_id: Optional[int] = None
    content: Optional[Dict[str, Any]] = None
    tag_ids: Optional[List[int]] = None


class WikiPageUpdate(SanitizedBaseModel):
    """A change to one page.

    Every field is optional and only what is sent is written, so renaming a
    page and moving it are the same request shape as editing its body.
    ``parent_page_id`` is the one field that is meaningfully ``null``: it means
    "make this a top-level page", which is different from not sending it.
    """

    title: Optional[TitleStr] = Field(default=None, min_length=1, max_length=255)
    content: Optional[Dict[str, Any]] = None
    tag_ids: Optional[List[int]] = None


class WikiPageMove(SanitizedBaseModel):
    """Where a page should sit after a drag.

    The two facts the tree needs, together: a page dropped into a new parent
    almost always lands at a particular place among its new siblings, and
    sending them separately would draw the tree wrong in between.
    """

    #: ``null`` makes it a top-level page.
    parent_page_id: Optional[int] = None
    #: Index among its siblings, after the move. Out-of-range clamps.
    position: int = Field(default=0, ge=0)


class WikiPageSummary(SanitizedBaseModel):
    """One page as the tree draws it — no body.

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
    parent_page_id: Optional[int] = None
    position: int = 0
    title: str
    slug: str
    created_by: int
    created_at: datetime
    updated_at: datetime
    tags: List[TagSummary] = Field(default_factory=list)


class WikiPageRead(WikiPageSummary):
    """One page, opened."""

    content: Dict[str, Any] = Field(default_factory=dict)
    comment_count: int = 0


class WikiPageTree(SanitizedBaseModel):
    """Every page of a wiki, flat, in reading order.

    Flat rather than nested: each row names its parent, and the client builds
    the shape. A nested payload would have to be walked to find one page and
    re-walked to move it, and the tree is drawn from the same rows either way.
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


def serialize_wiki_summary(
    wiki: "Any", *, user_id: Optional[int] = None
) -> WikiSummary:
    # Local import avoids a schema -> service import cycle.
    from app.core.tools import Tool
    from app.schemas.tenant.tag import annotated_tags
    from app.services.permissions import client_access, serialize_grants

    return WikiSummary(
        id=wiki.id,
        name=wiki.name,
        description=wiki.description,
        initiative_id=wiki.initiative_id,
        guild_id=wiki.guild_id,
        created_by=wiki.created_by,
        created_at=wiki.created_at,
        updated_at=wiki.updated_at,
        page_count=int(getattr(wiki, "page_count", 0)),
        home_page_id=wiki.home_page_id,
        page_order=wiki.page_order,
        show_page_counts=wiki.show_page_counts,
        contents_depth=wiki.contents_depth,
        show_connections=wiki.show_connections,
        reading_width=wiki.reading_width,
        accent_color=wiki.accent_color,
        template_page_id=wiki.template_page_id,
        archived_at=wiki.archived_at,
        **client_access(Tool.wiki, wiki, user_id),
        comments_enabled=wiki.comments_enabled,
        comment_count=getattr(wiki, "comment_count", 0),
        tags=annotated_tags(wiki),
        grants=serialize_grants(wiki),
    )


def serialize_wiki(wiki: "Any", *, user_id: Optional[int] = None) -> WikiRead:
    return WikiRead(**serialize_wiki_summary(wiki, user_id=user_id).model_dump())


def serialize_wiki_page_summary(page: "Any") -> WikiPageSummary:
    from app.schemas.tenant.tag import annotated_tags

    return WikiPageSummary(
        id=page.id,
        wiki_id=page.wiki_id,
        guild_id=page.guild_id,
        parent_page_id=page.parent_page_id,
        position=page.position,
        title=page.title,
        slug=page.slug,
        created_by=page.created_by,
        created_at=page.created_at,
        updated_at=page.updated_at,
        tags=annotated_tags(page),
    )


def serialize_wiki_page(page: "Any") -> WikiPageRead:
    return WikiPageRead(
        **serialize_wiki_page_summary(page).model_dump(),
        content=page.content or {},
        comment_count=getattr(page, "comment_count", 0),
    )
