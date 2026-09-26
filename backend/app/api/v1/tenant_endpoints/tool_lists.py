"""Tool lists and their sidebar counts — one pair of routes per tool, mounted once.

``GET /`` and ``GET /counts/by-initiative`` were nine copies each of the same
hundred lines: scope the guild, honour the tool's switch, apply sharing, narrow
by the search box and the tag filter, count, order, page, annotate, serialize.
None of that depends on which tool it is beyond the model, what to eager-load
and how a row becomes a summary — so the pair is mounted per ``Tool`` out of
:data:`TOOL_LISTS` rather than written nine times over. The query itself is
:mod:`app.services.tenant.tool_listing`; the per-tool differences that survive
are the registry's fields, and each is commented where it sits.

**The list and the count use different scope clauses, deliberately.** A list
runs ``permissions.listing_scope_clause``: asked for one initiative by name it
adds nothing, because the content table's own policy has already settled who
may read the row, and a guild admin's authority reaches every initiative in
their community. A count runs ``permissions.granted_scope_clause``: a count is
guild-wide, so there is no single initiative to ask about, and what it answers
is what has been *granted* to the reader — the same rule their sidebar and the
community front page list initiatives by. A badge that counted an admin's whole
guild would not be a badge about them.

Each route keeps the path, method, tag, name, summary and parameters its tool
already had, so the published surface and the generated client are unchanged
but for the ``tag_ids`` filter every tool now accepts.

:data:`TOOL_LISTS` also carries each tool's **single-row** answer — its Read
model and its own re-read-and-serialize — because that is the same per-tool
fact in a different shape, and a second table of it would be one more thing to
keep in step. :mod:`app.api.v1.tenant_endpoints.tool_grants` reads it.
"""

# NOT ``from __future__ import annotations``: the list handlers are built per
# tool from a signature assembled at import time, and the parameter annotations
# have to be real objects for FastAPI to read them.

import inspect
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Annotated, Any, Awaitable, Callable, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.actor_route import ActorRoute
from app.api.deps import (
    ActorContext,
    ActorSessionDep,
    ActorUserDep,
    RLSSessionDep,
    app_scope,
    get_current_active_user,
    GuildContextDep,
)
from app.core.app_scopes import AppScopeAccess, scope_name, tool_resource
from app.api.v1.tenant_endpoints import calendars as calendars_endpoints
from app.api.v1.tenant_endpoints import counters as counters_endpoints
from app.api.v1.tenant_endpoints import dashboards as dashboards_endpoints
from app.api.v1.tenant_endpoints import documents as documents_endpoints
from app.api.v1.tenant_endpoints import galleries as galleries_endpoints
from app.api.v1.tenant_endpoints import posts as posts_endpoints
from app.api.v1.tenant_endpoints import projects as projects_endpoints
from app.api.v1.tenant_endpoints import queues as queues_endpoints
from app.api.v1.tenant_endpoints import wikis as wikis_endpoints
from app.core.messages import DocumentMessages, QueryMessages
from app.core.tools import Tool
from app.db.query import page_has_next
from app.models.platform.user import User
from app.models.tenant.calendar import Calendar
from app.models.tenant.counter import CounterGroup
from app.models.tenant.dashboard import Dashboard
from app.models.tenant.document import Document, DocumentType
from app.models.tenant.gallery import Gallery
from app.models.tenant.initiative import Initiative
from app.models.tenant.post import Post
from app.models.tenant.project import Project
from app.models.tenant.project_order import ProjectOrder
from app.models.tenant.property import PropertyType
from app.schemas.query import FilterOp
from app.models.tenant.queue import Queue
from app.models.tenant.wiki import Wiki
from app.schemas.tenant.calendar import (
    CalendarListResponse,
    CalendarRead,
    serialize_calendar_summary,
)
from app.schemas.tenant.counter import (
    CounterGroupListResponse,
    CounterGroupRead,
    serialize_counter_group_summary,
)
from app.schemas.tenant.dashboard import (
    DashboardListResponse,
    DashboardRead,
    serialize_dashboard_summary,
)
from app.schemas.tenant.document import (
    DocumentListResponse,
    DocumentRead,
)
from app.schemas.tenant.gallery import (
    GalleryListResponse,
    GalleryRead,
    serialize_gallery_summary,
)
from app.schemas.tenant.initiative import InitiativeGroupedCountsResponse
from app.schemas.tenant.post import PostListResponse, PostRead, serialize_post
from app.schemas.tenant.project import ProjectListResponse, ProjectRead
from app.schemas.tenant.queue import (
    QueueListResponse,
    QueueRead,
    serialize_queue_summary,
)
from app.schemas.tenant.wiki import (
    WikiListResponse,
    WikiRead,
    serialize_wiki_summary,
)
from app.services.tenant import archive as archive_service
from app.services.tenant import calendars as calendars_service
from app.services.tenant import counters as counters_service
from app.services.tenant import dashboards as dashboards_service
from app.services.tenant import documents as documents_service
from app.services.tenant import galleries as galleries_service
from app.services.tenant import posts as posts_service
from app.services.tenant import properties as properties_service
from app.services.tenant import queues as queues_service
from app.services.tenant import tags as tags_service
from app.services.tenant import tool_listing
from app.services.tenant import wikis as wikis_service

