"""Which references count as a link between documents.

Backlinks — "what points at this page" — are built from what a document's
content refers to. This is the part that decides.
"""

from __future__ import annotations

from typing import Any

from app.services.tenant.documents import extract_linked_document_ids


def _doc(*nodes: dict[str, Any]) -> dict[str, Any]:
    return {"root": {"children": [{"type": "paragraph", "children": list(nodes)}]}}


def _wikilink(document_id: int) -> dict[str, Any]:
    return {"type": "wikilink", "documentId": document_id, "documentTitle": "Some page"}


def _reference(entity_type: str, entity_id: int) -> dict[str, Any]:
    return {"type": "entity-mention", "entityType": entity_type, "entityId": entity_id}


def test_a_hash_reference_to_a_document_is_a_link():
    """The defect this fixes: `#` fed nothing, so the graph under-reported the
    moment anyone used it."""
    assert extract_linked_document_ids(_doc(_reference("document", 7))) == {7}


def test_a_wikilink_still_counts():
    """Written before references were one thing, and still sitting in stored
    documents."""
    assert extract_linked_document_ids(_doc(_wikilink(3))) == {3}


def test_both_triggers_land_in_one_graph():
    content = _doc(_wikilink(3), _reference("document", 7))
    assert extract_linked_document_ids(content) == {3, 7}


def test_a_reference_to_something_that_is_not_a_document_is_not_a_document_link():
    """A page about a task links to the task, not to a page."""
    content = _doc(_reference("task", 12), _reference("queue", 4))
    assert extract_linked_document_ids(content) == set()


def test_a_chip_is_a_reading_not_a_link():
    """A chip shows what something is doing; it does not point at a page."""
    content = _doc({"type": "smart-chip", "chipKind": "task:status", "entityId": 9})
    assert extract_linked_document_ids(content) == set()


def test_references_are_found_however_deep_they_sit():
    nested = {
        "root": {
            "children": [
                {
                    "type": "list",
                    "children": [
                        {"type": "listitem", "children": [_reference("document", 5)]}
                    ],
                }
            ]
        }
    }
    assert extract_linked_document_ids(nested) == {5}


def test_content_that_is_not_a_document_yields_nothing():
    assert extract_linked_document_ids(None) == set()
    assert extract_linked_document_ids({}) == set()


def test_an_unresolved_reference_is_not_a_link():
    """A wikilink whose target was deleted is left pointing at nothing rather
    than at a document that no longer exists."""
    assert (
        extract_linked_document_ids(_doc({"type": "wikilink", "documentId": None}))
        == set()
    )
