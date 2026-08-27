"""Tests for dashboard definition/config validation.

The validator is a capability check: it admits only widget types we render and
binding sources we fetch, and leaves each binding's parameters to the fetcher
that consumes them. These tests pin both halves of that contract — what is
rejected, and what is deliberately passed through untouched.
"""

import pytest

from app.services.tenant.dashboard_definition import (
    ALL_SOURCES,
    MAX_WIDGETS,
    WIDGET_PRESETS,
    WIDGET_SPECS,
    WIDGET_TYPES,
    DashboardDefinitionError,
    normalize_dashboard_config,
    normalize_dashboard_definition,
)


def _definition(*widgets: dict) -> dict:
    return {"widgets": list(widgets)}


@pytest.mark.unit
def test_every_widget_source_is_a_known_source():
    """The derived source set can't drift from the widgets that declare it."""
    for widget_type, spec in WIDGET_SPECS.items():
        assert spec.sources, f"{widget_type} declares no sources"
        assert spec.sources <= ALL_SOURCES


@pytest.mark.unit
def test_presets_resolve_to_a_primitive_and_never_shadow_one():
    """A preset is a named configuration of a first-party widget — it ships no
    renderer, which is what makes it a safe extension point for the
    marketplace."""
    assert WIDGET_TYPES == set(WIDGET_SPECS) | set(WIDGET_PRESETS)
    assert not (set(WIDGET_SPECS) & set(WIDGET_PRESETS))
    for name, preset in WIDGET_PRESETS.items():
        spec = WIDGET_SPECS[preset.primitive]
        for key, value in preset.options.items():
            assert value in spec.options[key], f"{name}: bad option {key}={value}"


@pytest.mark.unit
def test_every_option_defaults_to_a_value_it_allows():
    """The default is what a widget draws when a definition names no value, and
    what the palette shows as chosen. One that is not in its own list would put
    the editor and the render out of step."""
    for widget_type, spec in WIDGET_SPECS.items():
        for key, option in spec.options.items():
            assert option.values, f"{widget_type}.{key} allows nothing"
            assert option.default in option.values, f"{widget_type}.{key} bad default"
            assert len(set(option.values)) == len(option.values), (
                f"{widget_type}.{key} repeats a value"
            )


@pytest.mark.unit
def test_preset_is_stored_resolved():
    """What lands in the row is always a primitive, with the preset name kept
    only as a label."""
    result = normalize_dashboard_definition(
        _definition(
            {
                "id": "bars",
                "type": "bar_chart",
                "binding": {"source": "task_counts", "bucket": "priority"},
            }
        )
    )
    widget = result["widgets"][0]
    assert widget["type"] == "chart"
    assert widget["preset"] == "bar_chart"
    assert widget["options"]["mark"] == "bar"


@pytest.mark.unit
def test_preset_options_win_over_supplied_ones():
    """A preset's own options are its identity — a bar_chart stays a bar."""
    result = normalize_dashboard_definition(
        _definition(
            {
                "type": "bar_chart",
                "options": {"mark": "pie"},
                "binding": {"source": "task_counts"},
            }
        )
    )
    assert result["widgets"][0]["options"]["mark"] == "bar"


@pytest.mark.unit
def test_rejects_unknown_option_value():
    with pytest.raises(DashboardDefinitionError, match="WIDGET_OPTION_INVALID"):
        normalize_dashboard_definition(
            _definition(
                {
                    "type": "chart",
                    "options": {"mark": "hologram"},
                    "binding": {"source": "task_counts"},
                }
            )
        )


@pytest.mark.unit
def test_unknown_option_keys_are_dropped():
    result = normalize_dashboard_definition(
        _definition(
            {
                "type": "chart",
                "options": {"mark": "line", "onClick": "steal"},
                "binding": {"source": "task_counts"},
            }
        )
    )
    assert result["widgets"][0]["options"] == {"mark": "line"}


@pytest.mark.unit
def test_normalizes_to_canonical_shape():
    result = normalize_dashboard_definition(
        _definition(
            {
                "id": "w1",
                "type": "gantt",
                "title": "  Delivery  ",
                "grid": {"x": 0, "y": 0, "w": 12, "h": 6},
                "binding": {"source": "tasks", "group_by": "project"},
            }
        )
    )

    assert result["schema_version"] == 1
    assert result["kind"] == "dashboard"
    assert result["layout"] == {"columns": 12}
    widget = result["widgets"][0]
    assert widget["title"] == "Delivery"
    assert widget["grid"] == {"x": 0, "y": 0, "w": 12, "h": 6}


