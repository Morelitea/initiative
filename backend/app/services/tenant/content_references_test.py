"""What a body says it is about, and which of it the graph keeps.

The first half decides what counts as a reference — one vocabulary, whether it
was written as ``[[ ]]`` in a document or as ``#`` in a comment. The second
decides which of those become ``references`` edges, and when one goes away.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlmodel import select

from app.core.references import references_in_body, references_in_text
from app.core.relationships import Provenance, RelationshipType
from app.core.search import SearchEntityType
from app.models.platform.guild import GuildRole
from app.models.tenant.relationship import EntityRelationship
from app.services.tenant import content_references
from app.services.tenant.relationships import Endpoint
from app.testing import create_comment, create_document, create_project, create_task


def _doc(*nodes: dict[str, Any]) -> dict[str, Any]:
    return {"root": {"children": [{"type": "paragraph", "children": list(nodes)}]}}


def _wikilink(document_id: int) -> dict[str, Any]:
    return {"type": "wikilink", "documentId": document_id, "documentTitle": "Some page"}


def _reference(entity_type: str, entity_id: int) -> dict[str, Any]:
    return {"type": "entity-mention", "entityType": entity_type, "entityId": entity_id}


DOCUMENT = SearchEntityType.document
TASK = SearchEntityType.task


# ---------------------------------------------------------------------------
# What counts as a reference
# ---------------------------------------------------------------------------


def test_a_hash_reference_is_a_reference():
    assert references_in_body(_doc(_reference("document", 7))) == {(DOCUMENT, 7)}


def test_a_wikilink_still_counts():
    """Written before references were one thing, and still sitting in stored
    documents."""
    assert references_in_body(_doc(_wikilink(3))) == {(DOCUMENT, 3)}


def test_both_triggers_land_in_one_graph():
    content = _doc(_wikilink(3), _reference("document", 7))
    assert references_in_body(content) == {(DOCUMENT, 3), (DOCUMENT, 7)}


def test_a_reference_to_something_that_is_not_a_document_counts_too():
    """The whole of what this phase adds: a page about a task refers to that
    task, and until now only the documents were kept."""
    content = _doc(_reference("task", 12), _reference("queue", 4))
    assert references_in_body(content) == {
        (TASK, 12),
        (SearchEntityType.queue, 4),
    }


def test_a_chip_is_a_reading_not_a_reference():
    """A chip shows what something is doing; it does not point at a page."""
    content = _doc({"type": "smart-chip", "chipKind": "task:status", "entityId": 9})
    assert references_in_body(content) == set()


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
    assert references_in_body(nested) == {(DOCUMENT, 5)}


def test_content_that_is_not_a_body_yields_nothing():
    assert references_in_body(None) == set()
    assert references_in_body({}) == set()


def test_an_unresolved_reference_is_not_a_reference():
    """A wikilink whose target was deleted is left pointing at nothing rather
    than at a document that no longer exists."""
    assert references_in_body(_doc({"type": "wikilink", "documentId": None})) == set()


def test_a_hash_in_running_text_is_a_reference():
    """What a comment is written in."""
    assert references_in_text("see #task[Fix the bug](12) first") == {(TASK, 12)}


def test_a_hash_naming_no_known_kind_is_not_a_reference():
    assert references_in_text("#widget[Nope](3)") == set()


def test_a_user_mention_is_not_a_reference():
    """People are not things an edge connects."""
    assert references_in_text("thanks @[Ada](4)") == set()


# ---------------------------------------------------------------------------
# Which of them become edges
# ---------------------------------------------------------------------------


async def _references(session, entity: Endpoint) -> set[tuple[str, int]]:
    """What the graph says this thing refers to."""
    rows = await session.exec(
        select(EntityRelationship.target_type, EntityRelationship.target_id).where(
            EntityRelationship.source_node == entity.node,
            EntityRelationship.relationship_type == RelationshipType.references.value,
            EntityRelationship.removed_at.is_(None),
        )
    )
    return set(rows.all())


@pytest.mark.integration
async def test_a_document_does_not_reference_itself(session, acting_user):
    """The page a self-link opens is the page it was written on, and the row
    would list the document among the ones that point at it."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    doc = await create_document(session, a.initiative, a.user)
    other = await create_document(session, a.initiative, a.user)
    anchor = Endpoint(DOCUMENT, doc.id)

    await content_references.sync_for_entity(
        session,
        anchor,
        body=_doc(_wikilink(doc.id), _wikilink(other.id)),
        author_id=a.user.id,
    )

    assert await _references(session, anchor) == {("document", other.id)}


@pytest.mark.integration
async def test_a_body_naming_a_task_records_it(session, acting_user):
    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)
    doc = await create_document(session, a.initiative, a.user)
    task = await create_task(session, a.project)
    anchor = Endpoint(DOCUMENT, doc.id)

    await content_references.sync_for_entity(
        session, anchor, body=_doc(_reference("task", task.id)), author_id=a.user.id
    )

    assert await _references(session, anchor) == {("task", task.id)}


