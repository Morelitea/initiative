"""Validation and normalization for dashboard definitions.

A definition is a **presentation spec**: a grid layout plus widgets, each bound
to a data source by name. Most dashboards — hand-built or installed from the
marketplace — are simply a *composition* of the built-in widgets below: a
"sprint health" listing is several first-party widgets, arranged and pre-bound. The
marketplace download carries that definition; what this module owns is narrower,
and is the reason a downloaded definition is safe to store — a **capability
check**:

* a widget must name a ``type`` we have a renderer for, and
* a binding must name a ``source`` we have a fetcher for, and one that widget
  can draw.

That closed vocabulary is what stops a definition from naming its own endpoint
or carrying code: there is nowhere to put a URL and nothing generic that would
dereference one. It is also why dashboards are display-only — no source maps to
a mutating route, so no definition can cause a write.

What this module deliberately does **not** do is re-declare the shape of each
binding's parameters. Those belong to the fetcher that consumes them (a
``counter`` binding's ``counter_id``, a ``tasks`` binding's filter-DSL
``conditions``), and mirroring them here would mean maintaining every parameter
in two places. They are stored as given, bounded by the definition size cap, and
checked where they are used: the filter DSL parser enforces its own limits, and
every id is authorized against the viewer by RLS at fetch time.

Normalization mirrors ``documents_spreadsheet``: unrecognized *structure* is
dropped rather than preserved, so a stored definition always has canonical shape.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from app.core.messages import DashboardMessages
from app.models.platform.marketplace import UID_ALPHABET, UID_LENGTH
from app.services.marketplace.manifest_values import (
    IDENTIFIER_CHARS,
    MAX_IDENTIFIER_LENGTH,
)
from app.services.marketplace.service_apps import APP_WIDGET_TYPE_PREFIX

SCHEMA_VERSION = 1

# Hard caps. A definition is small by nature; these bound both storage and the
# per-viewer fan-out a single dashboard can trigger.
MAX_DEFINITION_BYTES = 256 * 1024
MAX_WIDGETS = 50
MAX_GRID_COLUMNS = 12
MAX_GRID_ROWS = 500
MAX_TITLE_LENGTH = 200


class DashboardDefinitionError(ValueError):
    """Raised when a definition cannot be normalized. The message is a stable
    machine code from ``app.core.messages``; endpoints surface it as a 422."""


def _fail(code: str) -> None:
    raise DashboardDefinitionError(code)


# --- primitives ------------------------------------------------------------
#
# The widget kinds this app has renderers for. Each declares the size floor the
# canvas honors (so a layout can never squeeze it below legibility) and the
# sources it knows how to draw. The frontend renderer map mirrors this registry
# and a drift test keeps the two equal.
#
# Primitives are the *only* thing that maps to code. Everything a user or the
# marketplace can name resolves to one of these (see PRESETS below).


@dataclass(frozen=True)
class WidgetOptionSpec:
    """One display option: the values it may take, in the order the palette
    offers them, and the one a widget falls back to when a definition names
    none.

    Order is declared rather than sorted so a scale reads day → quarter instead
    of alphabetically, and the default is stated rather than implied by that
    order, so the two can differ (weeks are the useful default; days are the
    natural first entry). Serving both is what keeps the editor's pre-selected
    value equal to what the widget will actually draw.
    """

    values: tuple[str, ...]
    default: str

    def __contains__(self, value: object) -> bool:
        return value in self.values


def _option(*values: str, default: str | None = None) -> WidgetOptionSpec:
    return WidgetOptionSpec(values=values, default=default if default else values[0])


@dataclass(frozen=True)
class WidgetSpec:
    min_w: int
    min_h: int
    default_w: int
    default_h: int
    sources: frozenset[str]
    # Widget-level options this primitive accepts, each with its allowed values.
    # A preset's params and a definition's own options are checked against this.
    options: Mapping[str, WidgetOptionSpec] = field(default_factory=dict)


WIDGET_SPECS: dict[str, WidgetSpec] = {
    # A timeline needs width to be readable at all.
    "gantt": WidgetSpec(
        min_w=6,
        min_h=3,
        default_w=12,
        default_h=6,
        sources=frozenset({"tasks", "projects", "calendar_entries"}),
        options={
            "scale": _option("day", "week", "month", "quarter", default="week"),
            # How rows are grouped into foldable summaries. What each key means
            # is the widget's business — a calendar entry has no priority, so it
            # reads anything but "none" as "the calendar it sits on".
            "group": _option("project", "status", "priority", "assignee", "none"),
            # The total row above everything shown.
            "rollup": _option("on", "off"),
            # Whether groups arrive open or folded. A starting state only; which
            # rows are open afterwards belongs to whoever is reading.
            "start": _option("open", "folded"),
        },
    ),
    # One big number.
    "stat": WidgetSpec(
        min_w=2,
        min_h=2,
        default_w=3,
        default_h=2,
        sources=frozenset({"counter", "task_counts", "sheet_range"}),
        options={
            "format": _option("plain", "percent", "currency", "duration"),
            # Which count the number reports when its source is several
            # buckets rather than one value.
            "pick": _option("total", "largest", "first"),
            # A trend line under the number, and what its direction means. A
            # falling cycle time is good; falling revenue is not, so the widget
            # is told rather than guessing.
            "trend": _option("off", "on"),
            "direction": _option("up_good", "down_good"),
        },
    ),
    # A series drawn as bars/lines/area/slices.
    "chart": WidgetSpec(
        min_w=3,
        min_h=3,
        default_w=6,
        default_h=4,
        sources=frozenset({"task_counts", "counter_group", "sheet_range", "projects"}),
        options={
            "mark": _option("bar", "line", "area", "pie"),
            "stacked": _option("false", "true"),
            "sort": _option("source", "value_desc", "value_asc", "label"),
            # A ceiling on categories, with the tail folded into one "Other"
            # entry. The alternative — more colors — is the thing a categorical
            # palette cannot do past its slot count.
            "limit": _option("all", "5", "8", "12"),
            # Horizontal bars give long category names room to be read.
            "orientation": _option("columns", "bars"),
            # Direct labels, always selective: the extremes or the end of a
            # line, never a number on every point.
            "values": _option("none", "extremes", "end"),
            # One series in color and the rest in gray — the honest form when
            # the story is a single series and the others are context.
            "emphasis": _option("none", "largest", "last"),
        },
    ),
    # Staged counts, widest bucket first.
    "funnel": WidgetSpec(
        min_w=3,
        min_h=3,
        default_w=6,
        default_h=5,
        sources=frozenset({"task_counts", "sheet_range"}),
        options={
            # Stages are usually a workflow, so the order the source gave them
            # is meaningful; sorting is for when it is not.
            "order": _option("source", "descending"),
        },
    ),
    # A completion bar — a counter against its own min/max, or a done ratio.
    "progress": WidgetSpec(
        min_w=2,
        min_h=1,
        default_w=4,
        default_h=2,
        sources=frozenset({"counter", "task_counts", "projects"}),
        options={
            # One bar for the whole binding, or one per project/bucket.
            "breakdown": _option("total", "each"),
            "format": _option("percent", "plain"),
        },
    ),
    # Density over a calendar grid. Task counts bucketed by day is what it draws
    # at launch; nothing about the widget is specific to that source.
    "heatmap": WidgetSpec(
        min_w=4,
        min_h=2,
        default_w=8,
        default_h=3,
        sources=frozenset({"task_counts"}),
        options={"tone": _option("accent", "positive", "warning")},
    ),
    # A plain read-only table. Display only, like every widget: no row actions,
    # no inline editing — that is a project view's job, not a dashboard's.
    "table": WidgetSpec(
        min_w=4,
        min_h=3,
        default_w=12,
        default_h=5,
        sources=frozenset({"tasks", "projects", "sheet_range", "calendar_entries"}),
        options={
            # How many of a row's fields to show. The envelope carries tags,
            # assignees, checklist progress and comment counts; "standard" is
            # the four columns that fit a half-width tile.
            "columns": _option("standard", "detailed"),
            # Mark rows that need attention, in the negative tone.
            "highlight": _option("off", "overdue"),
            "totals": _option("off", "on"),
        },
    ),
}

# Derived, so a source is named exactly once — on the widgets that render it.
ALL_SOURCES: frozenset[str] = frozenset().union(
    *(spec.sources for spec in WIDGET_SPECS.values())
)


# --- app widgets ------------------------------------------------------------
#
# A service app contributes its own widgets and its own data sources (§7, §9.1).
# They are deliberately a *separate* vocabulary from the built-ins above rather
# than an addition to it:
#
# * an app widget's type is namespaced ``app:<listing_uid>:<widget_id>``, so it
#   can never resolve to a built-in renderer, and a built-in can never resolve
#   to an app's module;
# * ``app`` is the only source an app widget binds, and no built-in binds it —
#   an app's rows are opaque here, so nothing in this build could draw them.
#
# The binding names a listing and a source; it never names an address, and there
# is still nowhere in a definition to put one. What that source *is* — its
# parameters, its visibility, its freshness — lives in the installed app's
# pinned definition and is enforced when the data is fetched, under the caller's
# own session.

#: The one binding source an app widget may name.
APP_BINDING_SOURCE = "app"

#: Size floors for an app widget. Uniform, because this build cannot know what
#: a vendor's module draws; the floor is simply "big enough to read".
APP_WIDGET_SPEC = WidgetSpec(
    min_w=2,
    min_h=2,
    default_w=6,
    default_h=4,
    sources=frozenset({APP_BINDING_SOURCE}),
)

#: What one app binding may carry, mirroring the manifest's per-source cap.
MAX_APP_BINDING_PARAMS = 12
#: A parameter value is a scalar the source declared a type for. Checked again
#: against that type at fetch time; bounded here so a definition stays small.
MAX_APP_PARAM_LENGTH = 2_000


def _check_identifier(value: Any) -> str:
    if not isinstance(value, str) or not value or len(value) > MAX_IDENTIFIER_LENGTH:
        _fail(DashboardMessages.BINDING_INVALID)
    for character in value:
        if character not in IDENTIFIER_CHARS:
            _fail(DashboardMessages.BINDING_INVALID)
    return value


def _check_uid(value: Any, code: str) -> str:
    if not isinstance(value, str) or len(value) != UID_LENGTH:
        _fail(code)
    for character in value:
        if character not in UID_ALPHABET:
            _fail(code)
    return value


def app_widget_parts(declared: str) -> tuple[str, str] | None:
    """Split ``app:<listing_uid>:<widget_id>``, or None if it is not one.

    ``:`` is outside the identifier character set on both halves, so the three
    parts stay unambiguous however an app names its widget.
    """
    if not declared.startswith(APP_WIDGET_TYPE_PREFIX):
        return None
    remainder = declared[len(APP_WIDGET_TYPE_PREFIX) :]
    listing_uid, separator, widget_id = remainder.partition(":")
    if not separator:
        _fail(DashboardMessages.WIDGET_TYPE_UNKNOWN)
    _check_uid(listing_uid, DashboardMessages.WIDGET_TYPE_UNKNOWN)
    if (
        not widget_id
        or len(widget_id) > MAX_IDENTIFIER_LENGTH
        or any(character not in IDENTIFIER_CHARS for character in widget_id)
    ):
        _fail(DashboardMessages.WIDGET_TYPE_UNKNOWN)
    return listing_uid, widget_id


def _normalize_app_binding(binding: dict[str, Any], listing_uid: str) -> dict[str, Any]:
    """An ``app`` binding: which installed app, which source, which parameters.

    ``app_uid`` has to be the app the widget came from. A widget is one app's
    module and its sources are that app's, so letting a definition point one
    app's widget at another app's data would be a definition choosing what
    crosses between two vendors.
    """
    declared_uid = _check_uid(binding.get("app_uid"), DashboardMessages.BINDING_INVALID)
    if declared_uid != listing_uid:
        _fail(DashboardMessages.BINDING_INVALID)
    source_id = _check_identifier(binding.get("source_id"))

    raw_params = binding.get("params")
    params: dict[str, Any] = {}
    if raw_params is not None:
        if not isinstance(raw_params, dict) or len(raw_params) > MAX_APP_BINDING_PARAMS:
            _fail(DashboardMessages.BINDING_INVALID)
        for key, value in raw_params.items():
            params[_check_identifier(key)] = _check_app_param(value)

    cleaned: dict[str, Any] = {
        "source": APP_BINDING_SOURCE,
        "app_uid": listing_uid,
        "source_id": source_id,
    }
    if params:
        cleaned["params"] = params
    return cleaned


def _check_app_param(value: Any) -> Any:
    """One parameter value, kept as the scalar it is.

    Deliberately not coerced: the source's own ``params_schema`` declares the
    type, and turning a ``true`` into a ``1`` here would quietly satisfy a check
    the fetch path is supposed to refuse.
    """
    if isinstance(value, bool) or isinstance(value, int):
        return value
    if isinstance(value, str) and len(value) <= MAX_APP_PARAM_LENGTH:
        return value
    _fail(DashboardMessages.BINDING_INVALID)


# --- presets ---------------------------------------------------------------
#
# A preset is a *named widget* built from a primitive plus fixed options. It
# ships no code, so it is the safe extension point: a marketplace listing
# declares presets, they resolve to a first-party primitive at validation time,
# and a definition that names one is stored resolved. Nothing a listing supplies
# ever becomes a renderer.
#
# Presets are a *storage* concept, not a palette one — the picker offers each
# primitive's options directly, so "bar chart" is the chart widget with its mark
# chosen rather than a second entry saying the same thing. The built-ins below
# stay because a stored or downloaded definition may still name them.


@dataclass(frozen=True)
class WidgetPreset:
    primitive: str
    options: Mapping[str, str]


WIDGET_PRESETS: dict[str, WidgetPreset] = {
    "bar_chart": WidgetPreset("chart", {"mark": "bar"}),
    "line_chart": WidgetPreset("chart", {"mark": "line"}),
    "area_chart": WidgetPreset("chart", {"mark": "area"}),
    "pie_chart": WidgetPreset("chart", {"mark": "pie"}),
    "stacked_bar_chart": WidgetPreset("chart", {"mark": "bar", "stacked": "true"}),
    "timeline": WidgetPreset("gantt", {"scale": "week"}),
    "percent_stat": WidgetPreset("stat", {"format": "percent"}),
}

# Every name a definition may use for a widget.
WIDGET_TYPES: frozenset[str] = frozenset(WIDGET_SPECS) | frozenset(WIDGET_PRESETS)

# Fail at import time, not request time: a preset pointing at a primitive that
# doesn't exist (or setting an option it doesn't accept) is a programming error.
for _name, _preset in WIDGET_PRESETS.items():
    if _preset.primitive not in WIDGET_SPECS:
        raise RuntimeError(f"preset {_name!r} names unknown primitive")
    _allowed = WIDGET_SPECS[_preset.primitive].options
    for _key, _value in _preset.options.items():
        if _key not in _allowed or _value not in _allowed[_key].values:
            raise RuntimeError(f"preset {_name!r} sets invalid option {_key}={_value}")
if WIDGET_SPECS.keys() & WIDGET_PRESETS.keys():
    raise RuntimeError("a preset may not shadow a primitive name")
for _name, _spec in WIDGET_SPECS.items():
    for _key, _declared in _spec.options.items():
        if _declared.default not in _declared.values:
            raise RuntimeError(f"{_name}.{_key} defaults to a value it does not allow")


# --- normalization ---------------------------------------------------------


def _require_mapping(value: Any, code: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        _fail(code)
    return value


def _clean_text(value: Any) -> str | None:
    """Plain text only — never markup. Non-strings are dropped rather than
    coerced, so a nested object can't smuggle itself into a rendered label."""
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped[:MAX_TITLE_LENGTH] if stripped else None