router = APIRouter(route_class=ActorRoute)

CurrentUserDep = Annotated[User, Depends(get_current_active_user)]


# ---------------------------------------------------------------------------
# What a handler is handed
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ListRequest:
    """One list request: who is asking, where, and with which parameters.

    ``values`` holds every query parameter the tool declared, by name, so a
    per-tool hook reads the ones it asked for without the generic handler
    knowing they exist.
    """

    session: AsyncSession
    #: The person asking; ``None`` when an installed app is.
    user: Optional[User]
    guild_context: ActorContext
    values: dict[str, Any]

    @property
    def guild_id(self) -> int:
        return self.guild_context.guild_id

    @property
    def user_id(self) -> Optional[int]:
        """The person asking, by id; ``None`` for an installed app."""
        return self.guild_context.user_id


# ---------------------------------------------------------------------------
# Query parameters
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ListParam:
    """One query parameter of a tool's list, in the order it is published."""

    name: str
    annotation: Any
    default: Any


_SORT_DIR_DESCRIPTION = "asc (default) or desc."
_ROW_SEARCH_DESCRIPTION = (
    "Full-text match over the row — its name and its description. "
    "Reads the same index the search page does, so a list's filter "
    "box and a search agree about what matches."
)
_TOOL_SORT_DESCRIPTION = (
    "Order by one of: name, initiative, updated_at. Omit for this "
    "tool's own default order."
)


def _initiative_id(description: Optional[str] = None) -> ListParam:
    return ListParam(
        "initiative_id", Optional[int], Query(default=None, description=description)
    )


def search_param(description: Optional[str] = _ROW_SEARCH_DESCRIPTION) -> ListParam:
    return ListParam(
        "search", Optional[str], Query(default=None, description=description)
    )


def sort_by_param(description: Optional[str] = _TOOL_SORT_DESCRIPTION) -> ListParam:
    return ListParam(
        "sort_by", Optional[str], Query(default=None, description=description)
    )


def sort_dir_param(description: Optional[str] = _SORT_DIR_DESCRIPTION) -> ListParam:
    return ListParam(
        "sort_dir", Optional[str], Query(default=None, description=description)
    )


def _tag_ids(tool: Tool, description: Optional[str] = None) -> ListParam:
    """Every tool is taggable, so every list narrows by tag — ANY-of, the way a
    shelf is narrowed by what somebody remembers about a row rather than by
    everything that is true of it."""
    if description is None:
        plural = tool.plural.replace("_", " ")
        description = f"Only {plural} carrying any of these tags."
    return ListParam(
        "tag_ids", Optional[List[int]], Query(default=None, description=description)
    )


def _archived(described: bool = True) -> ListParam:
    return ListParam(
        "archived",
        Optional[bool],
        Query(
            default=None,
            description=archive_service.ARCHIVED_QUERY_DESCRIPTION
            if described
            else None,
        ),
    )


def page_param() -> ListParam:
    return ListParam("page", int, Query(default=1, ge=1))


def page_size_param(
    default: int, *, ge: int, le: int, description: Optional[str] = None
) -> ListParam:
    """A tool's page defaults, declared where they can be compared.

    They differ on purpose — a board of posts carries whole bodies and pages in
    fives, a dashboard list is a sidebar and fetches a hundred — and the
    clients depend on them, so they are stated per tool rather than averaged.
    """
    return ListParam(
        "page_size", int, Query(default=default, ge=ge, le=le, description=description)
    )


# ---------------------------------------------------------------------------
# The registry
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ToolListSpec:
    """Everything about one tool's API surface that the shared routes do not know.

    For the list: the model and its initiative switch, what a page eager-loads,
    how a row becomes a summary, the order a request that names none falls back
    to, the parameters the route publishes, and the page defaults (in
    ``params``). For the single row a write answers with: the Read model and
    the tool's own re-read-and-serialize (``read_model`` / ``read_row``), which
    the shared sharing route reads.
    """

    tool: Tool
    model: Any
    #: The initiative's master switch for this tool. Checked against
    #: ``Tool.view_permission`` below, so the table can be read at a glance
    #: without becoming a second source of truth for the column's name.
    enabled_column: Any
    response_model: Any
    #: (req) -> eager loads for the page query
    loader_options: Callable[["ListRequest"], list]
    #: (req) -> ORDER BY when the request asks for no sort
    default_order: Callable[["ListRequest"], list]
    #: async (spec, req, rows) -> the response's ``items``
    serialize: Callable[..., Awaitable[list]]
    params: tuple[ListParam, ...]
    #: The tool's detail Read model — the single row a write answers with.
    read_model: Any
    #: async (session, row_id, user, guild_context) -> ``read_model``. The
    #: tool's own re-read-and-serialize, which the shared sharing route
    #: (``tool_grants.py``) answers with.
    read_row: Callable[..., Awaitable[Any]]
    #: The sharing route's published description, per tool.
    grants_doc: Optional[str] = None
    #: async (spec, req) -> the whole WHERE. Defaults to the shared set.
    conditions: Optional[Callable[..., Awaitable[list]]] = None
    #: Rows belonging to the guild rather than to an initiative (guild calendars).
    guild_level_rows: bool = False
    #: Send a reader whose page has fallen off the end back to the first one.
    clamp_page: bool = False
    #: Sort fields this tool offers beyond the shared three.
    extra_sort_fields: Optional[dict[str, Any]] = None
    #: (req) -> statement transform applied before ORDER BY reads it.
    refine: Optional[Callable[["ListRequest"], Callable[[Any], Any]]] = None
    #: (user, guild_context) -> extra WHERE legs for the counts route.
    counts_conditions: Optional[Callable[..., list]] = None
    #: (req) -> extra fields on the list response.
    response_extras: Optional[Callable[["ListRequest"], dict]] = None
    list_doc: Optional[str] = None
    counts_doc: Optional[str] = None
    #: The OpenAPI tag, where it is not the tool's own plural.
    tag: Optional[str] = None
    #: Whether an installed app may list this tool, under its read scope.
    serves_apps: bool = True

    def __post_init__(self) -> None:
        # The switch column is spelled out in the table for readability; this
        # keeps it from drifting from the name the Tool enum derives
        # everywhere else.
        if self.enabled_column.key != self.tool.view_permission:
            raise ValueError(
                f"{self.tool.value}: enabled_column is "
                f"{self.enabled_column.key!r}, expected "
                f"{self.tool.view_permission!r}"
            )


