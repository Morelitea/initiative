"""What a document contributes to search, by what kind of document it is.

``documents.content`` holds a different shape per ``document_type``, so each
gets its own extraction. These assert the text actually reaches the index
against a real Postgres, including the shapes that would otherwise be silent:
a legacy spreadsheet, a document type that stores no prose, and content nested
below the top level.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.db.session import set_rls_context
from app.models.platform.guild import GuildRole
from app.models.tenant.document import DocumentType
from app.models.tenant.search_entry import SearchEntry
from app.testing import Actor, create_document

pytestmark = pytest.mark.integration

ActingUser = Callable[..., Awaitable[Actor]]


async def _body(session: AsyncSession, guild_id: int, document_id: int) -> str:
    await set_rls_context(session, guild_id=guild_id, guild_role="admin")
    rows = await session.exec(
        select(SearchEntry.body)
        .where(
            SearchEntry.entity_type == "document",
            SearchEntry.entity_id == document_id,
        )
        .order_by(SearchEntry.chunk_ix.asc())
    )
    return " ".join(r or "" for r in rows)


async def _finds(session: AsyncSession, guild_id: int, query: str) -> list[str]:
    await set_rls_context(session, guild_id=guild_id, guild_role="admin")
    found = await session.exec(
        text(
            "SELECT title FROM search_entries WHERE entity_type = 'document' "
            "AND tsv @@ websearch_to_tsquery('simple', :q)"
        ).bindparams(q=query)
    )
    return sorted({r[0] for r in found})


async def test_a_native_document_indexes_its_prose(
    session: AsyncSession, acting_user: ActingUser
) -> None:
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    doc = await create_document(
        session,
        a.initiative,
        a.user,
        name="Renewal",
        content={
            "root": {
                "children": [
                    {
                        "type": "paragraph",
                        "children": [{"type": "text", "text": "vendor renewal terms"}],
                    }
                ]
            }
        },
    )
    assert "vendor renewal terms" in await _body(session, a.guild.id, doc.id)
    assert await _finds(session, a.guild.id, "vendor renewal") == ["Renewal"]


async def test_nested_editor_content_is_reached(
    session: AsyncSession, acting_user: ActingUser
) -> None:
    """A mention, a wikilink and an image caption all keep text below the top
    level; the recursive path is what picks them up."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    doc = await create_document(
        session,
        a.initiative,
        a.user,
        name="Nested",
        content={
            "root": {
                "children": [
                    {
                        "type": "image",
                        "caption": {
                            "editorState": {
                                "root": {
                                    "children": [
                                        {
                                            "type": "paragraph",
                                            "children": [
                                                {
                                                    "type": "text",
                                                    "text": "captioned diagram",
                                                }
                                            ],
                                        }
                                    ]
                                }
                            }
                        },
                    },
                    {"type": "wikilink", "text": "Q3 Plan", "documentId": 4},
                ]
            }
        },
    )
    body = await _body(session, a.guild.id, doc.id)
    assert "captioned diagram" in body
    assert "Q3 Plan" in body


async def test_a_whiteboard_indexes_its_element_text(
    session: AsyncSession, acting_user: ActingUser
) -> None:
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    doc = await create_document(
        session,
        a.initiative,
        a.user,
        name="Board",
        document_type=DocumentType.whiteboard,
        content={
            "elements": [
                {"type": "text", "text": "architecture sketch"},
                {"type": "rectangle", "label": {"text": "boxed label"}},
            ],
            "appState": {},
            "files": {},
        },
    )
    body = await _body(session, a.guild.id, doc.id)
    assert "architecture sketch" in body
    assert "boxed label" in body


async def test_a_current_spreadsheet_indexes_cells_and_sheet_names(
    session: AsyncSession, acting_user: ActingUser
) -> None:
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    doc = await create_document(
        session,
        a.initiative,
        a.user,
        name="Workbook",
        document_type=DocumentType.spreadsheet,
        content={
            "schema_version": 3,
            "kind": "workbook",
            "sheets": [
                {"id": "s1", "name": "Budget", "cells": {"0:0": "Revenue", "0:1": 1234}}
            ],
        },
    )
    body = await _body(session, a.guild.id, doc.id)
    assert "Revenue" in body
    assert "1234" in body
    # Sheet names are addressable in formulas, so they are worth finding.
    assert "Budget" in body


async def test_a_legacy_spreadsheet_still_indexes(
    session: AsyncSession, acting_user: ActingUser
) -> None:
    """v1 and v2 payloads are upcast only when next saved, so both shapes are
    live in the database and the extraction has to read either."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    doc = await create_document(
        session,
        a.initiative,
        a.user,
        name="Legacy",
        document_type=DocumentType.spreadsheet,
        content={
            "schema_version": 1,
            "kind": "sheet",
            "dimensions": {"rows": 2, "cols": 2},
            "cells": {"0:0": "legacy total", "0:1": 99},
        },
    )
    body = await _body(session, a.guild.id, doc.id)
    assert "legacy total" in body
    assert "99" in body


async def test_a_smart_link_indexes_its_url(
    session: AsyncSession, acting_user: ActingUser
) -> None:
    """Searching for the service is a real thing people do, and the URL is the
    only place its name appears."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await create_document(
        session,
        a.initiative,
        a.user,
        name="Design system",
        document_type=DocumentType.smart_link,
        content={"url": "https://www.figma.com/file/abc/Design-System"},
    )
    assert await _finds(session, a.guild.id, "figma") == ["Design system"]
    assert await _finds(session, a.guild.id, "www.figma.com") == ["Design system"]


async def test_a_file_document_indexes_its_filename_only(
    session: AsyncSession, acting_user: ActingUser
) -> None:
    """Its bytes live outside the database, so its name is all there is."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    doc = await create_document(
        session,
        a.initiative,
        a.user,
        name="Contract",
        document_type=DocumentType.file,
        content={},
        original_filename="vendor-contract-2026.pdf",
    )
    assert "vendor-contract-2026.pdf" in await _body(session, a.guild.id, doc.id)
    # ...and findable by a word inside it, not only by the whole filename.
    assert await _finds(session, a.guild.id, "vendor contract") == ["Contract"]


async def test_text_is_stored_once(
    session: AsyncSession, acting_user: ActingUser
) -> None:
    """The recursive path can reach the same value by more than one route; the
    body must not carry it twice, or every document costs double."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    doc = await create_document(
        session,
        a.initiative,
        a.user,
        name="Once",
        content={
            "root": {
                "children": [
                    {
                        "type": "paragraph",
                        "children": [{"type": "text", "text": "singleton"}],
                    }
                ]
            }
        },
    )
    assert (await _body(session, a.guild.id, doc.id)).count("singleton") == 1
