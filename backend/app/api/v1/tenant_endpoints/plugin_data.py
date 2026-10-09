"""External data reaching a dashboard widget.

Three reads, all guild-scoped, all under the caller's own session.

``/plugins/widget-catalog`` is the palette: which installed plug-ins contribute
widgets, which endpoint each draws, and the template the browser draws it
with. It comes from each install's **pinned** definition, so a canvas is
authored against the version the guild chose.

``/plugins/{plugin_id}/endpoints/{endpoint_id}`` is the proxy. A widget never names
an address — it names a read endpoint on an installed plug-in, and this route turns
that into one bounded call to the plug-in's own service. The request carries the dashboard the
widget sits on, and that is what makes the gates run **before** anything else:

* the URL is ``/c/{community_id}/…`` under a session that assumes the guild's own
  Postgres role, so the install row is reachable only from inside the guild;
* the dashboard is loaded through the ordinary resource path, so a member of the
  guild who is not in the dashboard's initiative gets the same answer they would
  get for the dashboard itself — nothing;
* the dashboard has to actually display this endpoint — a plug-in widget the
  one it declares, one of ours the one its binding names — so holding one
  dashboard is not a key to every endpoint a plug-in offers;
* an endpoint marked ``admin_only`` is then read by the guild's admins alone.

Only after all of that does the service layer look at the response cache, which
is why the cache is a cache of *responses* rather than of decisions.

``/plugins/summaries`` lists the installs that say where the community stands with
them, and ``/plugins/{plugin_id}/summary`` reads one: the read its manifest names
as its ``community_summary``, drawn on the community's Usage settings. Both are
on the settings rung, so the list is not the content-gated install list. The caller names the install and nothing else — which endpoint
is read comes from the pinned definition — and it is the settings rung that
decides who may ask, the same as the storage figure beside it.

``/plugins/{plugin_id}/blocks/{block_id}/rows`` is a block's read on the tasks a
view holds, and ``/plugins/{plugin_id}/blocks/{block_id}/actions/{action_key}``
runs one of its actions on one task. Which tasks reach the plug-in, and what an
action checks, are :mod:`app.services.marketplace.plugin_blocks`'s.

``/plugins/{plugin_id}/endpoints/{endpoint_id}/options`` fills a menu. It is the one
read here with no dashboard on it, because it exists to fill in a form for a
widget nobody has placed yet — and what stands in for that gate is that the
caller cannot name what gets called: the source comes from the plug-in's own
declaration, and it is fetched on the caller's own credentials.
"""

from typing import Annotated, Any, Optional

from fastapi import APIRouter, HTTPException, Query, status
from sqlmodel import select

from app.api import resource_access
from app.api.deps import (
    AgeViewerDep,
    RLSSessionDep,
    GuildContextDep,
    CurrentUser,
    SettingsAdminContextDep,
    SettingsRLSSessionDep,
)
from app.core.audit_events import AuditEventType
from app.core.messages import GuildPluginMessages, PluginDataMessages
from app.core.rate_limit import PLUGIN_BLOCK_ACTIONS_PER_MEMBER, take_allowance
from app.core.tools import Tool
from app.models.tenant.guild_plugin import GuildPlugin
from app.schemas.sql_query import QueryColumnDescription
from app.services.query import rows as rows_query
from app.schemas.tenant.plugin_data import (
    PluginBlockActionRequest,
    PluginBlockActionResponse,
    PluginBlockRowsRequest,
    PluginBlockRowsResponse,
    PluginDataTable,
    PluginDataResponse,
    PluginEndpointRead,
    PluginParamOption,
    PluginParamOptionsResponse,
    PluginSummaryListResponse,
    PluginSummaryRead,
    PluginSummaryReturn,
    PluginWidgetCatalogEntry,
    PluginWidgetCatalogResponse,
    PluginWidgetRead,
)
from app.services import audit as audit_service
from app.services.marketplace import plugin_blocks
from app.services.marketplace import plugin_data as plugin_data_service
from app.services.marketplace.plugin_data import PluginDataError
from app.services.marketplace.service_plugins import (
    PLUGIN_WIDGET_TYPE_PREFIX,
    is_admin_only,
    plugin_widget_type,
)
from app.services.tenant import plugin_age