@pytest.mark.integration
async def test_a_reference_to_something_that_is_not_there_is_not_recorded(
    session, acting_user
):
    """An id nothing answers to leaves no edge — the far end has to exist for
    the pair to mean anything."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    doc = await create_document(session, a.initiative, a.user)
    anchor = Endpoint(DOCUMENT, doc.id)

    await content_references.sync_for_entity(
        session, anchor, body=_doc(_wikilink(999_999)), author_id=a.user.id
    )

    assert await _references(session, anchor) == set()


@pytest.mark.integration
async def test_editing_the_sentence_out_takes_the_edge_with_it(session, acting_user):
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    doc = await create_document(session, a.initiative, a.user)
    other = await create_document(session, a.initiative, a.user)
    anchor = Endpoint(DOCUMENT, doc.id)

    await content_references.sync_for_entity(
        session, anchor, body=_doc(_wikilink(other.id)), author_id=a.user.id
    )
    await content_references.sync_for_entity(
        session, anchor, body=_doc(), author_id=a.user.id
    )

    assert await _references(session, anchor) == set()
    remaining = await session.exec(
        select(EntityRelationship).where(
            EntityRelationship.source_node == anchor.node,
            EntityRelationship.relationship_type == RelationshipType.references.value,
        )
    )
    assert remaining.all() == [], (
        "a link that went away because somebody rewrote a sentence asserts "
        "nothing, so it is deleted rather than kept as a tombstone"
    )


@pytest.mark.integration
async def test_fixing_content_unresolves_a_link_to_itself(session, acting_user):
    """Asked to repair the content too, it leaves the words and drops the
    pointer — the same treatment a link to a deleted document gets."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    doc = await create_document(session, a.initiative, a.user)

    fixed = await content_references.sync_for_entity(
        session,
        Endpoint(DOCUMENT, doc.id),
        body=_doc(_wikilink(doc.id)),
        author_id=a.user.id,
        fix_content=True,
    )

    assert fixed is not None
    assert references_in_body(fixed) == set()


# ---------------------------------------------------------------------------
# A comment's `#` belongs to what the comment is about
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_a_comment_records_its_reference_against_its_parent(session, acting_user):
    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)
    doc = await create_document(session, a.initiative, a.user)
    task = await create_task(session, a.project)

    comment = await create_comment(
        session, a.user, document=doc, content=f"see #task[Do it]({task.id})"
    )
    await content_references.sync_for_comment(session, comment, author_id=a.user.id)

    assert await _references(session, Endpoint(DOCUMENT, doc.id)) == {("task", task.id)}


@pytest.mark.integration
async def test_one_comment_going_does_not_drop_what_another_still_says(
    session, acting_user
):
    """The recompute reads every source at once, so two people naming the same
    thing hold the edge up between them."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)
    project = await create_project(session, a.initiative, a.user)
    task = await create_task(session, project)
    doc = await create_document(session, a.initiative, a.user)

    first = await create_comment(
        session, a.user, document=doc, content=f"#task[Do it]({task.id})"
    )
    await create_comment(
        session, a.user, document=doc, content=f"agreed, #task[Do it]({task.id})"
    )
    await content_references.sync_for_comment(session, first, author_id=a.user.id)
    assert await _references(session, Endpoint(DOCUMENT, doc.id)) == {("task", task.id)}

    await session.delete(first)
    await session.flush()
    await content_references.sync_for_comment(session, first, author_id=a.user.id)

    assert await _references(session, Endpoint(DOCUMENT, doc.id)) == {
        ("task", task.id)
    }, "the other comment still says it"


@pytest.mark.integration
async def test_the_body_and_the_comments_are_read_together(session, acting_user):
    """A save recomputes from both, so writing a document does not wipe what
    its conversation refers to."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)
    doc = await create_document(session, a.initiative, a.user)
    other = await create_document(session, a.initiative, a.user)
    task = await create_task(session, a.project)
    await create_comment(
        session, a.user, document=doc, content=f"#task[Do it]({task.id})"
    )

    await content_references.sync_for_entity(
        session,
        Endpoint(DOCUMENT, doc.id),
        body=_doc(_wikilink(other.id)),
        author_id=a.user.id,
    )

    assert await _references(session, Endpoint(DOCUMENT, doc.id)) == {
        ("document", other.id),
        ("task", task.id),
    }


@pytest.mark.integration
async def test_an_edge_a_body_makes_is_marked_as_nobody_s_assertion(
    session, acting_user
):
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    doc = await create_document(session, a.initiative, a.user)
    other = await create_document(session, a.initiative, a.user)

    await content_references.sync_for_entity(
        session,
        Endpoint(DOCUMENT, doc.id),
        body=_doc(_wikilink(other.id)),
        author_id=a.user.id,
    )

    row = (
        await session.exec(
            select(EntityRelationship).where(
                EntityRelationship.relationship_type
                == RelationshipType.references.value
            )
        )
    ).first()
    assert row is not None
    assert row.provenance == Provenance.content.value
    assert row.created_by == a.user.id, (
        "whoever saved the content is the honest attributor for what it says"
    )