# ---------------------------------------------------------------------------
# Shared hook bodies
# ---------------------------------------------------------------------------


async def _default_conditions(spec: ToolListSpec, req: ListRequest) -> list:
    """The WHERE every tool list shares, plus the archive answer."""
    values = req.values
    return [
        *tool_listing.base_conditions(
            spec.tool,
            spec.model,
            spec.enabled_column,
            req.user_id,
            context=req.guild_context,
            initiative_id=values.get("initiative_id"),
            search=values.get("search"),
            tag_ids=values.get("tag_ids"),
            guild_level_rows=spec.guild_level_rows,
        ),
        archive_service.archive_filter_clause(spec.model, values.get("archived")),
    ]


def _summaries(serializer: Callable[..., Any]) -> Callable[..., Awaitable[list]]:
    """The ordinary page: tag the rows, then turn each into its summary."""

    async def serialize(spec: ToolListSpec, req: ListRequest, rows: list) -> list:
        await tags_service.annotate_tags(req.session, rows)
        return [
            serializer(row, context=req.guild_context, user_id=req.user_id)
            for row in rows
        ]

    return serialize


def _loads(loader: Callable[[], list]) -> Callable[[ListRequest], list]:
    """A tool whose eager loads do not depend on the request."""
    return lambda _req: loader()


def _order(*columns: Any) -> Callable[[ListRequest], list]:
    """A tool whose fallback order is fixed."""
    return lambda _req: list(columns)


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------


async def _project_conditions(spec: ToolListSpec, req: ListRequest) -> list:
    # ``template`` is the projects list's own filter: a blueprint is not work
    # in progress, so it is left out unless it is asked for by name.
    values = req.values
    return projects_endpoints.visible_project_conditions(
        req.user_id,
        context=req.guild_context,
        archived=values.get("archived"),
        template=values.get("template"),
        search=values.get("search"),
        tag_ids=values.get("tag_ids"),
        initiative_id=values.get("initiative_id"),
    )


def _project_refine(req: ListRequest) -> Callable[[Any], Any]:
    """Join each reader's own manual positions, which the default order reads.

    An installed app keeps no positions of its own, so its list is left as it
    is and ordered by id (:func:`_project_order`)."""
    if req.user_id is None:
        return lambda statement: statement
    return lambda statement: statement.outerjoin(
        ProjectOrder,
        and_(
            ProjectOrder.project_id == Project.id,
            ProjectOrder.user_id == req.user_id,
        ),
    )


def _project_order(req: ListRequest) -> list:
    """The reader's own manual order, then id; by id alone for an app."""
    if req.user_id is None:
        return [Project.id.asc()]
    return [ProjectOrder.sort_order.asc().nulls_last(), Project.id.asc()]


async def _serialize_projects(spec: ToolListSpec, req: ListRequest, rows: list) -> list:
    return await projects_endpoints.serialize_project_page(
        req.session, req.user_id, rows, slim=bool(req.values.get("slim"))
    )


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------


async def _document_conditions(spec: ToolListSpec, req: ListRequest) -> list:
    values = req.values
    if values.get("initiative_id") is not None:
        # The only list that answers 404 for an initiative outside the guild
        # rather than an empty page — its callers address a known initiative.
        await documents_endpoints.get_initiative_or_404(
            req.session,
            initiative_id=values["initiative_id"],
        )
    ids = values.get("ids")
    if ids is not None and len(ids) > documents_endpoints.MAX_DOCUMENT_IDS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=DocumentMessages.TOO_MANY_IDS,
        )
    conditions = documents_endpoints.visible_document_conditions(
        req.guild_context,
        req.user_id,
        initiative_id=values.get("initiative_id"),
        ids=ids,
        search=values.get("search"),
        tag_ids=values.get("tag_ids"),
        untagged=values.get("untagged"),
        is_template=values.get("is_template"),
        document_type=values.get("document_type"),
    )
    conditions.append(
        archive_service.archive_filter_clause(Document, values.get("archived"))
    )
    conditions.extend(
        await _property_filter_clauses(
            req.session,
            values.get("property_filters"),
            names_people=req.user is not None,
        )
    )
    return conditions


