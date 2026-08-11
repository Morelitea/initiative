"""Validation and normalization for dashboard definitions.

A definition is a **presentation spec**: a grid layout plus widgets, each bound
to a data source by name. Most dashboards — hand-built or installed from the
marketplace — are simply a *composition* of the built-in widgets below: a "KPI
dashboard" listing is several first-party widgets, arranged and pre-bound. The
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
class WidgetSpec:
    min_w: int
    min_h: int
    default_w: int
    default_h: int
    sources: frozenset[str]
    # Widget-level options this primitive accepts, each with its allowed values.
    # A preset's params and a definition's own options are checked against this.
    options: Mapping[str, frozenset[str]] = field(default_factory=dict)


WIDGET_SPECS: dict[str, WidgetSpec] = {
    # A timeline needs width to be readable at all.
    "gantt": WidgetSpec(
        min_w=6,
        min_h=3,
        default_w=12,
        default_h=6,
        sources=frozenset({"tasks", "projects", "calendar_entries"}),
        options={"scale": frozenset({"day", "week", "month", "quarter"})},
    ),
    # One big number.
    "kpi": WidgetSpec(
        min_w=2,
        min_h=2,
        default_w=3,
        default_h=2,
        sources=frozenset({"counter", "task_counts", "my_stats", "sheet_range"}),
        options={"format": frozenset({"plain", "percent", "currency", "duration"})},
    ),
    # A series drawn as bars/lines/area/slices.
    "chart": WidgetSpec(
        min_w=3,
        min_h=3,
        default_w=6,
        default_h=4,
        sources=frozenset(
            {"task_counts", "counter_group", "sheet_range", "my_stats", "projects"}
        ),
        options={
            "mark": frozenset({"bar", "line", "area", "pie"}),
            "stacked": frozenset({"true", "false"}),
        },
    ),
    # Staged counts, widest bucket first.
    "funnel": WidgetSpec(
        min_w=3,
        min_h=3,
        default_w=6,
        default_h=5,
        sources=frozenset({"task_counts", "sheet_range"}),
    ),
    # A completion bar — a counter against its own min/max, or a done ratio.
    "progress": WidgetSpec(
        min_w=2,
        min_h=1,
        default_w=4,
        default_h=2,
        sources=frozenset({"counter", "task_counts", "projects"}),
    ),
    # Density over a calendar grid (the shape /me/stats already returns).
    "heatmap": WidgetSpec(
        min_w=4,
        min_h=2,
        default_w=8,
        default_h=3,
        sources=frozenset({"my_stats", "task_counts"}),
    ),
    # A plain read-only table. Display only, like every widget: no row actions,
    # no inline editing — that is a project view's job, not a dashboard's.
    "table": WidgetSpec(
        min_w=4,
        min_h=3,
        default_w=12,
        default_h=5,
        sources=frozenset({"tasks", "projects", "sheet_range", "calendar_entries"}),
    ),
}

# Derived, so a source is named exactly once — on the widgets that render it.
ALL_SOURCES: frozenset[str] = frozenset().union(
    *(spec.sources for spec in WIDGET_SPECS.values())
)


# --- presets ---------------------------------------------------------------
#
# A preset is a *named widget* built from a primitive plus fixed options. It
# ships no code, so it is the safe extension point: the built-ins below give
# the palette its ready-made entries ("Bar chart"), and the same mechanism is
# how a marketplace listing will contribute custom widgets — a listing declares
# presets, they resolve to a first-party primitive at validation time, and a
# definition that names one is stored resolved. Nothing a listing supplies ever
# becomes a renderer.


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
    "percent_kpi": WidgetPreset("kpi", {"format": "percent"}),
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
        if _key not in _allowed or _value not in _allowed[_key]:
            raise RuntimeError(f"preset {_name!r} sets invalid option {_key}={_value}")
if WIDGET_SPECS.keys() & WIDGET_PRESETS.keys():
    raise RuntimeError("a preset may not shadow a primitive name")


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


def _normalize_binding(raw: Any, spec: WidgetSpec) -> dict[str, Any]:
    """Check the source is one we can fetch and this widget can draw, then keep
    its parameters as given for the fetcher to interpret."""
    binding = _require_mapping(raw, DashboardMessages.BINDING_INVALID)
    source = binding.get("source")
    if not isinstance(source, str) or source not in ALL_SOURCES:
        _fail(DashboardMessages.BINDING_SOURCE_UNKNOWN)
    if source not in spec.sources:
        _fail(DashboardMessages.BINDING_SOURCE_NOT_ALLOWED)
    params = {key: value for key, value in binding.items() if key != "source"}
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
        if not isinstance(candidate, str) or candidate not in allowed:
            _fail(DashboardMessages.WIDGET_OPTION_INVALID)
        options[key] = candidate
    if preset is not None:
        options.update(preset.options)
    return options


def _normalize_widget(raw: Any, index: int, seen_ids: set[str]) -> dict[str, Any]:
    widget = _require_mapping(raw, DashboardMessages.WIDGET_INVALID)
    declared = widget.get("type")
    if not isinstance(declared, str) or declared not in WIDGET_TYPES:
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
        "binding": _normalize_binding(widget.get("binding"), spec),
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