@pytest.mark.unit
def test_widget_ids_are_assigned_and_must_be_unique():
    result = normalize_dashboard_definition(
        _definition(
            {"type": "stat", "binding": {"source": "counter"}},
            {"type": "stat", "binding": {"source": "counter"}},
        )
    )
    assert [w["id"] for w in result["widgets"]] == ["w1", "w2"]

    with pytest.raises(DashboardDefinitionError, match="WIDGET_ID_DUPLICATE"):
        normalize_dashboard_definition(
            _definition(
                {"id": "same", "type": "stat", "binding": {"source": "counter"}},
                {"id": "same", "type": "stat", "binding": {"source": "counter"}},
            )
        )


@pytest.mark.unit
def test_size_floor_is_enforced_per_widget_type():
    """A layout can't squeeze a widget below what it can legibly render."""
    result = normalize_dashboard_definition(
        _definition(
            {"type": "gantt", "grid": {"w": 1, "h": 1}, "binding": {"source": "tasks"}}
        )
    )
    grid = result["widgets"][0]["grid"]
    assert grid["w"] == WIDGET_SPECS["gantt"].min_w
    assert grid["h"] == WIDGET_SPECS["gantt"].min_h


@pytest.mark.unit
def test_widget_is_kept_inside_the_grid():
    result = normalize_dashboard_definition(
        _definition(
            {
                "type": "gantt",
                "grid": {"x": 9, "y": 0, "w": 12, "h": 6},
                "binding": {"source": "tasks"},
            }
        )
    )
    grid = result["widgets"][0]["grid"]
    assert grid["x"] + grid["w"] <= 12


@pytest.mark.unit
@pytest.mark.parametrize(
    "payload,code",
    [
        (
            {"widgets": [{"type": "evil", "binding": {"source": "tasks"}}]},
            "WIDGET_TYPE_UNKNOWN",
        ),
        (
            {"widgets": [{"type": "stat", "binding": {"source": "shell_exec"}}]},
            "BINDING_SOURCE_UNKNOWN",
        ),
        # A real source, but not one this widget can draw.
        (
            {"widgets": [{"type": "stat", "binding": {"source": "tasks"}}]},
            "BINDING_SOURCE_NOT_ALLOWED",
        ),
        ({"widgets": [{"type": "stat"}]}, "BINDING_INVALID"),
        ({"widgets": "nope"}, "DEFINITION_INVALID"),
        ({"schema_version": 99, "widgets": []}, "DEFINITION_VERSION_UNSUPPORTED"),
    ],
)
def test_rejects_unknown_vocabulary(payload, code):
    with pytest.raises(DashboardDefinitionError, match=code):
        normalize_dashboard_definition(payload)


@pytest.mark.unit
def test_rejects_too_many_widgets():
    widgets = [
        {"id": f"w{i}", "type": "stat", "binding": {"source": "counter"}}
        for i in range(MAX_WIDGETS + 1)
    ]
    with pytest.raises(DashboardDefinitionError, match="TOO_MANY_WIDGETS"):
        normalize_dashboard_definition({"widgets": widgets})


@pytest.mark.unit
def test_no_definition_can_name_an_endpoint():
    """The closed source vocabulary is what keeps a URL out of a definition —
    there is no source a URL could be smuggled through."""
    for candidate in ("https://evil.test/steal", "//evil.test", "file:///etc/passwd"):
        with pytest.raises(DashboardDefinitionError, match="BINDING_SOURCE_UNKNOWN"):
            normalize_dashboard_definition(
                _definition({"type": "stat", "binding": {"source": candidate}})
            )


@pytest.mark.unit
def test_binding_parameters_pass_through_untouched():
    """Parameters belong to the fetcher: the filter DSL enforces its own limits
    and ids are authorized by RLS at fetch time, so they are stored as given."""
    conditions = {
        "logic": "and",
        "conditions": [{"field": "priority", "op": "eq", "value": "high"}],
    }
    result = normalize_dashboard_definition(
        _definition(
            {
                "type": "gantt",
                "binding": {
                    "source": "tasks",
                    "conditions": conditions,
                    "group_by": "project",
                },
            }
        )
    )
    binding = result["widgets"][0]["binding"]
    assert binding["conditions"] == conditions
    assert binding["group_by"] == "project"


