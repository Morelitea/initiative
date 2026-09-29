"""Finding the people an envelope names in its user-type property values."""

import pytest

from app.services.import_engine.people import user_reference_handles


def _value(handle, property_type="user_reference"):
    return {
        "property_name": "Reporter",
        "property_type": property_type,
        "value_handle": handle,
    }


def test_user_values_are_found_at_any_depth():
    """A task's properties sit two levels down, a document's one, an event's
    two again; the walk does not care which."""
    envelope = {
        "properties": [_value("Robin")],
        "tasks": [{"property_values": [_value("Sam"), _value("Robin")]}],
        "events": [{"properties": [_value("Ash")]}],
    }
    assert user_reference_handles(envelope) == ["Robin", "Sam", "Ash"]


def test_one_person_spelled_two_ways_is_one_person():
    assert user_reference_handles([_value("Robin"), _value("  robin ")]) == ["Robin"]


@pytest.mark.parametrize(
    "value",
    [
        _value(None),
        _value(""),
        _value("   "),
        _value(42),
        # Any other type's value_handle is not a person.
        _value("Robin", property_type="text"),
    ],
)
def test_what_names_nobody_is_ignored(value):
    assert user_reference_handles({"properties": [value]}) == []