def _grid_int(value: Any, *, low: int, high: int, default: int | None) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return default
    return default if value < low or value > high else value


def _normalize_grid(raw: Any, spec: WidgetSpec) -> dict[str, int]:
    grid = raw if isinstance(raw, dict) else {}
    w = _grid_int(grid.get("w"), low=1, high=MAX_GRID_COLUMNS, default=None)
    h = _grid_int(grid.get("h"), low=1, high=MAX_GRID_ROWS, default=None)
    w = spec.default_w if w is None else min(max(w, spec.min_w), MAX_GRID_COLUMNS)
    h = spec.default_h if h is None else max(h, spec.min_h)
    x = _grid_int(grid.get("x"), low=0, high=MAX_GRID_COLUMNS - 1, default=0) or 0
    y = _grid_int(grid.get("y"), low=0, high=MAX_GRID_ROWS, default=0) or 0
    # Keep the widget inside the grid rather than rejecting the definition.
    if x + w > MAX_GRID_COLUMNS:
        x = max(0, MAX_GRID_COLUMNS - w)
    return {"x": x, "y": y, "w": w, "h": h}


#: Binding parameters the *definition* does not carry, because the request
#: already establishes them: a dashboard is fetched under a guild and belongs to
#: an initiative, so those come from the row it lives on rather than from
#: something an author or an installed listing typed.
#:
#: Every source shipping at launch reads within one initiative, so a definition
#: has nothing to express here. A later source that genuinely spans initiatives
#: would state its scope as part of that source's own contract, decided then,
#: rather than by re-opening a free-form id here.
_CONTEXT_ONLY_PARAMS = frozenset({"initiative_id", "guild_id"})