async def _property_filter_clauses(
    session: AsyncSession, raw: Optional[str], *, names_people: bool
) -> list:
    """WHERE clauses for the typed property filters a document list may carry.

    Loads the definitions the caller can see, then hands the compilation to the
    shared helper so documents, tasks and events agree about what each operator
    means. A filter on a person-valued property takes row ids, which an
    installed app does not hold, so it is left to people (``names_people``),
    as the task list does.
    """
    try:
        parsed = properties_service.parse_property_filters(raw)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=QueryMessages.INVALID_CONDITIONS,
        )
    if not parsed:
        return []
    definitions = await properties_service.load_definitions_by_ids(
        session, [condition.property_id for condition in parsed]
    )
    if not names_people and any(
        condition.op is not FilterOp.is_null
        and (definition := definitions.get(condition.property_id)) is not None
        and definition.type is PropertyType.user_reference
        for condition in parsed
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=QueryMessages.INVALID_CONDITIONS,
        )
    return properties_service.build_property_filter_clauses(
        "document", parsed, definitions
    )


async def _serialize_documents(
    spec: ToolListSpec, req: ListRequest, rows: list
) -> list:
    return await documents_endpoints.serialize_document_page(
        req.session, req.user_id, rows
    )


# ---------------------------------------------------------------------------
# Calendars
# ---------------------------------------------------------------------------


async def _calendar_conditions(spec: ToolListSpec, req: ListRequest) -> list:
    conditions = await _default_conditions(spec, req)
    if req.values.get("scope") == "guild":
        # The opposite of the unfiltered list, which is everything in scope, so
        # it is asked for by name rather than inferred from an absent
        # ``initiative_id``.
        conditions.append(Calendar.initiative_id.is_(None))
    return conditions


# ---------------------------------------------------------------------------
# Posts
# ---------------------------------------------------------------------------


async def _post_conditions(spec: ToolListSpec, req: ListRequest) -> list:
    values = req.values
    conditions = posts_endpoints.board_conditions(
        req.user_id,
        context=req.guild_context,
        initiative_id=values.get("initiative_id"),
        search=values.get("search"),
        tag_ids=values.get("tag_ids"),
        unread=bool(values.get("unread")),
    )
    conditions.append(
        archive_service.archive_filter_clause(Post, values.get("archived"))
    )
    if values.get("until") is not None:
        conditions.append(posts_service.anchored_clause(values["until"]))
    return conditions


def _post_order(req: ListRequest) -> list:
    return posts_service.board_order(anchored=req.values.get("until") is not None)


async def _serialize_posts(spec: ToolListSpec, req: ListRequest, rows: list) -> list:
    # One grouped query each for the page, so a board of twenty asks a handful
    # of times rather than forty.
    session = req.session
    await tags_service.annotate_tags(session, rows)
    # An installed app's page carries no reactions, read state or ballots.
    await posts_endpoints.annotate_post_rows(session, rows, user_id=req.user_id)
    return [
        serialize_post(post, context=req.guild_context, user_id=req.user_id)
        for post in rows
    ]


# ---------------------------------------------------------------------------
# Galleries and wikis
# ---------------------------------------------------------------------------


async def _serialize_galleries(
    spec: ToolListSpec, req: ListRequest, rows: list
) -> list:
    await galleries_endpoints.annotate_gallery_rows(req.session, rows)
    return [
        serialize_gallery_summary(row, context=req.guild_context, user_id=req.user_id)
        for row in rows
    ]


async def _serialize_wikis(spec: ToolListSpec, req: ListRequest, rows: list) -> list:
    await wikis_endpoints.annotate_wiki_rows(req.session, rows)
    return [
        serialize_wiki_summary(row, context=req.guild_context, user_id=req.user_id)
        for row in rows
    ]


# ---------------------------------------------------------------------------
# One row per tool
# ---------------------------------------------------------------------------


