"""Dashboard endpoints — a canvas of widgets over existing data.

Creation is gated at the initiative level (dashboards_enabled +
create_dashboards); everything after that flows from the dashboard's
resource-grant DAC (``resource_grants`` + ``PUT /{id}/grants``), like every
other tool.

A dashboard's ``definition`` is normalized on every write, so only known widget
and binding vocabulary is ever stored. The definition is a presentation spec —
it names where data comes from and never carries content or actions — and each
widget's data is fetched per viewer through that source's own gated endpoint.
Sharing a dashboard therefore shares the *view*, never the underlying data:
a viewer who cannot read a bound counter simply sees an empty widget.
"""

import logging
from datetime import datetime, timezone
from typing import Annotated, Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func
from sqlalchemy.orm import selectinload
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api import resource_access
from app.api.deps import (
    IncludeDeletedDep,
    GuildContext,
    RLSSessionDep,
    get_current_active_user,
    get_guild_membership,
)
from app.core.messages import (
    DashboardMessages,
    InitiativeMessages,
    MarketplaceMessages,
)
from app.core.tools import Tool
from app.models.platform.marketplace import (
    MarketplaceListing,
    MarketplaceListingVersion,
)
from app.models.platform.user import User
from app.models.tenant.dashboard import Dashboard
from app.models.tenant.initiative import Initiative, PermissionKey
from app.models.tenant.resource_grant import ResourceAccessLevel, ResourceGrant
from app.schemas.tenant.dashboard import (
    PublishedOver,
    PublishRequest,
    DashboardInstalledListings,
    DashboardCreate,
    DashboardListResponse,
    DashboardRead,
    DashboardUpdate,
    WidgetCatalog,
    build_widget_catalog,
    serialize_dashboard,
    serialize_dashboard_summary,
)
from app.schemas.tenant.initiative import InitiativeGroupedCountsResponse
from app.schemas.tenant.recent_view import RecentViewWrite
from app.schemas.tenant.resource_grant import ResourceGrantSchema
from app.api.v1.tenant_endpoints.query import REFUSAL_STATUS as _QUERY_STATUS
from app.db import session as db_session
from app.db.session import rls_context_params
from app.schemas.sql_query import QueryColumnDescription, QueryResponse
from app.services import query as query_service
from app.services import permissions as permissions_service
from app.services import rls as rls_service
from app.services.marketplace import catalog as catalog_service
from app.services.marketplace.installs import (
    ListingInstallError,
    resolve_listing_install,
)
from app.services.tenant import dashboards as dashboards_service
from app.services.tenant import published_views
from app.services.tenant import recent_views as recent_views_service
from app.services.tenant import tags as tags_service
from app.services.tenant import search as search_service
from app.services.tenant import tool_listing
from app.models.tenant.guild_app import GuildApp
from app.services.marketplace.app_data import row_columns
from app.services.tenant.dashboard_definition import (
    DashboardDefinitionError,
    normalize_dashboard_config,
    normalize_dashboard_definition,
)

logger = logging.getLogger(__name__)

router = APIRouter()

GuildContextDep = Annotated[GuildContext, Depends(get_guild_membership)]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _endpoint_columns(session: AsyncSession):
    """What each installed app says its read endpoints hand back.

    Read once per save rather than per widget: a canvas of app tiles is a
    handful of installs, and this is what lets a statement over an endpoint's
    rows be refused while its author is looking at it.
    """
    installed = (await session.exec(select(GuildApp))).all()
    declared: dict[tuple[str, str], tuple] = {}
    for app in installed:
        for endpoint in (app.definition or {}).get("endpoints") or []:
            if not isinstance(endpoint, dict) or endpoint.get("direction") != "read":
                continue
            endpoint_id = endpoint.get("id")
            if isinstance(endpoint_id, str):
                declared[(app.listing_uid, endpoint_id)] = row_columns(endpoint)

    def columns(app_uid: str, endpoint_id: str):
        return declared.get((app_uid, endpoint_id))

    return columns


def _normalize_body(
    definition: dict, config: dict, endpoint_columns=None
) -> tuple[dict, dict]:
    """Validate a definition + its config together. Raises 422 with the
    validator's machine code so the client can localize it."""
    try:
        clean_definition = normalize_dashboard_definition(
            definition or {}, endpoint_columns=endpoint_columns
        )
        clean_config = normalize_dashboard_config(config or {}, clean_definition)
    except DashboardDefinitionError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    return clean_definition, clean_config


