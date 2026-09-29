"""Jira fields → properties (§6.5): only what somebody filled, typed by schema."""

import pytest

from app.services.import_engine import jira_fields as jf


def _issue(key, **fields):
    return {"key": key, "fields": {"summary": key, **fields}}


def _custom(field_id, name, type_, *, items=None, custom=None):
    schema = {"type": type_}
    if items:
        schema["items"] = items
    if custom:
        schema["custom"] = custom
    return {"id": field_id, "name": name, "custom": True, "schema": schema}


def _by_name(mapped):
    return {d["name"]: d for d in mapped.definitions}


def _values(mapped, key):
    return {v["property_name"]: v for v in mapped.values_by_issue[key]}


def test_a_field_nobody_filled_creates_nothing():
    """The first rule: a definition exists only where some issue carries a
    value. An empty field on every issue is a column nobody ever used."""
    catalog = [
        _custom("customfield_1", "Story points", "number"),
        _custom("customfield_2", "Never used", "string"),
    ]
    mapped = jf.map_fields(
        catalog,
        [
            _issue("ACME-1", customfield_1=3, customfield_2=None),
            _issue("ACME-2", customfield_2=""),
        ],
    )
    names = _by_name(mapped)
    assert "Story points" in names
    assert "Never used" not in names
    assert mapped.issue_counts["Story points"] == 1


def test_every_task_carries_its_jira_key():
    mapped = jf.map_fields([], [_issue("ACME-7")])
    assert _by_name(mapped)["Jira key"]["type"] == "text"
    assert _values(mapped, "ACME-7")["Jira key"]["value_text"] == "ACME-7"


def test_select_options_are_the_values_seen_not_the_allowed_set():
    """Options come from what issues used, in the order first seen."""
    catalog = [_custom("customfield_3", "Team", "option")]
    mapped = jf.map_fields(
        catalog,
        [
            _issue("ACME-1", customfield_3={"value": "Blue"}),
            _issue("ACME-2", customfield_3={"value": "Red"}),
            _issue("ACME-3", customfield_3={"value": "Blue"}),
        ],
    )
    team = _by_name(mapped)["Team"]
    assert team["type"] == "select"
    assert [o["value"] for o in team["options"]] == ["Blue", "Red"]
    assert _values(mapped, "ACME-2")["Team"]["value_text"] == "Red"


@pytest.mark.parametrize(
    "entry,value,expected_type,column,expected",
    [
        (_custom("c", "Notes", "string"), " hello ", "text", "value_text", "hello"),
        (
            _custom(
                "c",
                "Spec",
                "string",
                custom="com.atlassian.jira.plugin.system.customfieldtypes:url",
            ),
            "https://example.com",
            "url",
            "value_text",
            "https://example.com",
        ),
        (_custom("c", "Points", "number"), 5, "number", "value_number", 5.0),
        (
            _custom("c", "Launch", "date"),
            "2026-03-04",
            "date",
            "value_text",
            "2026-03-04",
        ),
        (
            _custom("c", "Signed off", "datetime"),
            "2024-03-04T09:30:00.000+0100",
            "datetime",
            "value_text",
            "2024-03-04T08:30:00+00:00",
        ),
        (
            _custom("c", "Flags", "array", items="option"),
            [{"value": "Impediment"}, {"value": "Impediment"}],
            "multi_select",
            "value_json",
            ["Impediment"],
        ),
        (
            _custom("c", "Keywords", "array", items="string"),
            ["a", "b"],
            "multi_select",
            "value_json",
            ["a", "b"],
        ),
        (
            _custom("c", "Region", "option-with-child"),
            {"value": "EU", "child": {"value": "Berlin"}},
            "text",
            "value_text",
            "EU → Berlin",
        ),
        (
            _custom("c", "Reviewer", "user"),
            {"displayName": "Robin", "emailAddress": None},
            "user_reference",
            "value_handle",
            "Robin",
        ),
    ],
)
def test_the_schema_decides_the_type(entry, value, expected_type, column, expected):
    mapped = jf.map_fields([entry], [_issue("ACME-1", c=value)])
    definition = _by_name(mapped)[entry["name"]]
    assert definition["type"] == expected_type
    assert _values(mapped, "ACME-1")[entry["name"]][column] == expected


def test_a_rich_text_field_arrives_as_markdown():
    doc = {
        "type": "doc",
        "version": 1,
        "content": [
            {
                "type": "paragraph",
                "content": [
                    {"type": "text", "text": "Bold", "marks": [{"type": "strong"}]}
                ],
            }
        ],
    }
    mapped = jf.map_fields([_custom("c", "Notes", "string")], [_issue("ACME-1", c=doc)])
    assert _values(mapped, "ACME-1")["Notes"]["value_text"] == "**Bold**"