def _projected_sample(raw: Any, endpoint: dict[str, Any] | None) -> dict[str, Any]:
    """A widget's own sample, read the way its live answer will be.

    A publisher supplies what the endpoint would answer with, and this projects
    it through that endpoint's returns exactly as the proxy does — so the tile
    somebody chooses a widget by is the tile they get once it is bound.
    """
    if endpoint is None or not isinstance(raw, dict) or not raw:
        return {}
    rows, values = plugin_data_service.project_returns(raw, endpoint)
    return {"rows": rows, "values": values}


router = APIRouter()


async def _plugin_for_viewer(
    session: RLSSessionDep, plugin_id: int, viewer: AgeViewerDep
) -> GuildPlugin:
    """The install, or 404; refused to a viewer too young for what it shows."""
    plugin = (
        await session.exec(select(GuildPlugin).where(GuildPlugin.id == plugin_id))
    ).first()
    if plugin is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=PluginDataMessages.ENDPOINT_NOT_FOUND,
        )
    if not plugin_age.age_allows(plugin.definition, viewer):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=GuildPluginMessages.AGE_RESTRICTED,
        )
    return plugin


def _bound_bindings(
    definition: dict[str, Any] | None,
    config: dict[str, Any] | None,
    *,
    plugin: GuildPlugin,
    endpoint_id: str,
) -> dict[str, dict[str, Any]]:
    """The widgets of this dashboard that display this endpoint, by widget id.

    The instance config layers over the definition's binding exactly as the
    canvas resolves it, so a slot a listing left open and the guild filled in
    counts the same as one the definition named outright.

    A plug-in's own widget displays the endpoint it declares in the install's
    pinned definition, whatever an older definition stored beside its binding,
    so it carries no statement. One of ours displays the endpoint its binding
    names.
    """
    widgets = (definition or {}).get("widgets")
    if not isinstance(widgets, list):
        return {}
    own_prefix = f"{PLUGIN_WIDGET_TYPE_PREFIX}{plugin.listing_uid}:"
    declared = {
        widget.get("id"): widget.get("endpoint")
        for widget in (plugin.definition or {}).get("widgets") or []
        if isinstance(widget, dict)
    }
    stored = config if isinstance(config, dict) else {}
    overrides = stored.get("widgets") or {}
    bound: dict[str, dict[str, Any]] = {}
    for widget in widgets:
        if not isinstance(widget, dict):
            continue
        binding = widget.get("binding")
        if not isinstance(binding, dict):
            continue
        override = overrides.get(widget.get("id"))
        effective = {**binding, **(override if isinstance(override, dict) else {})}
        if (
            effective.get("source") != "plugin"
            or effective.get("plugin_uid") != plugin.listing_uid
        ):
            continue
        widget_type = widget.get("type")
        if isinstance(widget_type, str) and widget_type.startswith(own_prefix):
            if declared.get(widget_type[len(own_prefix) :]) == endpoint_id:
                bound[str(widget.get("id"))] = {
                    key: value
                    for key, value in effective.items()
                    if key not in ("endpoint_id", "sql")
                }
        elif effective.get("endpoint_id") == endpoint_id:
            bound[str(widget.get("id"))] = effective
    return bound


