"""What the widget data plane sends back.

Two payloads, and the difference between them is the point.

:class:`AppDataResponse` is the app's own answer, passed through. Rows are
opaque here — they are the app's data on its way to a sandboxed widget that will
be handed them as values — so nothing in this build reads inside them and
nothing describes their shape.

:class:`AppWidgetCatalogResponse` is what a dashboard needs before it can bind
anything: which installed apps offer widgets, which sources each widget draws,
and the module the browser will run in its sandbox. It is read off each
install's **pinned** definition, so a canvas is authored against the version the
guild chose rather than whatever the catalog says today.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import Field

from app.schemas.base import RawTextStr, SanitizedBaseModel


class AppDataResponse(SanitizedBaseModel):
    """One data source's rows, as the app returned them."""

    #: Verbatim. This build does not interpret, reshape, or validate the
    #: contents — the widget sandbox receives them as data, never as markup.
    rows: List[Any] = []
    #: When the *upstream* call happened. A cached body keeps the time it was
    #: actually obtained, so a viewer can tell how fresh the answer is rather
    #: than how recently they asked.
    fetched_at: datetime
    #: True when this body came from the response cache.
    cached: bool = False


class AppDataParam(SanitizedBaseModel):
    """One parameter a source accepts, from its ``params_schema``."""

    key: str
    type: str
    label: Dict[str, str] = {}
    required: bool = False
    options: Optional[List[str]] = None


class AppDataSourceRead(SanitizedBaseModel):
    """A source a widget may bind to."""

    id: str
    #: ``member`` or ``guild_admin`` — enforced again on every fetch under the
    #: caller's own session, so this is what the picker shows rather than what
    #: protects the data.
    visibility: str = "member"
    #: What the manifest asks for, already clamped at publish time. The proxy
    #: applies the deployment's own ceiling on top.
    cache_ttl_seconds: int = 0
    params_schema: List[AppDataParam] = []


class AppWidgetRead(SanitizedBaseModel):
    """One widget an installed app contributes."""

    #: Namespaced ``app:<listing_uid>:<widget_id>``, so an app's widget can
    #: never resolve to a built-in renderer or the other way round.
    type: str
    id: str
    #: The widget's own strings, in every language its author supplied.
    meta: Dict[str, Any] = {}
    #: The browser-side module. Opaque and carried verbatim: it is JavaScript,
    #: already size-capped by the manifest validator, and passing it through the
    #: plain-text sanitizer would rewrite operators like ``a < b`` into
    #: something that no longer parses. Nothing on this side reads, compiles, or
    #: evaluates it — the browser's sandbox is the only thing that runs it.
    module_source: RawTextStr
    #: Which of the app's sources this widget draws.
    sources: List[str] = []
    #: Rows for a preview that issues no request at all, keyed by source.
    sample_data: Dict[str, Any] = {}


class AppWidgetCatalogEntry(SanitizedBaseModel):
    """One installed app's contribution to the widget palette."""

    app_id: int
    app_uid: str = Field(max_length=14)
    name: str
    enabled: bool = True
    widgets: List[AppWidgetRead] = []
    data_sources: List[AppDataSourceRead] = []


class AppWidgetCatalogResponse(SanitizedBaseModel):
    items: List[AppWidgetCatalogEntry] = []
