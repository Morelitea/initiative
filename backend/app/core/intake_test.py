"""The stream registry, and the blueprints that must agree with it."""

from __future__ import annotations

import pytest

from app.blueprints.intake import blueprint_for
from app.core.intake import (
    CASE_FIELD_TYPES,
    STREAM_FIELDS,
    STREAMS,
    CaseField,
    IntakeStream,
    meta,
)
from app.models.tenant.property import PropertyType
from app.models.tenant.task import TaskStatusCategory

pytestmark = pytest.mark.unit


def test_every_stream_says_what_feeds_it():
    assert set(STREAMS) == set(IntakeStream)
    assert set(STREAM_FIELDS) == set(IntakeStream)


def test_every_case_field_has_a_real_property_type():
    assert set(CASE_FIELD_TYPES) == set(CaseField)
    for field, declared in CASE_FIELD_TYPES.items():
        assert PropertyType(declared), field


def test_tracker_key_belongs_to_security_alone():
    """It names a finding in the private repository, which only security gets."""
    carrying = {
        s for s, fields in STREAM_FIELDS.items() if CaseField.tracker_key in fields
    }
    assert carrying == {IntakeStream.security}


@pytest.mark.parametrize("stream", list(IntakeStream))
def test_every_stream_ships_a_blueprint_that_parses(stream: IntakeStream):
    envelope = blueprint_for(stream)
    assert envelope.project.name
    assert envelope.task_statuses
    assert meta(stream).blueprint.endswith(".json")


@pytest.mark.parametrize("stream", list(IntakeStream))
def test_a_blueprint_defines_exactly_the_streams_case_fields(stream: IntakeStream):
    """The writer fills these by name, so the two declarations must agree."""
    envelope = blueprint_for(stream)
    defined = {
        definition.name: definition.type for definition in envelope.property_definitions
    }
    expected = {
        field.value: PropertyType(CASE_FIELD_TYPES[field])
        for field in STREAM_FIELDS[stream]
    }
    assert defined == expected


@pytest.mark.parametrize("stream", list(IntakeStream))
def test_a_blueprint_can_open_and_close_a_case(stream: IntakeStream):
    """A stream whose statuses had no ``done`` could never record a closure."""
    envelope = blueprint_for(stream)
    categories = {status.category for status in envelope.task_statuses}
    assert TaskStatusCategory.done in categories
    assert sum(1 for status in envelope.task_statuses if status.is_default) == 1


@pytest.mark.parametrize("stream", list(IntakeStream))
def test_a_blueprint_seeds_one_task_explaining_the_project(stream: IntakeStream):
    assert len(blueprint_for(stream).tasks) == 1
    seed = blueprint_for(stream).tasks[0]
    assert seed.description
    status_names = {status.name for status in blueprint_for(stream).task_statuses}
    assert seed.status_name in status_names