def _normalize_binding(
    raw: Any, spec: WidgetSpec, *, app_listing_uid: str | None = None
) -> dict[str, Any]:
    """Check the source is one we can fetch and this widget can draw, then keep
    its parameters as given for the fetcher to interpret."""
    binding = _require_mapping(raw, DashboardMessages.BINDING_INVALID)
    source = binding.get("source")

    if app_listing_uid is not None:
        # An app widget draws its own app's data and nothing else, so this is a
        # total branch rather than an extra allowed value.
        if source != APP_BINDING_SOURCE:
            _fail(DashboardMessages.BINDING_SOURCE_NOT_ALLOWED)
        return _normalize_app_binding(binding, app_listing_uid)

    if not isinstance(source, str) or source not in ALL_SOURCES:
        _fail(DashboardMessages.BINDING_SOURCE_UNKNOWN)
    if source not in spec.sources:
        _fail(DashboardMessages.BINDING_SOURCE_NOT_ALLOWED)
    params = {
        key: value
        for key, value in binding.items()
        if key != "source" and key not in _CONTEXT_ONLY_PARAMS
    }
    return {"source": source, **params}


def _normalize_options(raw: Any, spec: WidgetSpec, preset: WidgetPreset | None) -> dict:
    """Widget-level display options, checked against the primitive's allow-list.

    A preset's own options are applied last: they are what make it that preset,
    so a definition can fill in the rest but not contradict its identity.
    """
    supplied = raw if isinstance(raw, dict) else {}
    options: dict[str, str] = {}
    for key, value in supplied.items():
        allowed = spec.options.get(key)
        if allowed is None:
            continue
        # Booleans are accepted for flag-shaped options and stored as strings so
        # the option vocabulary stays a flat set of literals.
        candidate = str(value).lower() if isinstance(value, bool) else value
        if not isinstance(candidate, str) or candidate not in allowed.values:
            _fail(DashboardMessages.WIDGET_OPTION_INVALID)
        options[key] = candidate
    if preset is not None:
        options.update(preset.options)
    return options