TOOL_LISTS: dict[Tool, ToolListSpec] = {
    Tool.project: ToolListSpec(
        tool=Tool.project,
        read_model=ProjectRead,
        read_row=projects_endpoints.read_after_write,
        grants_doc=(
            "Replace the project's entire sharing state in one call — the body is the\n"
            "full list of grants (all-initiative-members / per-user / per-role). Every\n"
            "non-owner grant is rebuilt from it; the owner is always preserved.\n"
            "\n"
            "Anyone the new grants drop below write access is unassigned from the project's\n"
            "tasks (you can't be assigned to tasks you can't edit)."
        ),
        model=Project,
        enabled_column=Initiative.projects_enabled,
        response_model=ProjectListResponse,
        loader_options=lambda req: projects_endpoints.project_load_options(
            slim=bool(req.values.get("slim"))
        ),
        # No sort asked for keeps the per-user manual order the projects page
        # drags into place; a sort replaces it for this request only.
        default_order=_project_order,
        serialize=_serialize_projects,
        conditions=_project_conditions,
        refine=_project_refine,
        clamp_page=True,
        counts_conditions=lambda user, guild_context: [Project.is_template.is_(False)],
        params=(
            _archived(described=False),
            ListParam("template", Optional[bool], Query(default=None)),
            search_param(),
            _initiative_id(
                "Only projects in this initiative. Omit for every initiative "
                "the caller can see."
            ),
            ListParam(
                "slim",
                bool,
                Query(
                    default=False,
                    description=(
                        "Return a lightweight projection (id, name, icon, "
                        "initiative_id, can) without documents, "
                        "grants, tags, or the nested initiative. For project "
                        "pickers and other list-only callers."
                    ),
                ),
            ),
            sort_by_param(
                "Order by one of: name, initiative, updated_at. Omit to keep "
                "the reader's own manual order."
            ),
            sort_dir_param(),
            _tag_ids(Tool.project),
            page_param(),
            page_size_param(0, ge=0, le=100),
        ),
        counts_doc=(
            "Visible-project counts grouped by initiative.\n"
            "\n"
            "Lightweight endpoint for initiative landing-card badges — same\n"
            "visibility rules as the default project list (non-archived,\n"
            "non-template), one GROUP BY instead of walking the full corpus."
        ),
    ),
    Tool.document: ToolListSpec(
        tool=Tool.document,
        read_model=DocumentRead,
        read_row=documents_endpoints.read_after_write,
        grants_doc=(
            "Replace the document's entire sharing state in one call — the body is the\n"
            "full list of grants (all-initiative-members / per-user / per-role). Every\n"
            "non-owner grant is rebuilt from it; the owner is always preserved."
        ),
        model=Document,
        enabled_column=Initiative.documents_enabled,
        response_model=DocumentListResponse,
        loader_options=_loads(documents_service.list_loader_options),
        default_order=_order(Document.updated_at.desc(), Document.id.desc()),
        serialize=_serialize_documents,
        conditions=_document_conditions,
        # The one tool that also sorts by when a row was written — a document
        # list is a filing cabinet, and "newest first" is how you read one.
        extra_sort_fields={"created_at": Document.created_at},
        response_extras=lambda req: {
            "sort_by": req.values.get("sort_by"),
            "sort_dir": req.values.get("sort_dir"),
        },
        params=(
            _initiative_id(),
            ListParam(
                "ids",
                Optional[List[int]],
                Query(
                    default=None,
                    description=(
                        "Filter to specific document IDs — for hydrating a known "
                        "set of documents without walking a collection. Maximum "
                        f"{documents_endpoints.MAX_DOCUMENT_IDS} IDs."
                    ),
                ),
            ),
            search_param(description=None),
            _tag_ids(Tool.document, description="Filter by tag IDs"),
            ListParam(
                "untagged",
                Optional[bool],
                Query(default=None, description="Filter to documents with no tags"),
            ),
            ListParam(
                "is_template",
                Optional[bool],
                Query(
                    default=None,
                    description="Filter to template (or non-template) documents",
                ),
            ),
            ListParam(
                "document_type",
                Optional[DocumentType],
                Query(default=None, description="Filter by document type"),
            ),
            ListParam(
                "property_filters",
                Optional[str],
                Query(
                    default=None,
                    description=(
                        "JSON-encoded list of property-value filters, e.g. "
                        '`[{"property_id": 12, "op": "eq", "value": "live"}]`. '
                        f"Maximum {properties_service.MAX_PROPERTY_FILTERS} "
                        "conditions per request."
                    ),
                ),
            ),
            page_param(),
            page_size_param(20, ge=0, le=100),
            sort_by_param("Order by one of: name, initiative, updated_at, created_at."),
            sort_dir_param(),
            _archived(),
        ),
        list_doc=(
            "List documents in the active guild visible to the current user.\n"
            "\n"
            "DAC: Documents with explicit DocumentPermission or role-based "
            "permission.\n"
            "\n"
            "Pagination: page_size=0 serves the full set in server-bounded "
            "windows —\n"
            "walk page=1,2,... until has_next is false.\n"
            "\n"
            'Cross-guild "my documents" lives under /me/documents (see '
            "list_my_documents)."
        ),
        counts_doc=(
            "Visible-document counts grouped by initiative.\n"
            "\n"
            "Lightweight endpoint for the sidebar and initiative landing-card\n"
            "badges — same visibility filters as the document list, one GROUP BY\n"
            "instead of walking the full corpus."
        ),
    ),
    Tool.queue: ToolListSpec(
        tool=Tool.queue,
        read_model=QueueRead,
        read_row=queues_endpoints.read_after_write,
        grants_doc=(
            "Replace the queue's entire sharing state in one call — the body is the\n"
            "full list of grants (all-initiative-members / per-user / per-role). Every\n"
            "non-owner grant is rebuilt from it; the owner is always preserved."
        ),
        model=Queue,
        enabled_column=Initiative.queues_enabled,
        response_model=QueueListResponse,
        loader_options=_loads(queues_service.list_loader_options),
        default_order=_order(Queue.updated_at.desc(), Queue.id.desc()),
        serialize=_summaries(serialize_queue_summary),
        params=(
            _initiative_id(),
            search_param(),
            sort_by_param(),
            sort_dir_param(),
            _tag_ids(Tool.queue),
            _archived(),
            page_param(),
            page_size_param(20, ge=1, le=100),
        ),
        list_doc=(
            "List queues visible to the current user.\n"
            "\n"
            "DAC: Queues with explicit QueuePermission or role-based permission.\n"
            "Guild admins see all queues."
        ),
        counts_doc=(
            "Visible-queue counts grouped by initiative.\n"
            "\n"
            "Lightweight endpoint for the sidebar badges — same visibility rules\n"
            "as the queue list (queues-enabled initiatives, DAC), one GROUP BY\n"
            "instead of a capped list page."
        ),
    ),
    Tool.counter_group: ToolListSpec(
        tool=Tool.counter_group,
        read_model=CounterGroupRead,
        read_row=counters_endpoints.read_after_write,
        grants_doc=(
            "Replace the counter group's entire sharing state in one call — the body\n"
            "is the full list of grants (all-initiative-members / per-user / per-role).\n"
            "Every non-owner grant is rebuilt from it; the owner is always preserved."
        ),
        model=CounterGroup,
        enabled_column=Initiative.counter_groups_enabled,
        response_model=CounterGroupListResponse,
        loader_options=_loads(counters_service.list_loader_options),
        default_order=_order(CounterGroup.updated_at.desc(), CounterGroup.id.desc()),
        serialize=_summaries(serialize_counter_group_summary),
        # The counters router carries the wider "counters" tag, which the
        # individual counters underneath these groups share.
        tag="counters",
        params=(
            _initiative_id(),
            search_param(),
            sort_by_param(),
            sort_dir_param(),
            _tag_ids(Tool.counter_group),
            _archived(),
            page_param(),
            page_size_param(20, ge=1, le=100),
        ),
        counts_doc=(
            "Visible counter-group counts grouped by initiative.\n"
            "\n"
            "Lightweight endpoint for the sidebar badges — same visibility rules\n"
            "as the counter-group list (counters-enabled initiatives, DAC), one\n"
            "GROUP BY instead of a capped list page."
        ),
    ),
    Tool.calendar: ToolListSpec(
        tool=Tool.calendar,
        read_model=CalendarRead,
        read_row=calendars_endpoints.read_after_write,
        grants_doc=(
            "Replace the calendar's entire sharing state in one call — the body is\n"
            "the full list of grants (all-initiative-members / per-user / per-role).\n"
            "Every non-owner grant is rebuilt from it; the owner is always preserved."
        ),
        model=Calendar,
        enabled_column=Initiative.calendars_enabled,
        response_model=CalendarListResponse,
        loader_options=_loads(calendars_service.calendar_loader_options),
        default_order=_order(Calendar.name.asc(), Calendar.id.asc()),
        serialize=_summaries(serialize_calendar_summary),
        conditions=_calendar_conditions,
        # A calendar may belong to the guild rather than to an initiative: the
        # app holds it, and no initiative's switch has anything to say about it.
        guild_level_rows=True,
        params=(
            _initiative_id(),
            ListParam("scope", Optional[Literal["guild"]], Query(default=None)),
            search_param(),
            sort_by_param(),
            sort_dir_param(),
            _tag_ids(Tool.calendar),
            _archived(),
            page_param(),
            page_size_param(100, ge=1, le=200),
        ),
        list_doc=(
            "List calendars visible to the current user (guild admins see "
            "all).\n"
            "\n"
            "``scope=guild`` narrows to the guild's own calendars — the ones the "
            "calendar\n"
            "app holds, belonging to no initiative. That is the opposite of the\n"
            "unfiltered list, which is everything in scope, so it is asked for by "
            "name\n"
            "rather than inferred from an absent ``initiative_id``."
        ),
        counts_doc=(
            "Visible-calendar counts grouped by initiative.\n"
            "\n"
            "Lightweight endpoint for the sidebar badges — same visibility rules "
            "as the\n"
            "calendar list (calendars-enabled initiatives, DAC), one GROUP BY "
            "instead of\n"
            "a capped list page. Guild calendars belong to no initiative, so they "
            "fall\n"
            "outside every group here — the sidebar rows are initiative rows."
        ),
    ),
    Tool.dashboard: ToolListSpec(
        tool=Tool.dashboard,
        # Not among what an installed app reads today.
        serves_apps=False,
        read_model=DashboardRead,
        read_row=dashboards_endpoints.read_after_write,
        grants_doc=(
            "Replace the dashboard's entire sharing state in one call — the body is\n"
            "the full list of grants (all-initiative-members / per-user / per-role).\n"
            "Every non-owner grant is rebuilt from it; the owner is always preserved.\n"
            "\n"
            "This shares the canvas, not its data: each widget still resolves against\n"
            "the viewer's own access to the sources it binds."
        ),
        model=Dashboard,
        enabled_column=Initiative.dashboards_enabled,
        response_model=DashboardListResponse,
        loader_options=_loads(dashboards_service.dashboard_loader_options),
        default_order=_order(Dashboard.name.asc(), Dashboard.id.asc()),
        serialize=_summaries(serialize_dashboard_summary),
        params=(
            _initiative_id(),
            search_param(),
            sort_by_param(),
            sort_dir_param(),
            _tag_ids(Tool.dashboard),
            _archived(),
            page_param(),
            page_size_param(100, ge=1, le=200),
        ),
        list_doc="List dashboards visible to the current user (guild admins see all).",
        counts_doc=(
            "Visible-dashboard counts grouped by initiative.\n"
            "\n"
            "Lightweight endpoint for the sidebar badges — same visibility rules "
            "as the\n"
            "dashboard list (dashboards-enabled initiatives, DAC), one GROUP BY "
            "instead\n"
            "of a capped list page."
        ),
    ),
    Tool.post: ToolListSpec(
        tool=Tool.post,
        read_model=PostRead,
        read_row=posts_endpoints.read_after_write,
        grants_doc=(
            "Replace the post's entire sharing state in one call — the body is the\n"
            "full list of grants (all-initiative-members / per-user / per-role). Every\n"
            "non-owner grant is rebuilt from it; the owner is always preserved."
        ),
        model=Post,
        enabled_column=Initiative.posts_enabled,
        response_model=PostListResponse,
        loader_options=_loads(posts_service.list_loader_options),
        default_order=_post_order,
        serialize=_serialize_posts,
        conditions=_post_conditions,
        params=(
            _initiative_id(),
            search_param(
                "Full-text match over the notice — its headline and its body. "
                "Reads the same index the search page does, so the board's "
                "filter and a search agree about what matches."
            ),
            sort_by_param(
                "Order by one of: name, initiative, updated_at. Omit for the "
                "board order — live pins first, then newest first."
            ),
            sort_dir_param(),
            _tag_ids(Tool.post),
            _archived(),
            ListParam(
                "unread",
                bool,
                Query(
                    default=False,
                    description="Only notices this reader has not read yet.",
                ),
            ),
            ListParam(
                "until",
                Optional[datetime],
                Query(
                    default=None,
                    description=(
                        "Start the board at this instant and go back — "
                        "inclusive, and measured by the same date the feed is "
                        "ordered by. This is how a timeline jumps to a month "
                        "without paging through everything since. An anchored "
                        "board is strictly chronological: the pinned band steps "
                        "aside, because a pin says what matters now rather than "
                        "what mattered then."
                    ),
                ),
            ),
            page_param(),
            page_size_param(
                posts_endpoints.BOARD_PAGE_SIZE,
                ge=1,
                le=posts_endpoints.MAX_BOARD_PAGE_SIZE,
                description=(
                    "Posts per page. Small by default: a board renders each "
                    "post's body, so a page is that many editors to mount."
                ),
            ),
        ),
        list_doc=(
            "List posts visible to the current user (guild admins see all).\n"
            "\n"
            "Returns whole posts — a board shows notices, not headlines — which "
            "is why\n"
            "it pages in fives. A scheduled notice is here only for the people "
            "who\n"
            "could edit it; for everyone else the board starts when it goes up."
        ),
        counts_doc=(
            "Visible-post counts grouped by initiative.\n"
            "\n"
            "Lightweight endpoint for the sidebar badges — same visibility rules "
            "as the\n"
            "post list, one GROUP BY instead of a capped list page."
        ),
    ),
    Tool.gallery: ToolListSpec(
        tool=Tool.gallery,
        read_model=GalleryRead,
        read_row=galleries_endpoints.read_after_write,
        grants_doc=(
            "Replace the gallery's entire sharing state in one call — the body is\n"
            "the full list of grants. Every non-owner grant is rebuilt from it; the\n"
            "owner is always preserved."
        ),
        model=Gallery,
        enabled_column=Initiative.galleries_enabled,
        response_model=GalleryListResponse,
        loader_options=_loads(galleries_service.list_loader_options),
        default_order=_order(Gallery.updated_at.desc(), Gallery.id.desc()),
        serialize=_serialize_galleries,
        params=(
            _initiative_id(),
            search_param(
                "Full-text match over the gallery's name and description, "
                "through the same index the search page reads."
            ),
            sort_by_param(
                "Order by one of: name, initiative, updated_at. Omit for newest first."
            ),
            sort_dir_param(),
            _tag_ids(Tool.gallery),
            _archived(),
            page_param(),
            page_size_param(100, ge=0, le=500),
        ),
        list_doc="List galleries visible to the current user (guild admins see all).",
        counts_doc=(
            "Visible-gallery counts grouped by initiative, for the sidebar badges."
        ),
    ),
    Tool.wiki: ToolListSpec(
        tool=Tool.wiki,
        read_model=WikiRead,
        read_row=wikis_endpoints.read_after_write,
        model=Wiki,
        enabled_column=Initiative.wikis_enabled,
        response_model=WikiListResponse,
        loader_options=_loads(wikis_service.list_loader_options),
        default_order=_order(Wiki.updated_at.desc(), Wiki.id.desc()),
        serialize=_serialize_wikis,
        params=(
            _initiative_id(),
            search_param(
                "Full-text match over the wiki's name and description, through "
                "the same index the search page reads."
            ),
            sort_by_param(
                "Order by one of: name, initiative, updated_at. Omit for newest first."
            ),
            sort_dir_param(),
            _tag_ids(Tool.wiki),
            _archived(),
            page_param(),
            page_size_param(100, ge=0, le=500),
        ),
        list_doc="List wikis visible to the current user (guild admins see all).",
        counts_doc=(
            "Visible-wiki counts grouped by initiative, for the sidebar badges."
        ),
    ),
}


