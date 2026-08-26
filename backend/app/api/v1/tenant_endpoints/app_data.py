"""External data reaching a dashboard widget.

Two reads, both guild-scoped, both under the caller's own session.

``/apps/widget-catalog`` is the palette: which installed apps contribute
widgets, what each widget draws, and the module the browser will run in its
sandbox. It comes from each install's **pinned** definition, so a canvas is
authored against the version the guild chose.

``/apps/{app_id}/endpoints/{endpoint_id}`` is the proxy. A widget never names
an address — it names a read endpoint on an installed app, and this route turns
that into one bounded call to the app's own service. The request carries the dashboard the
widget sits on, and that is what makes the gates run **before** anything else:

* the URL is ``/g/{guild_id}/…`` under a session that assumes the guild's own
  Postgres role, so the install row is reachable only from inside the guild;
* the dashboard is loaded through the ordinary resource path, so a member of the
  guild who is not in the dashboard's initiative gets the same answer they would
  get for the dashboard itself — nothing;
* the dashboard has to actually bind this endpoint, so holding one dashboard is
  not a key to every endpoint an app offers;
* the endpoint's own ``visibility`` is then checked against the caller's real
  guild role.

Only after all of that does the service layer look at the response cache, which
is why the cache is a cache of *responses* rather than of decisions.
"""

from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlmodel import select

from app.api import resource_access
from app.api.deps import (
    GuildContext,
    RLSSessionDep,
    get_current_active_user,
    get_guild_membership,
)
from app.core.messages import AppDataMessages
from app.core.tools import Tool
from app.models.platform.user import User
from app.models.tenant.guild_app import GuildApp
from app.schemas.tenant.app_data import (
    AppDataResponse,
    AppEndpointRead,
    AppWidgetCatalogEntry,
    AppWidgetCatalogResponse,
    AppWidgetRead,
)
from app.services import rls as rls_service
from app.services.marketplace import app_data as app_data_service
from app.services.marketplace.service_apps import app_widget_type

router = APIRouter()

CurrentUser = Annotated[User, Depends(get_current_active_user)]
GuildContextDep = Annotated[GuildContext, Depends(get_guild_membership)]


def _binds_endpoint(
    definition: dict[str, Any] | None,
    config: dict[str, Any] | None,
    *,
    app_uid: str,
    endpoint_id: str,
) -> bool:
    """Whether a dashboard actually displays this endpoint.

    The instance config layers over the definition's binding exactly as the
    canvas resolves it, so a slot a listing left open and the guild filled in
    counts the same as one the definition named outright.
    """
    widgets = (definition or {}).get("widgets")
    if not isinstance(widgets, list):
        return False
    stored = config if isinstance(config, dict) else {}
    overrides = stored.get("widgets") or {}
    for widget in widgets:
        if not isinstance(widget, dict):
            continue
        binding = widget.get("binding")
        if not isinstance(binding, dict):
            continue
        override = overrides.get(widget.get("id"))
        effective = {**binding, **(override if isinstance(override, dict) else {})}
        if (
            effective.get("source") == "app"
            and effective.get("app_uid") == app_uid
            and effective.get("endpoint_id") == endpoint_id
        ):
            return True
    return False