def _normalize_widget(raw: Any, index: int, seen_ids: set[str]) -> dict[str, Any]:
    widget = _require_mapping(raw, DashboardMessages.WIDGET_INVALID)
    declared = widget.get("type")
    if not isinstance(declared, str):
        _fail(DashboardMessages.WIDGET_TYPE_UNKNOWN)

    # An app's widget keeps its namespaced type verbatim: the module that draws
    # it lives in the installed app's pinned definition, and this build resolves
    # it there rather than in the built-in registry.
    app_parts = app_widget_parts(declared)
    if app_parts is not None:
        preset = None
        primitive = declared
        spec = APP_WIDGET_SPEC
    else:
        if declared not in WIDGET_TYPES:
            _fail(DashboardMessages.WIDGET_TYPE_UNKNOWN)
        # Resolve a preset to its primitive, so what gets stored (and what the
        # renderer sees) is always a first-party widget kind.
        preset = WIDGET_PRESETS.get(declared)
        primitive = preset.primitive if preset else declared
        spec = WIDGET_SPECS[primitive]

    widget_id = _clean_text(widget.get("id")) or f"w{index + 1}"
    if widget_id in seen_ids:
        _fail(DashboardMessages.WIDGET_ID_DUPLICATE)
    seen_ids.add(widget_id)

    cleaned: dict[str, Any] = {
        "id": widget_id,
        "type": primitive,
        "grid": _normalize_grid(widget.get("grid"), spec),
        "binding": _normalize_binding(
            widget.get("binding"),
            spec,
            app_listing_uid=app_parts[0] if app_parts else None,
        ),
    }
    if preset is not None:
        # Kept for round-tripping and for labelling the widget in the palette.
        cleaned["preset"] = declared
    title = _clean_text(widget.get("title"))
    if title is not None:
        cleaned["title"] = title
    options = _normalize_options(widget.get("options"), spec, preset)
    if options:
        cleaned["options"] = options
    return cleaned