@pytest.mark.unit
def test_a_binding_cannot_name_its_own_initiative_or_guild():
    """Scope comes from the row the dashboard lives on, not from the definition.

    Every source at launch reads within one initiative, so there is nothing for
    these to express — and dropping them means an authored (or downloaded)
    definition has no field to point at somewhere else with.
    """
    result = normalize_dashboard_definition(
        _definition(
            {
                "type": "gantt",
                "binding": {
                    "source": "tasks",
                    "initiative_id": 999,
                    "guild_id": 42,
                    "project_id": 7,
                },
            }
        )
    )
    binding = result["widgets"][0]["binding"]
    assert "initiative_id" not in binding
    assert "guild_id" not in binding
    # A project is still the author's to choose; the fetcher scopes it.
    assert binding["project_id"] == 7


@pytest.mark.unit
def test_unknown_structural_keys_are_dropped():
    result = normalize_dashboard_definition(
        {
            "widgets": [
                {
                    "type": "stat",
                    "binding": {"source": "counter"},
                    "onClick": {"action": "delete_everything"},
                }
            ],
            "scripts": ["alert(1)"],
        }
    )
    assert "scripts" not in result
    assert "onClick" not in result["widgets"][0]


@pytest.mark.unit
def test_config_is_scoped_to_the_definitions_widgets():
    definition = normalize_dashboard_definition(
        _definition({"id": "w1", "type": "stat", "binding": {"source": "counter"}})
    )
    config = normalize_dashboard_config(
        {"widgets": {"w1": {"counter_id": 42}, "ghost": {"counter_id": 9}}},
        definition,
    )
    assert config == {"widgets": {"w1": {"counter_id": 42}}}


@pytest.mark.unit
def test_config_for_a_removed_widget_is_dropped():
    """Updating to a definition without that widget can't leave config behind."""
    definition = normalize_dashboard_definition(
        _definition({"id": "w2", "type": "stat", "binding": {"source": "counter"}})
    )
    assert normalize_dashboard_config(
        {"widgets": {"w1": {"counter_id": 1}}}, definition
    ) == {"widgets": {}}


# ---------------------------------------------------------------------------
# App widgets and the `app` binding source
# ---------------------------------------------------------------------------
#
# A service app's widget is a *separate* vocabulary from the built-ins, and the
# separation is what these pin. An app widget is namespaced, binds only `app`,
# and binds only its own app's sources — so a definition can never point one
# vendor's module at another vendor's data, and never resolve an app's widget to
# a built-in renderer.
#
# What a source *is* — its parameters, its visibility, its freshness — lives in
# the installed app's pinned definition and is enforced when the data is
# fetched. The validator's job here is shape, not authority.

APP_UID = "SHPAPP00000001"
OTHER_UID = "OTHERAPP000001"


def _app_widget(**overrides) -> dict:
    return {
        "id": "w1",
        "type": f"app:{APP_UID}:summary",
        "binding": {
            "source": "app",
            "app_uid": APP_UID,
            "endpoint_id": "app.acme.shop.orders-summary",
        },
        **overrides,
    }


@pytest.mark.unit
def test_an_app_widget_keeps_its_namespaced_type():
    result = normalize_dashboard_definition(_definition(_app_widget()))
    widget = result["widgets"][0]
    assert widget["type"] == f"app:{APP_UID}:summary"
    assert widget["binding"] == {
        "source": "app",
        "app_uid": APP_UID,
        "endpoint_id": "app.acme.shop.orders-summary",
    }
    # It still gets a grid, from the app-widget floor rather than a primitive's.
    assert widget["grid"]["w"] >= 2 and widget["grid"]["h"] >= 2


@pytest.mark.unit
def test_a_definition_outlives_the_app_its_widgets_came_from():
    """The check on an app widget is shape, never an install lookup.

    A stored dashboard is the guild's, so re-normalizing it — an edit, an
    upgrade — must keep accepting its app widgets whether or not the app is
    still installed. `app:<uid>:<widget>` with valid parts stores verbatim; the
    client renders the not-installed state and asks for the app to be
    reconnected. Only a malformed type is a rejection (the tests below).
    """
    definition = _definition(_app_widget())
    first = normalize_dashboard_definition(definition)
    # Idempotent under re-normalization: what was stored stays storable.
    assert normalize_dashboard_definition(first) == first