async def _resolve_listing_install(
    session: RLSSessionDep, listing_uid: str
) -> tuple[MarketplaceListing, MarketplaceListingVersion]:
    """The catalog rows behind an install, as an HTTP answer.

    The resolving itself is shared with the app installer
    (``services.marketplace.installs``) so both kinds ask the catalog the same
    questions; only the mapping to a status code belongs to this layer.
    """
    try:
        return await resolve_listing_install(session, listing_uid, kind="dashboard")
    except ListingInstallError as exc:
        raise HTTPException(
            status_code=(
                status.HTTP_404_NOT_FOUND if exc.not_found else status.HTTP_409_CONFLICT
            ),
            detail=exc.code,
        ) from exc


async def _count_install(listing_id: Optional[int]) -> None:
    """Add one to a listing's install tally, after the install has committed.

    On the system engine because the catalog has no request-path writer, and
    best-effort because it is a display number: a failed bump must never fail an
    install that already happened. Nothing about *which* guild is recorded.
    """
    if listing_id is None:
        return
    try:
        # Read off the module rather than bound at import: the session maker is
        # swapped per test, and a name captured at import time would keep
        # pointing at the real database.
        async with db_session.AdminSessionLocal() as session:
            await catalog_service.bump_installs_count(session, listing_id)
            await session.commit()
    except Exception:
        logger.warning(
            "marketplace: install count bump failed for listing %s",
            listing_id,
            exc_info=True,
        )


async def _get_initiative_for_dashboard(
    session: RLSSessionDep,
    initiative_id: int,
) -> Initiative:
    stmt = (
        select(Initiative)
        .where(Initiative.id == initiative_id)
        .options(
            selectinload(Initiative.memberships),
            selectinload(Initiative.roles),
        )
    )
    result = await session.exec(stmt)
    initiative = result.one_or_none()
    if not initiative:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=InitiativeMessages.NOT_FOUND,
        )
    return initiative


async def _check_create_permission(
    session: RLSSessionDep,
    initiative: Initiative,
    user: User,
    guild_context: GuildContext,
) -> None:
    if rls_service.is_guild_admin(guild_context.role):
        return
    has_perm = await rls_service.check_initiative_permission(
        session,
        initiative_id=initiative.id,
        user=user,
        permission_key=PermissionKey.create_dashboards,
    )
    if not has_perm:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=DashboardMessages.CREATE_PERMISSION_REQUIRED,
        )


async def _refetch_dashboard(session: RLSSessionDep, dashboard_id: int) -> Dashboard:
    dashboard = await dashboards_service.get_dashboard(
        session, dashboard_id, populate_existing=True
    )
    if not dashboard:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=DashboardMessages.NOT_FOUND,
        )
    return dashboard


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