# ---------------------------------------------------------------------------
# Mounting
# ---------------------------------------------------------------------------


def _tags(spec: ToolListSpec) -> list[str | Enum]:
    return [spec.tag or spec.tool.plural]


_CONTEXT_PARAMS: tuple[tuple[str, Any], ...] = (
    ("session", RLSSessionDep),
    ("current_user", CurrentUserDep),
    ("guild_context", GuildContextDep),
)


def _actor_params(tool: Tool) -> tuple[tuple[str, Any], ...]:
    """The same three, for a list an installed app may call under the tool's
    read scope: a person arrives exactly as above, and an install through its
    token."""
    scope = scope_name(tool_resource(tool), AppScopeAccess.read)
    return (
        ("session", ActorSessionDep),
        ("current_user", ActorUserDep),
        ("guild_context", Annotated[ActorContext, Depends(app_scope(scope))]),
    )


def _signature(
    params: tuple[ListParam, ...],
    context_params: tuple[tuple[str, Any], ...] = _CONTEXT_PARAMS,
) -> inspect.Signature:
    """The signature FastAPI reads off a tool's list handler.

    Keyword-only throughout, so the registry's declared order is what the
    published parameter list follows: the dependencies contribute the path and
    cookie params, which OpenAPI groups separately, and the tool's own query
    parameters keep the order its route has always published them in.
    """
    declared = [
        inspect.Parameter(name, inspect.Parameter.KEYWORD_ONLY, annotation=annotation)
        for name, annotation in context_params
    ]
    declared += [
        inspect.Parameter(
            param.name,
            inspect.Parameter.KEYWORD_ONLY,
            annotation=param.annotation,
            default=param.default,
        )
        for param in params
    ]
    return inspect.Signature(declared)


