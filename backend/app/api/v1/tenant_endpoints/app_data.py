"""External data reaching a dashboard widget.

Three reads, all guild-scoped, all under the caller's own session.

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

``/apps/{app_id}/endpoints/{endpoint_id}/options`` fills a menu. It is the one
read here with no dashboard on it, because it exists to fill in a form for a
widget nobody has placed yet — and what stands in for that gate is that the
caller cannot name what gets called: the source comes from the app's own
declaration, and its own visibility is enforced on the caller's credentials.
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
    AppParamOption,
    AppParamOptionsResponse,
    AppWidgetCatalogEntry,
    AppWidgetCatalogResponse,
    AppWidgetRead,
)
from app.services import rls as rls_service
from app.services.marketplace import app_data as app_data_service
from app.services.marketplace.service_apps import app_widget_type


def _projected_sample(raw: Any, endpoints: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """A widget's own sample, read the way its live answer will be.

    A publisher supplies what the endpoint would answer with, and this projects
    it through that endpoint's returns exactly as the proxy does — so the tile
    somebody chooses a widget by is the tile they get once it is bound. A sample
    for an endpoint the definition does not read is dropped.
    """
    if not isinstance(raw, dict):
        return {}
    projected: dict[str, Any] = {}
    for endpoint_id, result in raw.items():
        endpoint = endpoints.get(endpoint_id)
        if endpoint is None or not isinstance(result, dict):
            continue
        rows, values = app_data_service.project_returns(result, endpoint)
        projected[endpoint_id] = {"rows": rows, "values": values}
    return projected


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
        readable = {
            endpoint["id"]: endpoint
            for endpoint in definition.get("endpoints") or []
            if isinstance(endpoint, dict)
            and isinstance(endpoint.get("id"), str)
            and endpoint.get("direction") == "read"
        }
        endpoints = [
            AppEndpointRead(
                id=endpoint["id"],
                visibility=endpoint.get("visibility") or "member",
                cache_ttl_seconds=endpoint.get("cache_ttl_seconds") or 0,
                params=endpoint.get("params") or [],
            )
            for endpoint in readable.values()
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
                        sample_data=_projected_sample(
                            widget.get("sample_data"), readable
                        ),
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
        rows=result.rows,
        values=result.values,
        fetched_at=result.fetched_at,
        cached=result.cached,
    )


@router.get(
    "/{app_id}/endpoints/{endpoint_id}/options",
    response_model=AppParamOptionsResponse,
)
async def read_app_param_options(
    app_id: int,
    endpoint_id: str,
    session: RLSSessionDep,
    current_user: CurrentUser,
    guild_context: GuildContextDep,
    param: Annotated[
        str,
        Query(description="Which of the endpoint's parameters to fill a menu for."),
    ],
    params: Annotated[
        Optional[str],
        Query(
            description=(
                "What the form has answered so far, as a JSON object. Only the "
                "answers a source's `needs` names are ever forwarded."
            )
        ),
    ] = None,
) -> AppParamOptionsResponse:
    """The values one of an endpoint's parameters permits.

    This is what turns a declared ``options_from`` into a menu, and it is the
    one read here that carries no dashboard. It cannot: it exists to fill in a
    form for a widget that has not been placed yet, so there is no dashboard
    row whose gates could decide it.

    What decides it instead is that the caller never names what is called. The
    source is read out of the app's own pinned declaration — the
    ``options_from`` of the parameter being filled in — so the reachable set is
    exactly the reads a publisher marked as menu sources, and the arguments are
    the ones that source's ``needs`` names, mapped from answers this same form
    already holds. The source's own ``visibility`` is then enforced on the
    caller's own credentials, exactly as it is for a placed tile.

    A source that will not resolve is not an error: it comes back as
    ``unavailable`` with no options, and the parameter stays typeable.
    """
    app = (await session.exec(select(GuildApp).where(GuildApp.id == app_id))).first()
    if app is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=AppDataMessages.ENDPOINT_NOT_FOUND,
        )

    try:
        options, unavailable = await app_data_service.resolve_param_options(
            session,
            app=app,
            endpoint_id=endpoint_id,
            param_key=param,
            raw_params=params,
            user_id=current_user.id,
            is_guild_admin=rls_service.is_guild_admin(guild_context.role),
        )
    except app_data_service.AppDataError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.code) from exc

    return AppParamOptionsResponse(
        options=[AppParamOption(**option) for option in options],
        unavailable=unavailable,
    )
