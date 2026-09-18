"""Wiki endpoints — a body of linked pages in an initiative.

Creation is gated at the initiative level (wikis_enabled + create_wikis);
everything after that flows from the wiki's resource-grant DAC
(``resource_grants`` + ``PUT /{id}/grants``), like every other tool.

Three things here are the wiki's own rather than the generic tool shape:

* **Pages are content, not tools.** A page is reached only through its wiki —
  ``/wikis/{id}/pages/…`` — and adding, editing or moving one asks for
  **write** access on the wiki, the way editing a task asks for write on its
  project.
* **The tree comes back whole.** ``GET /{id}/pages`` returns every page of a
  wiki, flat and in reading order, because the navigation draws all of it at
  once. The rows carry no bodies, so the payload grows with the number of
  pages rather than with what has been written on them.
* **A page knows what points at it.** ``GET /{id}/pages/{page_id}/links``
  reads the ``relationships`` table both ways — the ``[[ ]]`` links extracted
  from bodies on save, and the connections people drew by hand — which is what
  makes a wiki a web rather than a folder.
"""

from copy import deepcopy
from typing import Annotated, Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func
from sqlalchemy.orm import selectinload
from sqlmodel import select

from app.api import resource_access
from app.api.deps import (
    GuildContext,
    RLSSessionDep,
    get_current_active_user,
    get_guild_membership,
)
from app.core.messages import InitiativeMessages, WikiMessages
from app.core.relationships import RelationshipType
from app.core.search import SearchEntityType
from app.core.tools import Tool
from app.db import reference_targets
from app.models.platform.user import User
from app.models.tenant.initiative import Initiative
from app.models.tenant.resource_grant import ResourceAccessLevel, ResourceGrant
from app.models.tenant.wiki import Wiki, WikiPage
from app.schemas.tenant.initiative import InitiativeGroupedCountsResponse
from app.schemas.tenant.recent_view import RecentViewWrite
from app.schemas.tenant.resource_grant import ResourceGrantSchema
from app.schemas.tenant.wiki import (
    WikiCreate,
    WikiListResponse,
    WikiPageCreate,
    WikiPageLink,
    WikiPageLinks,
    WikiPageMove,
    WikiPageRead,
    WikiPageTree,
    WikiPageUpdate,
    WikiRead,
    WikiUpdate,
    serialize_wiki,
    serialize_wiki_page,
    serialize_document_as_page,
    serialize_wiki_page_summary,
    serialize_wiki_summary,
)
from app.services import permissions as permissions_service
from app.services.tenant import archive as archive_service
from app.services.tenant import comments as comments_service
from app.services.tenant import content_references
from app.services.tenant import recent_views as recent_views_service
from app.services.tenant import relationships as relationships_service
from app.services.tenant import search as search_service
from app.services.tenant import soft_delete as soft_delete_service
from app.services.tenant import tags as tags_service
from app.services.tenant import tool_listing
from app.services.tenant import wikis as wikis_service

router = APIRouter()

GuildContextDep = Annotated[GuildContext, Depends(get_guild_membership)]
CurrentUserDep = Annotated[User, Depends(get_current_active_user)]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _get_initiative_for_wiki(
    session: RLSSessionDep, initiative_id: int
) -> Initiative:
    stmt = (
        select(Initiative)
        .where(Initiative.id == initiative_id)
        .options(
            selectinload(Initiative.memberships),
            selectinload(Initiative.roles),
        )
    )
    initiative = (await session.exec(stmt)).one_or_none()
    if not initiative:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=InitiativeMessages.NOT_FOUND,
        )
    return initiative


async def _annotate(session: RLSSessionDep, wikis: list) -> None:
    """Everything a wiki row carries beyond its columns, one grouped query
    each for the page."""
    await tags_service.annotate_tags(session, wikis)
    await comments_service.annotate_comment_counts(session, wikis, column="wiki_id")
    await wikis_service.annotate_page_counts(session, wikis)


async def _refetch_wiki(session: RLSSessionDep, wiki_id: int, *, user_id: int) -> Wiki:
    wiki = await wikis_service.get_wiki(session, wiki_id, populate_existing=True)
    if not wiki:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=Tool.wiki.not_found_code,
        )
    await _annotate(session, [wiki])
    return wiki