def _mount_list(spec: ToolListSpec) -> None:
    """Mount ``GET /`` for one tool."""

    async def list_rows(session, current_user, guild_context, **values):
        request = ListRequest(session, current_user, guild_context, values)
        build_conditions = spec.conditions or _default_conditions
        conditions = await build_conditions(spec, request)
        rows, total_count, page = await tool_listing.list_tool_rows(
            session,
            spec.model,
            conditions=conditions,
            loader_options=spec.loader_options(request),
            sort_by=values.get("sort_by"),
            sort_dir=values.get("sort_dir"),
            default_order=spec.default_order(request),
            page=values["page"],
            page_size=values["page_size"],
            extra_sort_fields=spec.extra_sort_fields,
            refine=spec.refine(request) if spec.refine else None,
            clamp=spec.clamp_page,
        )
        items = await spec.serialize(spec, request, rows)
        page_size = values["page_size"]
        extras = spec.response_extras(request) if spec.response_extras else {}
        return spec.response_model(
            items=items,
            total_count=total_count,
            page=page,
            page_size=page_size,
            has_next=page_has_next(page, page_size, total_count),
            **extras,
        )

    list_rows.__signature__ = _signature(
        spec.params,
        _actor_params(spec.tool) if spec.serves_apps else _CONTEXT_PARAMS,
    )
    router.add_api_route(
        f"/{spec.tool.route_segment}/",
        list_rows,
        methods=["GET"],
        response_model=spec.response_model,
        name=f"list_{spec.tool.plural}",
        description=spec.list_doc,
        tags=_tags(spec),
    )


