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


class AppParamOptionSource(SanitizedBaseModel):
    """Where a parameter's permitted values come from, when only the app knows.

    A repository, a label, a board: every one of them differs per install,
    changes after it, and can be enumerated only by the app holding that
    install's credential — so none can be written into a manifest, which is
    published once and identical on every deployment. The manifest names a read
    of the app's own instead, and this is that naming, carried through to
    whoever draws the control.
    """

    #: A ``read`` endpoint the same app declares.
    endpoint: str
    #: Which of its returns holds the values. Always one of its ``list``
    #: returns — a menu comes from a column, not from a single value.
    key: str
    #: A second return holding what a person reads, where the value is opaque.
    label_key: Optional[str] = None
    #: What to send that endpoint, as one of ITS parameter names to one of the
    #: parameters this same form collects. A repository's labels are that
    #: repository's, so the source has to be told which one was chosen.
    needs: Dict[str, str] = {}


class AppDataParam(SanitizedBaseModel):
    """One parameter an endpoint accepts, from its ``params``."""

    key: str
    type: str
    label: Dict[str, str] = {}
    required: bool = False
    options: Optional[List[str]] = None
    #: Where to fill a menu from, for the values only the app can enumerate.
    #: A control is still the consumer's to draw — this says what the values
    #: are, not what to draw for them.
    options_from: Optional[AppParamOptionSource] = None
    #: Whether the parameter takes several values. A fact about the value
    #: rather than about a control, and not inferable: whether to send one
    #: value or an array is the app's to state.
    list: bool = False


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


class AppParamOption(SanitizedBaseModel):
    """One value a parameter permits."""

    value: str
    #: What a person reads, when the value itself is opaque. Absent means the
    #: value is its own label.
    label: Optional[str] = None


class AppParamOptionsResponse(SanitizedBaseModel):
    """The menu for one parameter, or why there is not one.

    ``unavailable`` is never an error. A source that will not resolve — the app
    is down, a credential nobody has connected, a sibling not yet chosen — must
    leave the parameter **enterable**, because a control disabled on those
    grounds has made a valid configuration unreachable. A consumer draws a menu
    when there is one and a text field when there is not.
    """

    options: List[AppParamOption] = []
    #: ``no-source``, ``needs-sibling`` or ``unresolved``.
    unavailable: Optional[str] = None