def _may_write(wiki: Wiki, current_user: User) -> bool:
    """Whether this person may write this wiki — guild admins and full-access
    initiative members included, which is why it goes through the DAC engine
    rather than reading grants directly."""
    level = permissions_service.compute_permission(
        permissions_service.DAC_RESOURCES[Tool.wiki], wiki, current_user.id
    )
    return level in ("write", "owner")


async def _load_page(
    session: RLSSessionDep,
    wiki_id: int,
    page_id: int,
    current_user: User,
    guild_context: GuildContext,
    *,
    access: str = "read",
) -> tuple[Wiki, WikiPage]:
    """The wiki, authorized at ``access``, and one of its pages.

    Authorization is the wiki's: a page is the wiki's content, and reaching
    one means reaching the other.
    """
    wiki = await resource_access.load_authorized(
        session, Tool.wiki, wiki_id, current_user, guild_context, access=access
    )
    page = await wikis_service.get_page(session, wiki.id, page_id)
    # A draft is not part of the wiki for somebody who only reads it, so it is
    # missing rather than refused — the same answer they get for a page that
    # was never written.
    if page is None or (page.is_draft and not _may_write(wiki, current_user)):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=WikiMessages.PAGE_NOT_FOUND,
        )
    return wiki, page


async def _wiki_scope(
    session: RLSSessionDep,
    current_user: User,
    guild_context: GuildContext,
    *,
    initiative_id: Optional[int],
    search: Optional[str] = None,
) -> list | None:
    """Which wikis this reader may see — the guild, the feature switch,
    sharing, and the search box. ``None`` means the initiative exists but has
    the tool turned off."""
    conditions = [Wiki.guild_id == guild_context.guild_id]

    if initiative_id is not None:
        initiative = await session.get(Initiative, initiative_id)
        if initiative and not initiative.wikis_enabled:
            return None
        conditions.append(Wiki.initiative_id == initiative_id)
    else:
        conditions.append(
            Wiki.initiative_id.in_(
                select(Initiative.id).where(Initiative.wikis_enabled == True)  # noqa: E712
            )
        )

    conditions.append(
        permissions_service.listing_scope_clause(
            Tool.wiki,
            Wiki.id,
            current_user.id,
            guild_id=guild_context.guild_id,
            initiative_id=initiative_id,
        )
    )

    name_match = search_service.tool_search_clause(Tool.wiki, Wiki.id, search)
    if name_match is not None:
        conditions.append(name_match)

    return conditions


# ---------------------------------------------------------------------------
# Wikis
# ---------------------------------------------------------------------------


@router.get("/", response_model=WikiListResponse)
async def list_wikis(
    session: RLSSessionDep,
    current_user: CurrentUserDep,
    guild_context: GuildContextDep,
    initiative_id: Optional[int] = Query(default=None),
    search: Optional[str] = Query(
        default=None,
        description=(
            "Full-text match over the wiki's name and description, through the "
            "same index the search page reads."
        ),
    ),
    sort_by: Optional[str] = Query(
        default=None,
        description="Order by one of: name, initiative, updated_at. Omit for newest first.",
    ),
    sort_dir: Optional[str] = Query(default=None, description="asc (default) or desc."),
    archived: Optional[bool] = Query(
        default=None, description=archive_service.ARCHIVED_QUERY_DESCRIPTION
    ),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=0, le=500),
) -> WikiListResponse:
    """List wikis visible to the current user (guild admins see all)."""
    scope = await _wiki_scope(
        session, current_user, guild_context, initiative_id=initiative_id, search=search
    )
    if scope is None:
        return WikiListResponse(
            items=[], total_count=0, page=page, page_size=page_size, has_next=False
        )

    scope = [*scope, archive_service.archive_filter_clause(Wiki, archived)]
    count_subq = select(Wiki.id).where(*scope).subquery()
    total_count = (
        await session.exec(select(func.count()).select_from(count_subq))
    ).one()

    stmt = select(Wiki).where(*scope).options(*wikis_service.list_loader_options())
    stmt = tool_listing.apply_tool_order(
        stmt,
        Wiki,
        sort_by,
        sort_dir,
        default=[Wiki.updated_at.desc(), Wiki.id.desc()],
    )
    if page_size > 0:
        stmt = stmt.offset((page - 1) * page_size).limit(page_size)
    wikis = (await session.exec(stmt)).unique().all()
    await _annotate(session, list(wikis))

    items = [serialize_wiki_summary(w, user_id=current_user.id) for w in wikis]
    has_next = page_size > 0 and page * page_size < total_count
    return WikiListResponse(
        items=items,
        total_count=total_count,
        page=page,
        page_size=page_size,
        has_next=has_next,
    )