def _mount_counts(spec: ToolListSpec) -> None:
    """Mount ``GET /counts/by-initiative`` for one tool."""

    async def counts_by_initiative(
        session: RLSSessionDep,
        current_user: CurrentUserDep,
        guild_context: GuildContextDep,
    ) -> InitiativeGroupedCountsResponse:
        extra = (
            spec.counts_conditions(current_user, guild_context)
            if spec.counts_conditions
            else ()
        )
        counts = await tool_listing.count_tool_rows_by_initiative(
            session,
            spec.tool,
            spec.model,
            spec.enabled_column,
            user_id=current_user.id,
            extra_conditions=extra,
            context=guild_context,
        )
        return InitiativeGroupedCountsResponse(counts=counts)

    router.add_api_route(
        # Declared before the tools' own ``/{id}`` routes, so the literal path
        # wins the match: this router is included first (see api.py).
        f"/{spec.tool.route_segment}/counts/by-initiative",
        counts_by_initiative,
        methods=["GET"],
        response_model=InitiativeGroupedCountsResponse,
        name=f"get_{spec.tool.value}_counts_by_initiative",
        description=spec.counts_doc,
        tags=_tags(spec),
    )


for _spec in TOOL_LISTS.values():
    _mount_counts(_spec)
    _mount_list(_spec)