# Declared before ``/{app_id}`` on the apps router so the literal path wins the
# match (this router is included first for that reason).
@router.get("/widget-catalog", response_model=AppWidgetCatalogResponse)
async def read_app_widget_catalog(
    session: RLSSessionDep,
    current_user: CurrentUser,
    guild_context: GuildContextDep,
) -> AppWidgetCatalogResponse:
    """Which widgets this guild's installed apps contribute.

    Every member may read it: an app's existence is guild-wide knowledge and the
    palette carries no guild data — declarations, module source, and sample
    rows, all from the pinned definition. An endpoint declared for guild admins
    is still listed, and still refused at fetch time to anyone else.

    Disabled installs are left out entirely: their widgets have nothing to draw,
    so offering them would be offering a binding that cannot resolve.
    """
    apps = (
        await session.exec(select(GuildApp).order_by(GuildApp.name, GuildApp.id))
    ).all()

    items: list[AppWidgetCatalogEntry] = []
    for app in apps:
        definition = app.definition or {}
        if not app.enabled or definition.get("app_kind") != "service":
            continue
        declared = definition.get("widgets")
        if not isinstance(declared, list):
            continue
        widgets = [
            entry
            for entry in declared
            if isinstance(entry, dict) and isinstance(entry.get("id"), str)
        ]
        if not widgets:
            continue

        # Reads only. A picker offering a write would offer a tile that makes
        # the app act every time somebody looks at a dashboard.
        endpoints = [
            AppEndpointRead(
                id=endpoint["id"],
                visibility=endpoint.get("visibility") or "member",
                cache_ttl_seconds=endpoint.get("cache_ttl_seconds") or 0,
                params=endpoint.get("params") or [],
            )
            for endpoint in definition.get("endpoints") or []
            if isinstance(endpoint, dict)
            and isinstance(endpoint.get("id"), str)
            and endpoint.get("direction") == "read"
        ]
        items.append(
            AppWidgetCatalogEntry(
                app_id=app.id,
                app_uid=app.listing_uid,
                name=app.name,
                enabled=app.enabled,
                widgets=[
                    AppWidgetRead(
                        type=app_widget_type(app.listing_uid, widget["id"]),
                        id=widget["id"],
                        meta=widget.get("meta") or {},
                        module_source=widget.get("module_source") or "",
                        endpoints=widget.get("endpoints") or [],
                        sample_data=widget.get("sample_data") or {},
                    )
                    for widget in widgets
                ],
                endpoints=endpoints,
            )
        )
    return AppWidgetCatalogResponse(items=items)


@router.get("/{app_id}/endpoints/{endpoint_id}", response_model=AppDataResponse)
async def read_app_data(
    app_id: int,
    endpoint_id: str,
    session: RLSSessionDep,
    current_user: CurrentUser,
    guild_context: GuildContextDep,
    dashboard_id: Annotated[
        int,
        Query(
            description=(
                "The dashboard the widget sits on. Its own gates decide whether "
                "this caller may see anything here at all."
            )
        ),
    ],
    params: Annotated[
        Optional[str],
        Query(description="The binding's parameters, as a JSON object."),
    ] = None,
) -> AppDataResponse:
    """One of an app's read endpoints, resolved for this viewer.

    Returns the app's rows verbatim with the time they were obtained. An app
    that is unreachable, slow, oversized, or answering in a shape this build
    does not accept comes back as a named message code, so the canvas draws one
    error tile instead of the request becoming a server fault.
    """
    # Gates 1–4 for the surface the data is being drawn on: RLS scopes the row
    # to this guild, initiative membership decides whether it exists for this
    # caller, and the resource's own grants decide whether they may read it.
    dashboard = await resource_access.load_authorized(
        session, Tool.dashboard, dashboard_id, current_user, guild_context
    )

    app = (await session.exec(select(GuildApp).where(GuildApp.id == app_id))).first()
    if app is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=AppDataMessages.ENDPOINT_NOT_FOUND,
        )
    if not _binds_endpoint(
        dashboard.definition,
        dashboard.config,
        app_uid=app.listing_uid,
        endpoint_id=endpoint_id,
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=AppDataMessages.ENDPOINT_NOT_FOUND,
        )

    try:
        result = await app_data_service.fetch_app_source(
            session,
            app=app,
            endpoint_id=endpoint_id,
            raw_params=params,
            user_id=current_user.id,
            is_guild_admin=rls_service.is_guild_admin(guild_context.role),
        )
    except app_data_service.AppDataError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.code) from exc

    return AppDataResponse(
        rows=result.rows, fetched_at=result.fetched_at, cached=result.cached
    )