def test_the_built_ins_map_by_their_own_ids_without_a_catalog():
    """A catalog the site would not give still leaves Jira's own fields,
    whose ids are the same on every site."""
    mapped = jf.map_fields(
        [],
        [
            _issue(
                "ACME-1",
                priority={"name": "Highest"},
                issuetype={"name": "Bug"},
                reporter={"displayName": "Robin"},
                fixVersions=[{"name": "1.0"}, {"name": "1.1"}],
                timeoriginalestimate=5400,
                resolutiondate="2024-05-01T12:00:00.000+0000",
            )
        ],
    )
    values = _values(mapped, "ACME-1")
    assert values["Priority"]["value_text"] == "Highest"
    assert values["Issue type"]["value_text"] == "Bug"
    assert values["Reporter"]["value_handle"] == "Robin"
    assert values["Fix versions"]["value_json"] == ["1.0", "1.1"]
    assert values["Original estimate (hours)"]["value_number"] == 1.5
    assert values["Resolved"]["value_text"].startswith("2024-05-01T12:00:00")


def test_what_has_no_home_is_dropped_and_named_only_if_filled():
    """Several people in one field, a service desk's records, a type nobody
    knows: named in the plan so nobody is surprised — but only when an issue
    actually used it."""
    catalog = [
        _custom("c1", "Watchers too", "array", items="user"),
        _custom(
            "c2",
            "SLA",
            "sd-servicelevelagreement",
            custom="com.atlassian.servicedesk:sla",
        ),
        _custom("c3", "Mystery", "any"),
        _custom("c4", "Empty mystery", "any"),
    ]
    mapped = jf.map_fields(
        catalog,
        [
            _issue(
                "ACME-1",
                c1=[{"displayName": "A"}],
                c2={"ongoingCycle": {}},
                c3={"x": 1},
                c4=None,
            )
        ],
    )
    assert mapped.dropped_fields == ["Mystery", "SLA", "Watchers too"]
    assert set(_by_name(mapped)) == {"Jira key"}


def test_fields_with_a_home_elsewhere_are_not_properties():
    """Rank is the order, Sprint is the sprints item, the Epic fields are the
    parent link: none of them is a column."""
    catalog = [
        _custom("r", "Rank", "any", custom="com.pyxis.greenhopper.jira:gh-lexo-rank"),
        _custom(
            "s",
            "Sprint",
            "array",
            items="json",
            custom="com.pyxis.greenhopper.jira:gh-sprint",
        ),
    ]
    mapped = jf.map_fields(catalog, [_issue("ACME-1", r="0|i0000:", s=[{"id": 1}])])
    assert set(_by_name(mapped)) == {"Jira key"}
    assert mapped.dropped_fields == []


def test_a_start_date_field_fills_the_task_not_a_property():
    mapped = jf.map_fields(
        [_custom("c", "Start date", "date")], [_issue("ACME-1", c="2026-02-01")]
    )
    assert mapped.start_dates == {"ACME-1": "2026-02-01"}
    assert "Start date" not in _by_name(mapped)


def test_two_fields_sharing_a_name_stay_two_properties():
    catalog = [
        _custom("c1", "Estimate", "number"),
        _custom("c2", "estimate", "string"),
    ]
    mapped = jf.map_fields(catalog, [_issue("ACME-1", c1=2, c2="two")])
    assert {"Estimate", "estimate (2)"} <= set(_by_name(mapped))


def test_the_mapping_produces_values_the_envelope_accepts():
    """Validated against the real project envelope, as the rest of the
    mapping is: the apply path will not bend to what a site sends."""
    from app.schemas.tenant.project_export import (
        ProjectExportPropertyDefinition,
        ProjectExportPropertyValue,
    )

    catalog = [
        _custom("c1", "Team", "option"),
        _custom("c2", "Flags", "array", items="option"),
        _custom("c3", "Points", "number"),
    ]
    mapped = jf.map_fields(
        catalog,
        [
            _issue(
                "ACME-1",
                c1={"value": "Blue"},
                c2=[{"value": "Impediment"}],
                c3=3,
                reporter={"displayName": "Robin"},
                resolutiondate="2024-05-01T12:00:00.000+0000",
            )
        ],
    )
    for definition in mapped.definitions:
        ProjectExportPropertyDefinition.model_validate(definition)
    for value in mapped.values_by_issue["ACME-1"]:
        ProjectExportPropertyValue.model_validate(value)
