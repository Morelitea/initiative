"""A reference crossing an export by the ref it had, and placed again on the
way in."""

import copy

import pytest

from app.core.references import references_in_body, references_in_text
from app.services.import_engine.references import (
    SOURCE_REF,
    detach_editor_references,
    detach_envelope_references,
    detach_markdown_references,
    has_source_references,
    place_editor_references,
    place_markdown_references,
)

pytestmark = pytest.mark.unit


def _editor(*inline: dict) -> dict:
    return {
        "root": {
            "type": "root",
            "children": [{"type": "paragraph", "children": list(inline)}],
        }
    }


def _inline(content: dict) -> list[dict]:
    return content["root"]["children"][0]["children"]


def _mention(entity_type: str, entity_id: int, text: str) -> dict:
    return {
        "type": "entity-mention",
        "version": 1,
        "entityType": entity_type,
        "entityId": entity_id,
        "text": text,
    }


def _chip(chip_kind: str, entity_id: int, text: str) -> dict:
    return {
        "type": "smart-chip",
        "version": 1,
        "chipKind": chip_kind,
        "entityId": entity_id,
        "text": text,
    }


def _wikilink(document_id: int, title: str) -> dict:
    return {
        "type": "wikilink",
        "version": 1,
        "documentId": document_id,
        "documentTitle": title,
        "text": title,
    }


def test_a_markdown_reference_crosses_as_the_ref_it_had():
    text = (
        "See #task[Fix the bug](41), #doc[Spec](7) and #wiki-page[Start](3), "
        "not #widget[Nope](9) or @[Ada](4)"
    )

    detached = detach_markdown_references(text)

    # Every spelling the composer writes reads as its kind; a word that names
    # no kind, and a person, are not references and are left as they were.
    assert detached == (
        "See #task[Fix the bug](task:41), #doc[Spec](document:7) and "
        "#wiki-page[Start](wiki_page:3), not #widget[Nope](9) or @[Ada](4)"
    )
    # Nothing reads a detached reference as one until it is placed.
    assert references_in_text(detached) == set()
    assert has_source_references(detached)
    assert not has_source_references(text)


def test_a_markdown_reference_is_placed_or_reduced_to_its_label():
    detached = "See #task[Fix the bug](task:41) and #doc[Spec](document:7)"

    placed = place_markdown_references(
        detached, lambda ref: 90 if ref == "task:41" else None
    )

    assert placed == "See #task[Fix the bug](90) and Spec"


def test_an_editor_reference_carries_a_ref_instead_of_an_id():
    content = _editor(
        {"type": "text", "text": "See "},
        _mention("task", 41, "Fix the bug"),
        _chip("task:status", 41, "In progress"),
        _wikilink(7, "Spec"),
        _mention("task", 0, "Waiting on a page"),
    )
    before = copy.deepcopy(content)

    detached = detach_editor_references(content)

    text, mention, chip, wikilink, waiting = _inline(detached)
    assert text == {"type": "text", "text": "See "}
    assert (mention["entityId"], mention[SOURCE_REF]) == (0, "task:41")
    assert (chip["entityId"], chip[SOURCE_REF]) == (0, "task:41")
    assert (wikilink["documentId"], wikilink[SOURCE_REF]) == (None, "document:7")
    # A node that names nothing yet is not something to carry.
    assert SOURCE_REF not in waiting
    assert references_in_body(detached) == set()
    assert has_source_references(detached)
    # The loaded row's column is never edited in place.
    assert content == before


def test_an_exported_editor_reference_is_placed_or_left_as_words():
    detached = detach_editor_references(
        _editor(
            _mention("task", 41, "Fix the bug"),
            _mention("document", 8, "Gone"),
            _chip("task:status", 42, "Done"),
            _wikilink(7, "Spec"),
        )
    )

    placed = place_editor_references(
        detached, lambda ref: 90 if ref == "task:41" else None
    )

    mention, gone, chip, wikilink = _inline(placed)
    assert mention["entityId"] == 90 and SOURCE_REF not in mention
    # A reference to nothing here is its words, never somebody else's row.
    assert gone["type"] == "text" and gone["text"] == "Gone"
    assert chip["type"] == "text" and chip["text"] == "Done"
    # A wikilink stays one, unlinked — how the editor draws a missing page.
    assert wikilink["type"] == "wikilink"
    assert wikilink["documentId"] is None and SOURCE_REF not in wikilink
    assert not has_source_references(placed)


def test_a_reference_written_before_refs_crossed_is_left_as_it_was():
    """A body from an older export still names things by id; placing has
    nothing to say about it."""
    content = _editor(_mention("task", 41, "Fix the bug"))

    assert place_editor_references(content, lambda _ref: 90) == content
    assert place_markdown_references("#task[x](41)", lambda _ref: 90) == "#task[x](41)"


def test_an_envelope_detaches_its_bodies_and_says_where_it_was_taken():
    from app.core.config import settings

    envelope = {
        "type": "initiative-wiki",
        "pages": [
            {"content": _editor(_mention("post", 5, "Notice"))},
            {"content": _editor({"type": "text", "text": "plain"})},
        ],
    }

    detach_envelope_references(envelope, guild_id=12)

    first, second = envelope["pages"]
    assert _inline(first["content"])[0][SOURCE_REF] == "post:5"
    assert not has_source_references(second["content"])
    assert envelope["source_guild_id"] == 12
    assert envelope["source_instance_url"] == settings.APP_URL