@router.get("/", response_model=DashboardListResponse)
async def list_dashboards(
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
    initiative_id: Optional[int] = Query(default=None),
    search: Optional[str] = Query(
        default=None,
        description=(
            "Full-text match over the row — its name and its description. "
            "Reads the same index the search page does, so a list's filter "
            "box and a search agree about what matches."
        ),
    ),
    sort_by: Optional[str] = Query(
        default=None,
        description=(
            "Order by one of: name, initiative, updated_at. Omit for this "
            "tool's own default order."
        ),
    ),
    sort_dir: Optional[str] = Query(default=None, description="asc (default) or desc."),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=200),
) -> DashboardListResponse:
    """List dashboards visible to the current user (guild admins see all)."""
    conditions = [Dashboard.guild_id == guild_context.guild_id]

    if initiative_id is not None:
        initiative = await session.get(Initiative, initiative_id)
        if initiative and not initiative.dashboards_enabled:
            return DashboardListResponse(
                items=[],
                total_count=0,
                page=page,
                page_size=page_size,
                has_next=False,
            )
        conditions.append(Dashboard.initiative_id == initiative_id)
    else:
        conditions.append(
            Dashboard.initiative_id.in_(
                select(Initiative.id).where(Initiative.dashboards_enabled == True)  # noqa: E712
            )
        )

    conditions.append(
        permissions_service.listing_scope_clause(
            Tool.dashboard,
            Dashboard.id,
            current_user.id,
            guild_id=guild_context.guild_id,
            initiative_id=initiative_id,
        )
    )

    name_match = search_service.tool_search_clause(Tool.dashboard, Dashboard.id, search)
    if name_match is not None:
        conditions.append(name_match)

    count_subq = select(Dashboard.id).where(*conditions).subquery()
    total_count = (
        await session.exec(select(func.count()).select_from(count_subq))
    ).one()

    stmt = (
        select(Dashboard)
        .where(*conditions)
        .options(*dashboards_service.dashboard_loader_options())
    )
    stmt = (
        tool_listing.apply_tool_order(
            stmt,
            Dashboard,
            sort_by,
            sort_dir,
            default=[Dashboard.name.asc(), Dashboard.id.asc()],
        )
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    result = await session.exec(stmt)
    dashboards = result.unique().all()

    items = [
        serialize_dashboard_summary(d, user_id=current_user.id) for d in dashboards
    ]
    has_next = page * page_size < total_count
    return DashboardListResponse(
        items=items,
        total_count=total_count,
        page=page,
        page_size=page_size,
        has_next=has_next,
    )


# Declared before /{dashboard_id} so the literal path wins the match.
@router.get("/counts/by-initiative", response_model=InitiativeGroupedCountsResponse)
async def get_dashboard_counts_by_initiative(
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> InitiativeGroupedCountsResponse:
    """Visible-dashboard counts grouped by initiative.

    Lightweight endpoint for the sidebar badges — same visibility rules as the
    dashboard list (dashboards-enabled initiatives, DAC), one GROUP BY instead
    of a capped list page.
    """
    conditions = [
        Dashboard.guild_id == guild_context.guild_id,
        Dashboard.initiative_id.in_(
            select(Initiative.id).where(Initiative.dashboards_enabled == True)  # noqa: E712
        ),
    ]
    conditions.append(
        permissions_service.granted_scope_clause(
            Tool.dashboard,
            Dashboard.id,
            current_user.id,
            guild_id=guild_context.guild_id,
        )
    )

    statement = (
        select(Dashboard.initiative_id, func.count(Dashboard.id))
        .where(*conditions)
        .group_by(Dashboard.initiative_id)
    )
    rows = (await session.exec(statement)).all()
    return InitiativeGroupedCountsResponse(
        counts={initiative_id: count for initiative_id, count in rows}
    )


# Declared before /{dashboard_id} so the literal path wins the match.
@router.get("/installed-listings", response_model=DashboardInstalledListings)
async def read_installed_listings(
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> DashboardInstalledListings:
    """Which marketplace listings this guild has installed, and how many of each.

    One row per distinct listing rather than per dashboard, so the answer is
    complete in one response — the dashboard list is paginated, and a partial
    page would mark some installs and miss others.

    RLS-scoped like every other read here: it counts the dashboards the caller
    can see.
    """
    rows = (
        await session.exec(
            select(Dashboard.listing_uid, func.count())
            .where(Dashboard.listing_uid.is_not(None))
            .group_by(Dashboard.listing_uid)
        )
    ).all()
    return DashboardInstalledListings(
        counts={uid: int(count) for uid, count in rows if uid}
    )


# Declared before /{dashboard_id} so the literal path wins the match.
@router.get("/widget-catalog", response_model=WidgetCatalog)
async def read_widget_catalog(
    guild_context: GuildContextDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> WidgetCatalog:
    """The widget vocabulary this build supports — size floors, bindable
    sources, and display options per primitive, plus the named presets.

    Static app metadata rather than guild data (it reads no tables), but it
    stays on the guild-scoped router because it only means anything to someone
    already inside a guild, and that keeps every dashboard route addressed the
    same way. Serving it is what lets the editor's palette avoid carrying a
    second copy of the registry.
    """
    return build_widget_catalog()


@router.get("/{dashboard_id}", response_model=DashboardRead)
async def read_dashboard(
    dashboard_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
    include_deleted: IncludeDeletedDep = False,
) -> DashboardRead:
    dashboard = await resource_access.load_authorized(
        session, Tool.dashboard, dashboard_id, current_user, guild_context
    )
    # With what it publishes over: a reader has to be able to tell that some of
    # these numbers are not their own.
    return await _serialized_with_published(
        session, dashboard, current_user, guild_context.guild_id
    )


@router.post("/", response_model=DashboardRead, status_code=status.HTTP_201_CREATED)
async def create_dashboard(
    dashboard_in: DashboardCreate,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> DashboardRead:
    """Create a dashboard. Requires create_dashboards permission on the
    initiative (or guild admin); the creator gets the owner grant."""
    initiative = await _get_initiative_for_dashboard(
        session, dashboard_in.initiative_id
    )
    if not initiative.dashboards_enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=DashboardMessages.FEATURE_DISABLED,
        )
    await _check_create_permission(session, initiative, current_user, guild_context)

    listing_id: Optional[int] = None
    listing_version: Optional[str] = None
    if dashboard_in.listing_uid:
        listing, version = await _resolve_listing_install(
            session, dashboard_in.listing_uid
        )
        listing_id, listing_version = listing.id, version.version
        # Validated again on the way in: the catalog validated it at publish
        # time, but this build decides what it can render *now*.
        definition, config = _normalize_body(
            dict(version.definition),
            dashboard_in.config,
            await _endpoint_columns(session),
        )
    else:
        definition, config = _normalize_body(
            dashboard_in.definition,
            dashboard_in.config,
            await _endpoint_columns(session),
        )

    dashboard = Dashboard(
        guild_id=guild_context.guild_id,
        initiative_id=initiative.id,
        created_by=current_user.id,
        name=dashboard_in.name.strip(),
        description=dashboard_in.description,
        definition=definition,
        config=config,
        listing_uid=dashboard_in.listing_uid,
        listing_version=listing_version,
    )
    session.add(dashboard)
    await session.flush()

    session.add(
        ResourceGrant(
            resource_type="dashboard",
            resource_id=dashboard.id,
            user_id=current_user.id,
            role_id=None,
            level=ResourceAccessLevel.owner,
            guild_id=guild_context.guild_id,
            initiative_id=initiative.id,
        )
    )

    # Apply the initial sharing exactly the way edits do — one grant list, one
    # code path (defaults to Viewer for all initiative members).
    await permissions_service.replace_resource_grants(
        session,
        resource_type="dashboard",
        resource_id=dashboard.id,
        guild_id=guild_context.guild_id,
        initiative_id=initiative.id,
        owner_id=current_user.id,
        grants=dashboard_in.grants,
    )

    if dashboard_in.tag_ids:
        await tags_service.set_entity_tags(
            session,
            tags_service.TOOL_TAG_LINKS[Tool.dashboard],
            guild_id=guild_context.guild_id,
            entity_id=dashboard.id,
            tag_ids=dashboard_in.tag_ids,
        )

    await session.commit()
    if listing_id is not None:
        await _count_install(listing_id)
    hydrated = await _refetch_dashboard(session, dashboard.id)
    return serialize_dashboard(hydrated, user_id=current_user.id)


@router.patch("/{dashboard_id}", response_model=DashboardRead)
async def update_dashboard(
    dashboard_id: int,
    dashboard_in: DashboardUpdate,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> DashboardRead:
    """Update a dashboard — rename, or re-author its canvas. Requires write
    access. This is the only kind of write a dashboard has: authoring what it
    hooks up to. It never writes the data it displays."""
    dashboard = await resource_access.load_authorized(
        session,
        Tool.dashboard,
        dashboard_id,
        current_user,
        guild_context,
        access="write",
    )
    updated = False
    update_data = dashboard_in.model_dump(exclude_unset=True)

    if "name" in update_data and update_data["name"] is not None:
        dashboard.name = update_data["name"].strip()
        updated = True
    if "description" in update_data:
        dashboard.description = update_data["description"]
        updated = True

    # Definition and config are validated as a pair even when only one is sent,
    # so config can never outlive the widgets it configures.
    if "definition" in update_data or "config" in update_data:
        definition = update_data.get("definition", dashboard.definition)
        config = update_data.get("config", dashboard.config)
        normalized, normalized_config = _normalize_body(
            definition, config, await _endpoint_columns(session)
        )
        if await published_views.published_by(session, dashboard_id):
            # What this dashboard publishes is read through the questions on
            # it, so changing one is the act of writing it — and it may only be
            # written by somebody who reaches those resources themselves.
            if not await published_views.editor_reaches_what_is_published(
                session, dashboard_id, current_user, guild_context
            ):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=DashboardMessages.EDIT_NEEDS_THE_PUBLISHED_ACCESS,
                )
            # And it stays one set of numbers: `me` is what makes a statement
            # answer differently for each reader.
            if published_views.names_the_reader(normalized, normalized_config):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail=DashboardMessages.PUBLISHED_VIEW_HAS_NO_READER,
                )
        dashboard.definition, dashboard.config = normalized, normalized_config
        updated = True

    if updated:
        dashboard.updated_at = datetime.now(timezone.utc)
        session.add(dashboard)
        await session.commit()

    hydrated = await _refetch_dashboard(session, dashboard.id)
    return serialize_dashboard(hydrated, user_id=current_user.id)


@router.post("/{dashboard_id}/upgrade", response_model=DashboardRead)
async def upgrade_dashboard(
    dashboard_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> DashboardRead:
    """Re-pin an installed dashboard to its listing's current version.

    Nothing is ever pushed into a guild: a new version sits in the catalog until
    someone with write access here asks for it. Applying one replaces this
    instance's definition and nothing else — other instances of the same
    listing, in this guild or any other, are untouched.

    The instance's own config survives. A binding slot the new version dropped
    takes its config key with it, which is the same normalization an edit does,
    so config can never outlive the widget it configured.
    """
    dashboard = await resource_access.load_authorized(
        session,
        Tool.dashboard,
        dashboard_id,
        current_user,
        guild_context,
        access="write",
    )
    if not dashboard.listing_uid:
        # Authored here, not installed — there is no listing to re-pin to.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=MarketplaceMessages.NOT_INSTALLED_FROM_LISTING,
        )

    _, version = await _resolve_listing_install(session, dashboard.listing_uid)
    if version.version == dashboard.listing_version:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=MarketplaceMessages.ALREADY_LATEST_VERSION,
        )

    definition, config = _normalize_body(
        dict(version.definition), dashboard.config, await _endpoint_columns(session)
    )
    dashboard.definition = definition
    dashboard.config = config
    dashboard.listing_version = version.version
    dashboard.updated_at = datetime.now(timezone.utc)
    session.add(dashboard)
    await session.commit()

    hydrated = await _refetch_dashboard(session, dashboard.id)
    return serialize_dashboard(hydrated, user_id=current_user.id)


@router.delete("/{dashboard_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_dashboard(
    dashboard_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> None:
    """Soft-delete a dashboard. Requires owner permission or guild admin."""
    from app.services.platform import guilds as guilds_service
    from app.services.tenant.soft_delete import soft_delete_entity

    dashboard = await resource_access.load_authorized(
        session,
        Tool.dashboard,
        dashboard_id,
        current_user,
        guild_context,
        require_owner=True,
    )
    retention_days = await guilds_service.get_guild_retention_days(
        session, guild_context.guild_id
    )
    await soft_delete_entity(
        session,
        dashboard,
        deleted_by_user_id=current_user.id,
        retention_days=retention_days,
    )
    await session.commit()


def _stored_binding(
    definition: dict[str, Any] | None,
    config: dict[str, Any] | None,
    widget_id: str,
) -> Optional[dict[str, Any]]:
    """One widget's binding as the canvas resolves it.

    The instance config layers over the definition exactly as it does when the
    dashboard is drawn, so a slot a listing left open and the guild filled in
    counts the same as one the definition named outright.
    """
    widgets = (definition or {}).get("widgets")
    if not isinstance(widgets, list):
        return None
    overrides = (config or {}).get("widgets") or {}
    for widget in widgets:
        if not isinstance(widget, dict) or str(widget.get("id")) != widget_id:
            continue
        binding = widget.get("binding")
        if not isinstance(binding, dict):
            return None
        override = overrides.get(widget_id)
        return {**binding, **(override if isinstance(override, dict) else {})}
    return None


@router.get("/{dashboard_id}/widgets/{widget_id}/query", response_model=QueryResponse)
async def run_widget_query(
    dashboard_id: int,
    widget_id: str,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> QueryResponse:
    """Run the statement stored on one of this dashboard's widgets.

    What runs is the widget's own, never one the request supplies. That is what
    makes a published view safe to serve: the rows a dashboard's grants reach
    are shown through the question somebody published, and a reader cannot ask
    a different one of them.

    The dashboard's own four gates decide whether this caller sees anything at
    all, and they run first.
    """
    dashboard = await resource_access.load_authorized(
        session, Tool.dashboard, dashboard_id, current_user, guild_context
    )
    binding = _stored_binding(dashboard.definition, dashboard.config, widget_id)
    if not isinstance(binding, dict) or binding.get("source") != "query":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=DashboardMessages.WIDGET_HAS_NO_QUERY,
        )
    sql = binding.get("sql")
    if not isinstance(sql, str) or not sql.strip():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=DashboardMessages.WIDGET_HAS_NO_QUERY,
        )
    # Only here, and only after the gates above: a grant made to this dashboard
    # answers while this is set and at no other time.
    through = await published_views.serves_through(
        session, dashboard_id, guild_context.guild_id
    )
    if through is not None and published_views.names_the_reader(
        {"widgets": [{"binding": binding}]}
    ):
        # A statement about the reader is not one set of numbers, so it does not
        # get the grant — it answers from this reader's own access instead.
        # Saving one on a publishing dashboard is refused where it is written;
        # this is the same rule where it is run, so it holds however the
        # statement arrived.
        through = None
    try:
        result = await query_service.run(
            sql,
            context=rls_context_params(session),
            initiative_id=dashboard.initiative_id,
            via_dashboard_id=through,
        )
    except query_service.QueryError as refused:
        raise HTTPException(
            status_code=_QUERY_STATUS.get(refused.code, status.HTTP_400_BAD_REQUEST),
            detail=refused.code,
        ) from refused
    return QueryResponse(
        columns=[
            QueryColumnDescription(name=column.name, type=column.type)
            for column in result.columns
        ],
        rows=[list(row) for row in result.rows],
        truncated=result.truncated,
        relations=list(result.relations),
    )


# ---------------------------------------------------------------------------
# Published views — what a dashboard shows that is not the reader's own
# ---------------------------------------------------------------------------


@router.put("/{dashboard_id}/published", response_model=DashboardRead)
async def set_published_view(
    dashboard_id: int,
    payload: PublishRequest,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> DashboardRead:
    """Say what this dashboard shows to everybody who can open it.

    The whole list each time. Every resource named here becomes readable
    *through* this dashboard: its tiles stop answering from each viewer's own
    access for those rows and answer the same way for all of them.

    Three things this refuses, and each is one of the rules the feature rests
    on. It reaches no further than the author, so a resource they cannot read
    themselves cannot be published. It stays fixed, so a dashboard whose
    statements ask about the reader cannot become one. And it is authoring, so
    it takes write access to the dashboard like any other change to it.
    """
    dashboard = await resource_access.load_authorized(
        session,
        Tool.dashboard,
        dashboard_id,
        current_user,
        guild_context,
        access="write",
    )
    if payload.resources and published_views.names_the_reader(
        dashboard.definition, dashboard.config
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=DashboardMessages.PUBLISHED_VIEW_HAS_NO_READER,
        )

    wanted: list[tuple[Tool, int]] = []
    for entry in payload.resources:
        try:
            kind = Tool(entry.resource_type)
        except ValueError as unknown:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=DashboardMessages.BINDING_INVALID,
            ) from unknown
        # Read as the person publishing, through the ordinary path: what they
        # hand on is their own reach and never more than it.
        try:
            await resource_access.load_authorized(
                session, kind, entry.resource_id, current_user, guild_context
            )
        except HTTPException as refused:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=DashboardMessages.PUBLISH_BEYOND_YOUR_REACH,
            ) from refused
        wanted.append((kind, entry.resource_id))

    held = {
        published_views.target(grant): grant
        for grant in await published_views.published_by(session, dashboard_id)
    }
    for key, grant in held.items():
        if key not in wanted:
            await session.delete(grant)
    for kind, resource_id in wanted:
        if (kind, resource_id) in held:
            continue
        session.add(
            published_views.read_grant(
                dashboard_id,
                kind,
                resource_id,
                guild_id=dashboard.guild_id,
                initiative_id=dashboard.initiative_id,
                created_by=current_user.id,
            )
        )
    await session.commit()

    hydrated = await _refetch_dashboard(session, dashboard_id)
    return await _serialized_with_published(
        session, hydrated, current_user, guild_context.guild_id
    )


@router.delete(
    "/{dashboard_id}/published/{resource_type}/{resource_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def revoke_published_view(
    dashboard_id: int,
    resource_type: str,
    resource_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> None:
    """Stop a dashboard reading one resource through its own grant.

    Either side may do this: whoever authors the dashboard, and whoever owns
    the resource. The owner's answer to a dashboard publishing over their work
    is to take it back, and it is theirs to give at any time.
    """
    try:
        kind = Tool(resource_type)
    except ValueError as unknown:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=DashboardMessages.NOT_FOUND,
        ) from unknown

    grant = (
        await session.exec(
            select(ResourceGrant).where(
                ResourceGrant.dashboard_id == dashboard_id,
                ResourceGrant.resource_type == kind,
                ResourceGrant.resource_id == resource_id,
            )
        )
    ).first()
    if grant is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=DashboardMessages.NOT_FOUND
        )

    if not await _may_revoke(
        session, dashboard_id, kind, resource_id, current_user, guild_context
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=DashboardMessages.PERMISSION_REQUIRED,
        )
    await session.delete(grant)
    await session.commit()


