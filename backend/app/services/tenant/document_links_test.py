"""Which references count as a link between documents, and which get recorded.

Backlinks — "what points at this page" — are built from what a document's
content refers to. The first half here decides what counts as a reference; the
second decides which of them the graph keeps.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlmodel import select

from app.models.platform.guild import GuildRole
from app.models.tenant.document import DocumentLink
from app.services.tenant.documents import (
    extract_linked_document_ids,
    sync_document_links,
)
from app.testing import create_document


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


async def _targets(session, document_id: int) -> set[int]:
    """What the graph says this document links to."""
    rows = await session.exec(
        select(DocumentLink.target_document_id).where(
            DocumentLink.source_document_id == document_id
        )
    )
    return set(rows)


@pytest.mark.integration
async def test_a_document_does_not_link_to_itself(session, acting_user):
    """The page a self-link opens is the page it was written on, and the row
    would list the document among the ones that link to it."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    doc = await create_document(session, a.initiative, a.user)
    other = await create_document(session, a.initiative, a.user)

    await sync_document_links(
        session,
        document_id=doc.id,
        content=_doc(_wikilink(doc.id), _wikilink(other.id)),
        guild_id=a.guild.id,
    )

    assert await _targets(session, doc.id) == {other.id}


@pytest.mark.integration
async def test_a_hash_reference_to_itself_is_not_a_link_either(session, acting_user):
    """Both triggers write into one graph, so both are refused the same way."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    doc = await create_document(session, a.initiative, a.user)

    await sync_document_links(
        session,
        document_id=doc.id,
        content=_doc(_reference("document", doc.id)),
        guild_id=a.guild.id,
    )

    assert await _targets(session, doc.id) == set()


@pytest.mark.integration
async def test_a_self_link_already_recorded_is_removed(session, acting_user):
    """Content written before this was refused still holds one, so the next
    save is what clears it."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    doc = await create_document(session, a.initiative, a.user)
    session.add(
        DocumentLink(
            source_document_id=doc.id,
            target_document_id=doc.id,
            guild_id=a.guild.id,
        )
    )
    await session.flush()

    await sync_document_links(
        session,
        document_id=doc.id,
        content=_doc(_wikilink(doc.id)),
        guild_id=a.guild.id,
    )

    assert await _targets(session, doc.id) == set()


@pytest.mark.integration
async def test_fixing_content_unresolves_a_link_to_itself(session, acting_user):
    """Asked to repair the content too, it leaves the words and drops the
    pointer — the same treatment a link to a deleted document gets."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    doc = await create_document(session, a.initiative, a.user)

    fixed = await sync_document_links(
        session,
        document_id=doc.id,
        content=_doc(_wikilink(doc.id)),
        guild_id=a.guild.id,
        fix_content=True,
    )

    assert fixed is not None
    assert extract_linked_document_ids(fixed) == set()