@router.get("/counts/by-initiative", response_model=InitiativeGroupedCountsResponse)
async def get_wiki_counts_by_initiative(
    session: RLSSessionDep,
    current_user: CurrentUserDep,
    guild_context: GuildContextDep,
) -> InitiativeGroupedCountsResponse:
    """Visible-wiki counts grouped by initiative, for the sidebar badges."""
    conditions = [
        Wiki.guild_id == guild_context.guild_id,
        Wiki.initiative_id.in_(
            select(Initiative.id).where(Initiative.wikis_enabled == True)  # noqa: E712
        ),
        permissions_service.granted_scope_clause(
            Tool.wiki,
            Wiki.id,
            current_user.id,
            guild_id=guild_context.guild_id,
        ),
    ]
    statement = (
        select(Wiki.initiative_id, func.count(Wiki.id))
        .where(*conditions)
        .group_by(Wiki.initiative_id)
    )
    rows = (await session.exec(statement)).all()
    return InitiativeGroupedCountsResponse(
        counts={initiative_id: count for initiative_id, count in rows}
    )


@router.get("/{wiki_id}", response_model=WikiRead)
async def read_wiki(
    wiki_id: int,
    session: RLSSessionDep,
    current_user: CurrentUserDep,
    guild_context: GuildContextDep,
) -> WikiRead:
    await resource_access.load_authorized(
        session, Tool.wiki, wiki_id, current_user, guild_context
    )
    hydrated = await _refetch_wiki(session, wiki_id, user_id=current_user.id)
    return serialize_wiki(hydrated, user_id=current_user.id)


@router.post("/", response_model=WikiRead, status_code=status.HTTP_201_CREATED)
async def create_wiki(
    wiki_in: WikiCreate,
    session: RLSSessionDep,
    current_user: CurrentUserDep,
    guild_context: GuildContextDep,
) -> WikiRead:
    """Create a wiki. Requires create_wikis permission on the initiative (or
    guild admin); the creator gets the owner grant."""
    initiative = await _get_initiative_for_wiki(session, wiki_in.initiative_id)
    if not initiative.wikis_enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=Tool.wiki.feature_disabled_code,
        )
    await resource_access.require_create(
        session, Tool.wiki, initiative, current_user, guild_context
    )

    wiki = Wiki(
        guild_id=guild_context.guild_id,
        initiative_id=initiative.id,
        created_by=current_user.id,
        name=wiki_in.name.strip(),
        description=(wiki_in.description or "").strip() or None,
    )
    session.add(wiki)
    await session.flush()

    session.add(
        ResourceGrant(
            resource_type="wiki",
            resource_id=wiki.id,
            user_id=current_user.id,
            role_id=None,
            level=ResourceAccessLevel.owner,
            guild_id=guild_context.guild_id,
            initiative_id=initiative.id,
        )
    )
    await permissions_service.replace_resource_grants(
        session,
        resource_type="wiki",
        resource_id=wiki.id,
        guild_id=guild_context.guild_id,
        initiative_id=initiative.id,
        owner_id=current_user.id,
        grants=wiki_in.grants,
    )
    if wiki_in.tag_ids:
        await tags_service.set_entity_tags(
            session,
            tags_service.TOOL_TAG_LINKS[Tool.wiki],
            guild_id=guild_context.guild_id,
            entity_id=wiki.id,
            tag_ids=wiki_in.tag_ids,
        )
    await session.commit()
    hydrated = await _refetch_wiki(session, wiki.id, user_id=current_user.id)
    return serialize_wiki(hydrated, user_id=current_user.id)