async def _may_revoke(
    session: Any,
    dashboard_id: int,
    kind: Tool,
    resource_id: int,
    user: User,
    guild_context: Any,
) -> bool:
    """Whether this caller may take a published grant back — either end of it."""
    for check in (
        lambda: resource_access.load_authorized(
            session, Tool.dashboard, dashboard_id, user, guild_context, access="write"
        ),
        lambda: resource_access.load_authorized(
            session, kind, resource_id, user, guild_context, manage_access=True
        ),
    ):
        try:
            await check()
            return True
        except HTTPException:
            continue
    return False


async def _serialized_with_published(
    session: Any, dashboard: Dashboard, user: User, guild_id: int
) -> DashboardRead:
    """A dashboard read, saying what it publishes over and whether that stands.

    Both, because they answer different questions. The list is what somebody
    published, which its author manages whether or not it is serving; the flag
    is whether these tiles are currently showing it, which is what a reader is
    told.
    """
    read = serialize_dashboard(dashboard, user_id=user.id)
    grants = await published_views.published_by(session, dashboard.id)
    read.published_over = [
        PublishedOver(
            resource_type=str(grant.resource_type),
            resource_id=grant.resource_id,
        )
        for grant in grants
    ]
    read.published_active = bool(grants) and await published_views.author_still_reaches(
        grants, guild_id
    )
    return read


