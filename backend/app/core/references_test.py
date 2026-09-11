"""Reading a reference back.

``format_ref`` writes ``task:12``; this is the half that reads one. Every
trigger stores that shape, so one parser owning it is what keeps `#`, `[[ ]]`
and a smart chip agreeing about what a string names.
"""

from __future__ import annotations

from app.core.references import format_ref, parse_ref
from app.core.search import SearchEntityType


def test_a_reference_reads_back_as_what_was_written():
    for entity_type in SearchEntityType:
        if entity_type is SearchEntityType.comment:
            continue
        assert parse_ref(format_ref(entity_type, 12)) == (entity_type, 12)


def test_a_comment_is_not_something_a_reference_names():
    """A comment is a remark ON something — the thing it is on is what a reader
    wants — so the vocabulary does not admit one."""
    assert parse_ref("comment:3") is None


def test_a_kind_this_build_does_not_know_names_nothing():
    assert parse_ref("sandwich:3") is None


def test_a_string_that_is_not_a_reference_names_nothing():
    for ref in ("", "task", "task:", ":12", "task:abc", "task:-1", "12:task"):
        assert parse_ref(ref) is None, ref


def test_an_aspect_is_not_part_of_the_bare_form():
    """``task:12:status`` names a fact about a thing. That is the smart-chip
    shape, read by the parser that knows which facts exist."""
    assert parse_ref("task:12:status") is None