@router.patch("/{wiki_id}", response_model=WikiRead)
async def update_wiki(
    wiki_id: int,
    wiki_in: WikiUpdate,
    session: RLSSessionDep,
    current_user: CurrentUserDep,
    guild_context: GuildContextDep,
) -> WikiRead:
    wiki = await resource_access.load_authorized(
        session, Tool.wiki, wiki_id, current_user, guild_context, access="write"
    )
    data = wiki_in.model_dump(exclude_unset=True)

    if "name" in data and data["name"] is not None:
        wiki.name = data["name"].strip()
    if "description" in data:
        wiki.description = (data["description"] or "").strip() or None
    # Both of these name one of the wiki's own pages, and neither is believed
    # without checking — a page id from another wiki would otherwise point this
    # wiki at somebody else's words.
    for field, refusal in (
        ("home_page_id", WikiMessages.HOME_NOT_IN_WIKI),
        ("template_page_id", WikiMessages.TEMPLATE_NOT_IN_WIKI),
    ):
        if field not in data:
            continue
        page_id = data[field]
        if page_id is not None:
            page = await wikis_service.get_page(session, wiki.id, page_id)
            if page is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST, detail=refusal
                )
        setattr(wiki, field, page_id)

    # The settings proper: each is written exactly when it was sent.
    for field in (
        "page_order",
        "show_page_counts",
        "contents_depth",
        "show_connections",
        "reading_width",
    ):
        if field in data and data[field] is not None:
            setattr(wiki, field, data[field])
    if "accent_color" in data:
        setattr(wiki, "accent_color", (data["accent_color"] or "").strip() or None)

    session.add(wiki)
    await session.commit()
    hydrated = await _refetch_wiki(session, wiki.id, user_id=current_user.id)
    return serialize_wiki(hydrated, user_id=current_user.id)


@router.delete("/{wiki_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_wiki(
    wiki_id: int,
    session: RLSSessionDep,
    current_user: CurrentUserDep,
    guild_context: GuildContextDep,
) -> None:
    from app.services.platform import guilds as guilds_service

    wiki = await resource_access.load_authorized(
        session, Tool.wiki, wiki_id, current_user, guild_context, require_owner=True
    )
    retention_days = await guilds_service.get_guild_retention_days(
        session, guild_context.guild_id
    )
    await soft_delete_service.soft_delete_entity(
        session,
        wiki,
        deleted_by_user_id=current_user.id,
        retention_days=retention_days,
    )
    await session.commit()


@router.put("/{wiki_id}/grants", response_model=WikiRead)
async def set_wiki_grants(
    wiki_id: int,
    grants: List[ResourceGrantSchema],
    session: RLSSessionDep,
    current_user: CurrentUserDep,
    guild_context: GuildContextDep,
) -> WikiRead:
    await resource_access.set_resource_grants(
        session, Tool.wiki, wiki_id, current_user, guild_context, grants
    )
    hydrated = await _refetch_wiki(session, wiki_id, user_id=current_user.id)
    return serialize_wiki(hydrated, user_id=current_user.id)


@router.post("/{wiki_id}/view", response_model=RecentViewWrite)
async def record_wiki_view(
    wiki_id: int,
    session: RLSSessionDep,
    current_user: CurrentUserDep,
    guild_context: GuildContextDep,
) -> RecentViewWrite:
    wiki = await resource_access.load_authorized(
        session, Tool.wiki, wiki_id, current_user, guild_context
    )
    record = await recent_views_service.record_view(
        session,
        user_id=current_user.id,
        entity_type="wiki",
        entity_id=wiki.id,
        persist=not guild_context.is_pam,
        limit=current_user.recent_tabs_limit,
    )
    return RecentViewWrite(
        entity_type="wiki",
        entity_id=wiki.id,
        last_viewed_at=record.last_viewed_at,
    )


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------


