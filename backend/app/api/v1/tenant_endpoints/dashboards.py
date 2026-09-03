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
from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func
from sqlalchemy.orm import selectinload
from sqlmodel import select

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
from app.db import session as db_session
from app.services import permissions as permissions_service
from app.services import rls as rls_service
from app.services.marketplace import catalog as catalog_service
from app.services.marketplace.installs import (
    ListingInstallError,
    resolve_listing_install,
)
from app.services.tenant import dashboards as dashboards_service
from app.services.tenant import recent_views as recent_views_service
from app.services.tenant import tags as tags_service
from app.services.tenant import search as search_service
from app.services.tenant import tool_listing
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


def _normalize_body(definition: dict, config: dict) -> tuple[dict, dict]:
    """Validate a definition + its config together. Raises 422 with the
    validator's machine code so the client can localize it."""
    try:
        clean_definition = normalize_dashboard_definition(definition or {})
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
        default=None, description="Case-insensitive substring match on name."
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
    return serialize_dashboard(dashboard, user_id=current_user.id)


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
            dict(version.definition), dashboard_in.config
        )
    else:
        definition, config = _normalize_body(
            dashboard_in.definition, dashboard_in.config
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
        dashboard.definition, dashboard.config = _normalize_body(definition, config)
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

    definition, config = _normalize_body(dict(version.definition), dashboard.config)
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
