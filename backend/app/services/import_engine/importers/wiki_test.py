"""The wiki importer's placing of what a page names."""

from __future__ import annotations

import pytest

from app.services.import_engine.importers.wiki import WikiImporter, _place_references

pytestmark = pytest.mark.unit


def _doc(*inline):
    return {
        "root": {
            "type": "root",
            "children": [{"type": "paragraph", "children": list(inline)}],
        }
    }


def _page_mention(slug, text="Target"):
    return {
        "type": "entity-mention",
        "version": 1,
        "entityType": "wiki_page",
        "entityId": 0,
        "text": text,
        "importSlug": slug,
    }


def _person(name, user_id=None):
    return {
        "type": "mention",
        "version": 1,
        "mentionName": name,
        "mentionUserId": user_id,
        "text": name,
    }


def test_a_page_mention_points_at_the_page_its_slug_became():
    placed = _place_references(
        _doc(_page_mention("guide")), page_ids={"guide": 12}, mentioned={}
    )
    assert placed is not None
    (node,) = placed["root"]["children"][0]["children"]
    assert node["entityId"] == 12 and "importSlug" not in node


def test_a_mention_of_a_page_that_did_not_arrive_is_its_words_again():
    placed = _place_references(
        _doc(_page_mention("gone", "The old page")), page_ids={}, mentioned={}
    )
    assert placed is not None
    (node,) = placed["root"]["children"][0]["children"]
    assert node["type"] == "text" and node["text"] == "The old page"


def test_a_person_placed_by_the_people_step_is_linked_and_nobody_else_is():
    placed = _place_references(
        _doc(_person("Sam Bee"), _person("Nobody"), _person("Already", 3)),
        page_ids={},
        mentioned={"Sam Bee": 7, "Already": 9},
    )
    assert placed is not None
    sam, nobody, already = placed["root"]["children"][0]["children"]
    assert sam["mentionUserId"] == 7
    assert nobody["mentionUserId"] is None
    # A mention that already names an account is somebody else's to change.
    assert already["mentionUserId"] == 3


def test_content_with_nothing_to_place_is_left_as_it_was():
    assert (
        _place_references(
            _doc({"type": "text", "text": "x"}), page_ids={}, mentioned={}
        )
        is None
    )
    assert _place_references("not a document", page_ids={}, mentioned={}) is None


def test_the_people_a_wiki_names_are_asked_about_most_named_first():
    importer = WikiImporter()
    envelope = importer.validate(
        {
            "type": "initiative-wiki",
            "name": "Docs",
            "pages": [
                {
                    "title": "A",
                    "slug": "a",
                    "author_handle": "Robin",
                    "author_name": "Robin Ade",
                    "mention_handles": ["Sam"],
                },
                {
                    "title": "B",
                    "slug": "b",
                    "author_handle": "robin",
                    "mention_handles": [],
                },
                {"title": "C", "slug": "c"},
            ],
        }
    )
    people = importer.people(envelope)
    assert [(p.handle, p.name) for p in people] == [
        ("Robin", "Robin Ade"),
        ("Sam", None),
    ]