@router.get("/{wiki_id}/pages", response_model=WikiPageTree)
async def list_wiki_pages(
    wiki_id: int,
    session: RLSSessionDep,
    current_user: CurrentUserDep,
    guild_context: GuildContextDep,
) -> WikiPageTree:
    """Every page of a wiki, in reading order.

    The whole list in one response: the navigation draws all of it, and these
    rows carry no bodies.
    """
    wiki = await resource_access.load_authorized(
        session, Tool.wiki, wiki_id, current_user, guild_context
    )
    rows = await wikis_service.load_list(
        session, wiki, include_drafts=_may_write(wiki, current_user)
    )
    await tags_service.annotate_tags(
        session, [row for row in rows if isinstance(row, WikiPage)]
    )
    # The position each row is SERVED with is its place in the list as drawn —
    # a document's is kept on the wiki and a page's in its own column, and
    # neither is what a client counts with.
    items = [
        serialize_wiki_page_summary(row)
        if isinstance(row, WikiPage)
        else serialize_document_as_page(row, wiki_id=wiki.id, position=spot)
        for spot, row in enumerate(rows)
    ]
    return WikiPageTree(items=items)


@router.put(
    "/{wiki_id}/documents/{document_id}",
    response_model=WikiPageTree,
)
async def add_document_to_wiki(
    wiki_id: int,
    document_id: int,
    session: RLSSessionDep,
    current_user: CurrentUserDep,
    guild_context: GuildContextDep,
) -> WikiPageTree:
    """Put an existing document in this wiki.

    Two gates, because two things are involved: write on the wiki, because the
    wiki is what gains a page, and read on the document, because you cannot put
    something in front of people that you cannot see yourself.

    The document is not moved or copied. It joins by an edge — ``document
    part_of wiki`` — so it keeps its address, its sharing and its history, and
    goes on belonging to whatever else it already belonged to.
    """
    wiki = await resource_access.load_authorized(
        session, Tool.wiki, wiki_id, current_user, guild_context, access="write"
    )
    document = await resource_access.load_authorized(
        session, Tool.document, document_id, current_user, guild_context
    )

    await relationships_service.create(
        session,
        source=relationships_service.Endpoint(SearchEntityType.document, document.id),
        relationship_type=RelationshipType.part_of,
        target=relationships_service.Endpoint(SearchEntityType.wiki, wiki.id),
        created_by=current_user.id,
    )
    await session.commit()
    return await list_wiki_pages(wiki_id, session, current_user, guild_context)


@router.post("/{wiki_id}/documents/{document_id}/move", response_model=WikiPageTree)
async def move_wiki_document(
    wiki_id: int,
    document_id: int,
    move: WikiPageMove,
    session: RLSSessionDep,
    current_user: CurrentUserDep,
    guild_context: GuildContextDep,
) -> WikiPageTree:
    """Put a borrowed document somewhere else in this wiki's list.

    At the top of it, always: which page a document is filed under would be a
    fact about a document that belongs to other places too, and this wiki does
    not get to decide that.

    Write on the wiki is the whole gate, and read on the document is implied by
    it already being in a wiki this person may write: where it sits is a
    decision about the wiki, not a change to the document — which is why the
    document itself is never written.
    """
    wiki = await resource_access.load_authorized(
        session, Tool.wiki, wiki_id, current_user, guild_context, access="write"
    )
    documents = await wikis_service.linked_documents(session, wiki.id)
    document = next((d for d in documents if d.id == document_id), None)
    if document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=WikiMessages.PAGE_NOT_FOUND
        )

    await wikis_service.place_in_list(session, wiki, document, move.position)
    await session.commit()
    return await list_wiki_pages(wiki_id, session, current_user, guild_context)


@router.delete(
    "/{wiki_id}/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def remove_document_from_wiki(
    wiki_id: int,
    document_id: int,
    session: RLSSessionDep,
    current_user: CurrentUserDep,
    guild_context: GuildContextDep,
) -> None:
    """Take a document back out of this wiki.

    The wiki loses a page; the document loses nothing. Write on the wiki is the
    only gate — this is a decision about what the wiki contains.
    """
    wiki = await resource_access.load_authorized(
        session, Tool.wiki, wiki_id, current_user, guild_context, access="write"
    )
    edge = await relationships_service.find(
        session,
        source=relationships_service.Endpoint(SearchEntityType.document, document_id),
        relationship_type=RelationshipType.part_of,
        target=relationships_service.Endpoint(SearchEntityType.wiki, wiki.id),
    )
    if edge is not None:
        await relationships_service.remove(session, edge, removed_by=current_user.id)
        wikis_service.forget_document_placement(wiki, document_id)
        session.add(wiki)
        await session.commit()