# Declared before ``/{plugin_id}`` on the plug-ins router so the literal path wins the
# match (this router is included first for that reason).
@router.get("/widget-catalog", response_model=PluginWidgetCatalogResponse)
async def read_plugin_widget_catalog(
    session: RLSSessionDep,
    current_user: CurrentUser,
    guild_context: GuildContextDep,
) -> PluginWidgetCatalogResponse:
    """Which widgets this guild's installed plug-ins contribute.

    Every member may read it: a plug-in's existence is guild-wide knowledge and the
    palette carries no guild data — declarations, templates, and sample
    rows, all from the pinned definition. An endpoint declared for guild admins
    is still listed, and still refused at fetch time to anyone else.

    Disabled installs are left out entirely: their widgets have nothing to draw,
    so offering them would be offering a binding that cannot resolve.
    """
    plugins = (
        await session.exec(
            select(GuildPlugin).order_by(GuildPlugin.name, GuildPlugin.id)
        )
    ).all()

    items: list[PluginWidgetCatalogEntry] = []
    for plugin in plugins:
        definition = plugin.definition or {}
        if not plugin.enabled or definition.get("plugin_kind") != "service":
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
        # the plug-in act every time somebody looks at a dashboard.
        readable = {
            endpoint["id"]: endpoint
            for endpoint in definition.get("endpoints") or []
            if isinstance(endpoint, dict)
            and isinstance(endpoint.get("id"), str)
            and endpoint.get("direction") == "read"
        }
        endpoints = [
            PluginEndpointRead(
                id=endpoint["id"],
                admin_only=is_admin_only(endpoint),
                cache_ttl_seconds=endpoint.get("cache_ttl_seconds") or 0,
                params=endpoint.get("params") or [],
                returns=endpoint.get("returns") or [],
            )
            for endpoint in readable.values()
        ]
        items.append(
            PluginWidgetCatalogEntry(
                plugin_id=plugin.id,
                plugin_uid=plugin.listing_uid,
                name=plugin.name,
                enabled=plugin.enabled,
                widgets=[
                    PluginWidgetRead(
                        type=plugin_widget_type(plugin.listing_uid, widget["id"]),
                        id=widget["id"],
                        meta=widget.get("meta") or {},
                        endpoint=widget.get("endpoint") or "",
                        template=widget.get("template") or "",
                        strings=widget.get("strings") or {},
                        sample_data=_projected_sample(
                            widget.get("sample_data"),
                            readable.get(widget.get("endpoint") or ""),
                        ),
                    )
                    for widget in widgets
                ],
                endpoints=endpoints,
            )
        )
    return PluginWidgetCatalogResponse(items=items)