# ---------------------------------------------------------------------------
# Sharing (resource grants)
# ---------------------------------------------------------------------------


@router.put("/{dashboard_id}/grants", response_model=DashboardRead)
async def set_dashboard_grants(
    dashboard_id: int,
    grants: List[ResourceGrantSchema],
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> DashboardRead:
    """Replace the dashboard's entire sharing state in one call — the body is
    the full list of grants (all-initiative-members / per-user / per-role).
    Every non-owner grant is rebuilt from it; the owner is always preserved.

    This shares the canvas, not its data: each widget still resolves against
    the viewer's own access to the sources it binds.
    """
    await resource_access.set_resource_grants(
        session, Tool.dashboard, dashboard_id, current_user, guild_context, grants
    )
    hydrated = await _refetch_dashboard(session, dashboard_id)
    return serialize_dashboard(hydrated, user_id=current_user.id)


# ---------------------------------------------------------------------------
# Recent-view tracking (powers the layout header tabs bar)
# ---------------------------------------------------------------------------


@router.post("/{dashboard_id}/view", response_model=RecentViewWrite)
async def record_dashboard_view(
    dashboard_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> RecentViewWrite:
    dashboard = await resource_access.load_authorized(
        session, Tool.dashboard, dashboard_id, current_user, guild_context
    )
    record = await recent_views_service.record_view(
        session,
        user_id=current_user.id,
        entity_type="dashboard",
        entity_id=dashboard.id,
        persist=not guild_context.is_pam,
        limit=current_user.recent_tabs_limit,
    )
    return RecentViewWrite(
        entity_type="dashboard",
        entity_id=dashboard.id,
        last_viewed_at=record.last_viewed_at,
    )


@router.delete("/{dashboard_id}/view", status_code=status.HTTP_204_NO_CONTENT)
async def clear_dashboard_view(
    dashboard_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> None:
    await resource_access.load_authorized(
        session, Tool.dashboard, dashboard_id, current_user, guild_context
    )
    await recent_views_service.clear_view(
        session,
        user_id=current_user.id,
        entity_type="dashboard",
        entity_id=dashboard_id,
    )