@router.post(
    "/{wiki_id}/pages",
    response_model=WikiPageRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_wiki_page(
    wiki_id: int,
    page_in: WikiPageCreate,
    session: RLSSessionDep,
    current_user: CurrentUserDep,
    guild_context: GuildContextDep,
) -> WikiPageRead:
    """Add a page. Write access on the wiki is the whole gate — a page is the
    wiki's content.

    It arrives as a draft unless the request says otherwise: for as long as it
    takes to write one, a new page is empty and unnamed, and the people who
    only read this wiki have no use for that.
    """
    wiki = await resource_access.load_authorized(
        session, Tool.wiki, wiki_id, current_user, guild_context, access="write"
    )
    title = (page_in.title or "").strip()

    if page_in.parent_page_id is not None:
        parent = await wikis_service.get_page(session, wiki.id, page_in.parent_page_id)
        if parent is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=WikiMessages.PAGE_NOT_FOUND,
            )

    # A new page starts as a copy of the wiki's template, where it has one and
    # the request did not bring a body of its own. That is what keeps two
    # hundred character pages the same shape without anybody policing it.
    content = page_in.content
    if content is None and wiki.template_page_id is not None:
        template = await wikis_service.get_page(session, wiki.id, wiki.template_page_id)
        if template is not None:
            content = deepcopy(template.content or {})

    page = WikiPage(
        guild_id=guild_context.guild_id,
        wiki_id=wiki.id,
        created_by=current_user.id,
        parent_page_id=page_in.parent_page_id,
        position=await wikis_service.next_position(
            session, wiki, page_in.parent_page_id
        ),
        is_draft=page_in.is_draft,
        title=title,
        slug=await wikis_service.unique_page_slug(session, wiki.id, title),
        content=content or {},
    )
    session.add(page)
    await session.flush()

    if page_in.tag_ids:
        await tags_service.set_entity_tags(
            session,
            tags_service.TAG_LINKS["wiki_page"],
            guild_id=guild_context.guild_id,
            entity_id=page.id,
            tag_ids=page_in.tag_ids,
        )

    # What the body names becomes `references` edges, the same way a document's
    # does — which is what makes the backlinks below say anything.
    await content_references.sync_for_entity(
        session,
        relationships_service.Endpoint(SearchEntityType.wiki_page, page.id),
        body=page.content,
        author_id=current_user.id,
    )
    await session.commit()
    await session.refresh(page)
    return serialize_wiki_page(page)


@router.get("/{wiki_id}/pages/{page_id}", response_model=WikiPageRead)
async def read_wiki_page(
    wiki_id: int,
    page_id: int,
    session: RLSSessionDep,
    current_user: CurrentUserDep,
    guild_context: GuildContextDep,
) -> WikiPageRead:
    _wiki, page = await _load_page(
        session, wiki_id, page_id, current_user, guild_context
    )
    await tags_service.annotate_tags(session, [page])
    return serialize_wiki_page(page)


@router.patch("/{wiki_id}/pages/{page_id}", response_model=WikiPageRead)
async def update_wiki_page(
    wiki_id: int,
    page_id: int,
    page_in: WikiPageUpdate,
    session: RLSSessionDep,
    current_user: CurrentUserDep,
    guild_context: GuildContextDep,
) -> WikiPageRead:
    _wiki, page = await _load_page(
        session, wiki_id, page_id, current_user, guild_context, access="write"
    )
    data = page_in.model_dump(exclude_unset=True)

    if "is_draft" in data and data["is_draft"] is not None:
        page.is_draft = data["is_draft"]
    if "title" in data and data["title"] is not None:
        title = data["title"].strip()
        if title != page.title:
            page.title = title
            page.slug = await wikis_service.unique_page_slug(
                session, page.wiki_id, title, exclude_page_id=page.id
            )
    if "content" in data and data["content"] is not None:
        page.content = data["content"]

    session.add(page)
    await session.flush()

    if "tag_ids" in data and data["tag_ids"] is not None:
        await tags_service.set_entity_tags(
            session,
            tags_service.TAG_LINKS["wiki_page"],
            guild_id=page.guild_id,
            entity_id=page.id,
            tag_ids=data["tag_ids"],
        )
    if "content" in data:
        await content_references.sync_for_entity(
            session,
            relationships_service.Endpoint(SearchEntityType.wiki_page, page.id),
            body=page.content,
            author_id=current_user.id,
        )
    await session.commit()
    await session.refresh(page)
    await tags_service.annotate_tags(session, [page])
    return serialize_wiki_page(page)