def normalize_dashboard_definition(payload: Any) -> dict[str, Any]:
    """Validate and canonicalize a dashboard definition.

    Raises ``DashboardDefinitionError`` with a machine code for a widget type or
    binding source this app has no renderer/fetcher for; returns a definition in
    canonical shape.
    """
    definition = _require_mapping(payload, DashboardMessages.DEFINITION_INVALID)

    if definition.get("schema_version", SCHEMA_VERSION) != SCHEMA_VERSION:
        _fail(DashboardMessages.DEFINITION_VERSION_UNSUPPORTED)

    raw_widgets = definition.get("widgets", [])
    if not isinstance(raw_widgets, list):
        _fail(DashboardMessages.DEFINITION_INVALID)
    if len(raw_widgets) > MAX_WIDGETS:
        _fail(DashboardMessages.TOO_MANY_WIDGETS)

    seen_ids: set[str] = set()
    widgets = [
        _normalize_widget(raw, index, seen_ids) for index, raw in enumerate(raw_widgets)
    ]

    raw_layout = definition.get("layout")
    layout = raw_layout if isinstance(raw_layout, dict) else {}
    columns = _grid_int(
        layout.get("columns"), low=1, high=MAX_GRID_COLUMNS, default=MAX_GRID_COLUMNS
    )

    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "dashboard",
        "layout": {"columns": columns},
        "widgets": widgets,
    }


def normalize_dashboard_config(
    payload: Any, definition: dict[str, Any]
) -> dict[str, Any]:
    """Validate instance config against a definition's widgets.

    Config fills the binding parameters a definition left open (the ids a
    catalog listing can't know). Entries naming a widget the definition doesn't
    have are dropped, so updating to a version that removes a widget can't leave
    dangling config behind. The parameter values are the fetcher's business,
    exactly as in a binding.
    """
    config = _require_mapping(payload, DashboardMessages.CONFIG_INVALID)
    raw_widgets = config.get("widgets")
    if raw_widgets is None:
        return {"widgets": {}}
    widget_config = _require_mapping(raw_widgets, DashboardMessages.CONFIG_INVALID)

    known_ids = {widget["id"] for widget in definition.get("widgets", [])}
    cleaned = {
        widget_id: values
        for widget_id, values in widget_config.items()
        if widget_id in known_ids and isinstance(values, dict) and values
    }
    return {"widgets": cleaned}
