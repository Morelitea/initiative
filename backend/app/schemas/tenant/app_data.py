"""What the widget data plane sends back.

Two payloads, and the difference between them is the point.

:class:`AppDataResponse` is the app's own answer, read through the returns its
endpoint declares: the ones holding several become rows, the ones holding a
single value stay whole beside them. The projection is by name alone — nothing
here interprets a value, and the manifest is the only thing that says what the
names are.

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
    """One data source's answer, in the two shapes its endpoint declared."""

    #: One entry per index across the endpoint's ``list`` returns, read side by
    #: side. Values are carried as the app sent them — the widget sandbox
    #: receives them as data, never as markup.
    rows: List[Dict[str, Any]] = []
    #: The endpoint's single-valued returns: what the answer says about itself
    #: rather than about any one item in it, and still there when there are no
    #: items at all.
    values: Dict[str, Any] = {}
    #: When the *upstream* call happened. A cached body keeps the time it was
    #: actually obtained, so a viewer can tell how fresh the answer is rather
    #: than how recently they asked.
    fetched_at: datetime
    #: True when this body came from the response cache.
    cached: bool = False


class AppDataParam(SanitizedBaseModel):
    """One parameter an endpoint accepts, from its ``params``."""

    key: str
    type: str
    label: Dict[str, str] = {}
    required: bool = False
    options: Optional[List[str]] = None


class AppEndpointRead(SanitizedBaseModel):
    """A read endpoint a widget may bind to.

    Reads only. A write and an emission are both real endpoints and neither
    fills a tile, so neither belongs in a widget picker.
    """

    id: str
    #: ``member`` or ``guild_admin`` — enforced again on every fetch under the
    #: caller's own session, so this is what the picker shows rather than what
    #: protects the data.
    visibility: str = "member"
    #: What the manifest asks for, already clamped at publish time. The proxy
    #: applies the deployment's own ceiling on top.
    cache_ttl_seconds: int = 0
    params: List[AppDataParam] = []


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
    #: Which of the app's read endpoints this widget draws.
    endpoints: List[str] = []
    #: What a preview draws instead of calling anything, keyed by endpoint id
    #: and projected through that endpoint's returns exactly as a live answer
    #: is — so a listing's tile and an installed one are the same widget.
    sample_data: Dict[str, Any] = {}


class AppWidgetCatalogEntry(SanitizedBaseModel):
    """One installed app's contribution to the widget palette."""

    app_id: int
    app_uid: str = Field(max_length=14)
    name: str
    enabled: bool = True
    widgets: List[AppWidgetRead] = []
    endpoints: List[AppEndpointRead] = []


class AppWidgetCatalogResponse(SanitizedBaseModel):
    items: List[AppWidgetCatalogEntry] = []