@router.post("/{wiki_id}/pages/{page_id}/move", response_model=WikiPageRead)
async def move_wiki_page(
    wiki_id: int,
    page_id: int,
    move: WikiPageMove,
    session: RLSSessionDep,
    current_user: CurrentUserDep,
    guild_context: GuildContextDep,
) -> WikiPageRead:
    """File a page and place it there in one request — what a drag is.

    Only the page's new neighbours are renumbered: a position means something
    among the pages filed together and nothing across the wiki.
    """
    wiki, page = await _load_page(
        session, wiki_id, page_id, current_user, guild_context, access="write"
    )
    await wikis_service.validate_reparent(session, page, move.parent_page_id)
    await wikis_service.place_in_list(
        session, wiki, page, move.position, move.parent_page_id
    )
    await session.commit()
    await session.refresh(page)
    return serialize_wiki_page(page)


@router.delete("/{wiki_id}/pages/{page_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_wiki_page(
    wiki_id: int,
    page_id: int,
    session: RLSSessionDep,
    current_user: CurrentUserDep,
    guild_context: GuildContextDep,
) -> None:
    """Send a page to the trash. Its children go with it — a section is put
    away whole."""
    from app.services.platform import guilds as guilds_service

    _wiki, page = await _load_page(
        session, wiki_id, page_id, current_user, guild_context, access="write"
    )
    retention_days = await guilds_service.get_guild_retention_days(
        session, guild_context.guild_id
    )
    # Sub-pages go with it through CASCADE_CHILDREN, the same way a comment
    # thread follows its root.
    await soft_delete_service.soft_delete_entity(
        session,
        page,
        deleted_by_user_id=current_user.id,
        retention_days=retention_days,
    )
    await session.commit()


@router.get("/{wiki_id}/pages/{page_id}/links", response_model=WikiPageLinks)
async def read_wiki_page_links(
    wiki_id: int,
    page_id: int,
    session: RLSSessionDep,
    current_user: CurrentUserDep,
    guild_context: GuildContextDep,
) -> WikiPageLinks:
    """What this page names, and what names it.

    The second half is the backlinks. They are read from the same table the
    ``[[ ]]`` extractor writes to, so a page that somebody linked to from a
    task knows about it without the task having to say so twice.
    """
    _wiki, page = await _load_page(
        session, wiki_id, page_id, current_user, guild_context
    )
    outgoing, incoming = await wikis_service.page_links(session, page)

    async def _links(rows, *, other: str) -> list[WikiPageLink]:
        # Resolve titles one kind at a time rather than one row at a time, and
        # through the shared resolver — which answers only for rows this reader
        # may see, so a link to something hidden from them simply is not shown.
        wanted: dict[str, list[int]] = {}
        for row in rows:
            wanted.setdefault(getattr(row, f"{other}_type"), []).append(
                getattr(row, f"{other}_id")
            )
        found: dict[tuple[str, int], Any] = {}
        for entity_type, ids in wanted.items():
            resolved = await reference_targets.resolve_many(
                session, SearchEntityType(entity_type), ids, user_id=current_user.id
            )
            for entity_id, row in resolved.items():
                found[(entity_type, entity_id)] = row

        links: list[WikiPageLink] = []
        for row in rows:
            entity_type = getattr(row, f"{other}_type")
            entity_id = getattr(row, f"{other}_id")
            target = found.get((entity_type, entity_id))
            if target is None:
                continue
            tool = getattr(target, "tool", None)
            links.append(
                WikiPageLink(
                    entity_type=entity_type,
                    entity_id=entity_id,
                    title=target.title,
                    relationship_type=row.relationship_type,
                    initiative_id=getattr(target, "initiative_id", None),
                    tool=getattr(tool, "value", tool),
                    tool_id=getattr(target, "tool_id", None),
                )
            )
        return links

    return WikiPageLinks(
        outgoing=await _links(outgoing, other="target"),
        incoming=await _links(incoming, other="source"),
    )