@pytest.mark.unit
def test_declared_parameters_are_kept_as_the_scalars_they_are():
    """Not coerced: the source's own params_schema declares the type, and
    turning a bool into an int here would satisfy a check the fetch path is
    meant to refuse."""
    result = normalize_dashboard_definition(
        _definition(
            _app_widget(
                binding={
                    "source": "app",
                    "app_uid": APP_UID,
                    "endpoint_id": "app.acme.shop.orders",
                    "params": {"range": "30d", "limit": 5, "detailed": True},
                }
            )
        )
    )
    assert result["widgets"][0]["binding"]["params"] == {
        "range": "30d",
        "limit": 5,
        "detailed": True,
    }


@pytest.mark.unit
def test_an_app_widget_cannot_bind_another_apps_data():
    with pytest.raises(DashboardDefinitionError):
        normalize_dashboard_definition(
            _definition(
                _app_widget(
                    binding={
                        "source": "app",
                        "app_uid": OTHER_UID,
                        "endpoint_id": "app.acme.shop.orders",
                    }
                )
            )
        )


@pytest.mark.unit
def test_an_app_widget_binds_only_the_app_source():
    for source in sorted(ALL_SOURCES):
        with pytest.raises(DashboardDefinitionError):
            normalize_dashboard_definition(
                _definition(_app_widget(binding={"source": source}))
            )


@pytest.mark.unit
def test_a_builtin_widget_cannot_bind_the_app_source():
    """An app's rows are opaque here, so no built-in could draw them."""
    with pytest.raises(DashboardDefinitionError):
        normalize_dashboard_definition(
            _definition(
                {
                    "id": "w1",
                    "type": "stat",
                    "binding": {
                        "source": "app",
                        "app_uid": APP_UID,
                        "endpoint_id": "app.acme.shop.orders",
                    },
                }
            )
        )


@pytest.mark.unit
def test_the_app_source_is_not_in_the_builtin_vocabulary():
    """`ALL_SOURCES` and `WIDGET_TYPES` stay the built-ins' own, so the served
    widget catalog and every drift test keep describing this build's renderers
    rather than whatever some guild happens to have installed."""
    assert "app" not in ALL_SOURCES
    assert not any(name.startswith("app:") for name in WIDGET_TYPES)


@pytest.mark.unit
@pytest.mark.parametrize(
    "widget_type",
    [
        "app:",
        "app:SHPAPP00000001",  # no widget id
        "app:SHPAPP00000001:",  # empty widget id
        "app:short:summary",  # uid is the wrong length
        "app:SHOPAPP000000!:summary",  # outside the uid alphabet
        "app:SHPAPP00000001:Summary!",  # outside the identifier set
    ],
)
def test_a_malformed_app_widget_type_is_refused(widget_type):
    with pytest.raises(DashboardDefinitionError):
        normalize_dashboard_definition(_definition(_app_widget(type=widget_type)))


@pytest.mark.unit
@pytest.mark.parametrize(
    "binding",
    [
        {"source": "app", "endpoint_id": "app.acme.shop.orders"},  # no app named
        {"source": "app", "app_uid": APP_UID},  # no source named
        {"source": "app", "app_uid": APP_UID, "endpoint_id": "Orders!"},
        {
            "source": "app",
            "app_uid": APP_UID,
            "endpoint_id": "app.acme.shop.orders",
            "params": [],
        },
        {
            "source": "app",
            "app_uid": APP_UID,
            "endpoint_id": "app.acme.shop.orders",
            "params": {"range": {"nested": 1}},
        },
        {
            "source": "app",
            "app_uid": APP_UID,
            "endpoint_id": "app.acme.shop.orders",
            "params": {"bad key": "x"},
        },
    ],
)
def test_a_malformed_app_binding_is_refused(binding):
    with pytest.raises(DashboardDefinitionError):
        normalize_dashboard_definition(_definition(_app_widget(binding=binding)))


@pytest.mark.unit
def test_an_app_binding_still_has_nowhere_to_put_an_address():
    """The rule that makes a stored definition safe: it names capabilities, not
    hosts. Where the app lives comes from the deployment's registration."""
    result = normalize_dashboard_definition(
        _definition(
            _app_widget(
                binding={
                    "source": "app",
                    "app_uid": APP_UID,
                    "endpoint_id": "app.acme.shop.orders",
                    "url": "https://evil.test/steal",
                    "base_url": "https://evil.test",
                }
            )
        )
    )
    binding = result["widgets"][0]["binding"]
    assert set(binding) == {"source", "app_uid", "endpoint_id"}