@router.get("/{plugin_id}/endpoints/{endpoint_id}", response_model=PluginDataResponse)
async def read_plugin_data(
    plugin_id: int,
    endpoint_id: str,
    session: RLSSessionDep,
    current_user: CurrentUser,
    guild_context: GuildContextDep,
    viewer: AgeViewerDep,
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
    widget_id: Annotated[
        Optional[str],
        Query(
            description=(
                "Which widget on that dashboard is asking. Only needed where "
                "its binding carries a statement: what runs is the one stored "
                "on the widget, never one the request supplies."
            )
        ),
    ] = None,
) -> PluginDataResponse:
    """One of a plug-in's read endpoints, resolved for this viewer.

    Returns the plug-in's rows verbatim with the time they were obtained. A plug-in
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

    plugin = await _plugin_for_viewer(session, plugin_id, viewer)
    bound = _bound_bindings(
        dashboard.definition,
        dashboard.config,
        plugin=plugin,
        endpoint_id=endpoint_id,
    )
    if not bound:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=PluginDataMessages.ENDPOINT_NOT_FOUND,
        )

    result = await plugin_data_service.fetch_plugin_source(
        session,
        plugin=plugin,
        endpoint_id=endpoint_id,
        raw_params=params,
        user_id=current_user.id,
        is_guild_admin=guild_context.is_admin,
    )

    # After the fetch, so a statement is a transformation of a shared answer:
    # twenty viewers of the same binding are still one upstream call, whatever
    # each of their widgets asks of the rows.
    table = _transformed(plugin, endpoint_id, bound.get(widget_id or ""), result)
    return PluginDataResponse(
        rows=result.rows,
        table=table,
        values=result.values,
        fetched_at=result.fetched_at,
        cached=result.cached,
    )


def _transformed(
    plugin: GuildPlugin,
    endpoint_id: str,
    binding: dict[str, Any] | None,
    result: "plugin_data_service.PluginDataResult",
) -> PluginDataTable | None:
    """What this widget's statement made of the rows, or nothing.

    A binding with no statement draws the plug-in's own rows, as it always has —
    the plug-in's widget template reads them by the names its manifest declared. A
    binding with one gets a table beside them: described, and positional, so a
    built-in widget can be pointed at a plug-in.
    """
    statement = (binding or {}).get("sql")
    if not isinstance(statement, str) or not statement.strip():
        return None

    endpoint = plugin_data_service.find_read_endpoint(plugin.definition, endpoint_id)
    if endpoint is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=PluginDataMessages.ENDPOINT_NOT_FOUND,
        )
    planned = rows_query.plan(statement, plugin_data_service.row_columns(endpoint))
    answered = rows_query.evaluate(planned, result.rows)

    return PluginDataTable(
        columns=[
            QueryColumnDescription(name=column.name, type=column.type)
            for column in planned.columns
        ],
        rows=[list(row) for row in answered],
    )


def _summary_endpoint(plugin: GuildPlugin) -> dict[str, Any] | None:
    """The read an enabled install names as its ``community_summary``, or None."""
    endpoint_id = (plugin.definition or {}).get("community_summary")
    if not plugin.enabled or not isinstance(endpoint_id, str):
        return None
    return plugin_data_service.find_read_endpoint(plugin.definition, endpoint_id)


@router.get("/summaries", response_model=PluginSummaryListResponse)
async def list_plugin_summaries(
    session: SettingsRLSSessionDep,
    _guild_context: SettingsAdminContextDep,
) -> PluginSummaryListResponse:
    """The installs whose pinned definition names a community summary, with
    what each declares it returns. Nothing is fetched here: each summary is read
    on its own, so one slow plug-in holds up only its own card."""
    plugins = (await session.exec(select(GuildPlugin).order_by(GuildPlugin.id))).all()
    items: list[PluginSummaryRead] = []
    for plugin in plugins:
        endpoint = _summary_endpoint(plugin)
        returns = (endpoint or {}).get("returns") or []
        if not returns:
            continue
        items.append(
            PluginSummaryRead(
                plugin_id=plugin.id,
                name=plugin.name,
                returns=[PluginSummaryReturn(**value) for value in returns],
            )
        )
    return PluginSummaryListResponse(items=items)


@router.get("/{plugin_id}/summary", response_model=PluginDataResponse)
async def read_plugin_summary(
    plugin_id: int,
    session: SettingsRLSSessionDep,
    current_user: CurrentUser,
    _guild_context: SettingsAdminContextDep,
) -> PluginDataResponse:
    """Where the community stands with one installed plug-in.

    The endpoint is the one the pinned definition names as its
    ``community_summary``; an install that names none, or is switched off,
    has nothing to draw and answers 404. A plug-in that does not answer comes
    back as the proxy's own message code, so the page draws "unavailable"
    rather than failing.
    """
    plugin = (
        await session.exec(select(GuildPlugin).where(GuildPlugin.id == plugin_id))
    ).first()
    endpoint = _summary_endpoint(plugin) if plugin else None
    if plugin is None or endpoint is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=PluginDataMessages.ENDPOINT_NOT_FOUND,
        )

    result = await plugin_data_service.fetch_plugin_source(
        session,
        plugin=plugin,
        endpoint_id=endpoint["id"],
        raw_params=None,
        user_id=current_user.id,
        # The settings rung is the community's admin standing, which is
        # what an admin-only summary asks for.
        is_guild_admin=True,
    )

    return PluginDataResponse(
        rows=result.rows,
        values=result.values,
        fetched_at=result.fetched_at,
        cached=result.cached,
    )


@router.get(
    "/{plugin_id}/endpoints/{endpoint_id}/options",
    response_model=PluginParamOptionsResponse,
)
async def read_plugin_param_options(
    plugin_id: int,
    endpoint_id: str,
    session: RLSSessionDep,
    current_user: CurrentUser,
    guild_context: GuildContextDep,
    viewer: AgeViewerDep,
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
) -> PluginParamOptionsResponse:
    """The values one of an endpoint's parameters permits.

    This is what turns a declared ``options_from`` into a menu, and it is the
    one read here that carries no dashboard. It cannot: it exists to fill in a
    form for a widget that has not been placed yet, so there is no dashboard
    row whose gates could decide it.

    What decides it instead is that the caller never names what is called. The
    source is read out of the plug-in's own pinned declaration — the
    ``options_from`` of the parameter being filled in — so the reachable set is
    exactly the reads a publisher marked as menu sources, and the arguments are
    the ones that source's ``needs`` names, mapped from answers this same form
    already holds. The source is then fetched on the caller's own credentials,
    exactly as it is for a placed tile.

    A source that will not resolve is not an error: it comes back as
    ``unavailable`` with no options, and the parameter stays typeable.
    """
    plugin = await _plugin_for_viewer(session, plugin_id, viewer)

    options, unavailable = await plugin_data_service.resolve_param_options(
        session,
        plugin=plugin,
        endpoint_id=endpoint_id,
        param_key=param,
        raw_params=params,
        user_id=current_user.id,
        is_guild_admin=guild_context.is_admin,
    )

    return PluginParamOptionsResponse(
        options=[PluginParamOption(**option) for option in options],
        unavailable=unavailable,
    )


@router.post(
    "/{plugin_id}/blocks/{block_id}/rows", response_model=PluginBlockRowsResponse
)
async def read_plugin_block_rows(
    plugin_id: int,
    block_id: str,
    payload: PluginBlockRowsRequest,
    session: RLSSessionDep,
    current_user: CurrentUser,
    guild_context: GuildContextDep,
    viewer: AgeViewerDep,
) -> PluginBlockRowsResponse:
    """One block's read, for the tasks a view holds.

    Each row is keyed by the task it names. A task the viewer cannot see, that
    the block is not drawn on for them, or that the plug-in cannot read has no
    row, and with none left the plug-in is not called. A plug-in that does not
    answer comes back as the widget proxy's own message code.
    """
    plugin = await _plugin_for_viewer(session, plugin_id, viewer)
    result = await plugin_blocks.block_rows(
        session,
        plugin=plugin,
        block_id=block_id,
        task_ids=payload.task_ids,
        context=guild_context,
        user_id=current_user.id,
    )
    return PluginBlockRowsResponse(
        rows=result.rows, fetched_at=result.fetched_at, cached=result.cached
    )


#: The counter namespace for block actions' allowance.
_ACTION_LIMIT_NAMESPACE = "plugin-block-action"
#: How an action ended, in the audit line, when the plug-in answered.
_ACTION_OK = "ok"


@router.post(
    "/{plugin_id}/blocks/{block_id}/actions/{action_key}",
    response_model=PluginBlockActionResponse,
)
async def run_plugin_block_action(
    plugin_id: int,
    block_id: str,
    action_key: str,
    payload: PluginBlockActionRequest,
    session: RLSSessionDep,
    current_user: CurrentUser,
    guild_context: GuildContextDep,
    viewer: AgeViewerDep,
) -> PluginBlockActionResponse:
    """Run one of a block's actions on one task.

    ``action_key`` is the action's endpoint id after ``plugin.<public id>.``.
    The plug-in does the work, with its own access, and answers with the
    block's fresh row for the task; Initiative changes nothing itself. Refused
    with ``PLUGIN_BLOCK_NOT_FOUND`` when the block declares no such action,
    ``PLUGIN_BLOCK_NOT_OFFERED`` when the block is not drawn on this task for
    this viewer, and 429 past the allowance.
    """
    plugin = await _plugin_for_viewer(session, plugin_id, viewer)

    def audit(outcome: str) -> None:
        audit_service.emit(
            event_type=AuditEventType.PLUGIN_BLOCK_ACTION,
            actor_user_id=current_user.id,
            guild_id=guild_context.guild_id,
            target_type="task",
            target_id=payload.task_id,
            detail={
                "install_id": plugin.id,
                "listing_uid": plugin.listing_uid,
                "block": block_id,
                "action": action_key,
                "outcome": outcome,
            },
        )

    if not await take_allowance(
        PLUGIN_BLOCK_ACTIONS_PER_MEMBER,
        _ACTION_LIMIT_NAMESPACE,
        f"{guild_context.guild_id}:{plugin.id}:{current_user.id}",
    ):
        audit(PluginDataMessages.RATE_LIMITED)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=PluginDataMessages.RATE_LIMITED,
        )
    try:
        row = await plugin_blocks.run_block_action(
            session,
            plugin=plugin,
            block_id=block_id,
            action_key=action_key,
            task_id=payload.task_id,
            context=guild_context,
            user_id=current_user.id,
        )
    except PluginDataError as exc:
        audit(exc.code)
        raise
    except HTTPException as exc:
        audit(str(exc.detail))
        raise
    audit(_ACTION_OK)
    return PluginBlockActionResponse(row=row)
