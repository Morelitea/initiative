"""What can be edited by several people at once, and how each one is reached.

A collaboration room is a Yjs document plus the row it is a body of. Which row
that is differs — a document's body is its own, a wiki page's body is the
page's while the *sharing* belongs to the wiki it sits in — and that difference
is the whole of what varies between them.

So it is declared once here, per kind, and the room, the socket and the
persistence sweep all read it rather than each knowing about documents:

``entity_type``
    The room's ``resource_type`` in the stream register, and the reference kind
    the body's ``[[ ]]`` links are recorded against. One value, because they
    are the same fact.
``tool``
    Whose sharing decides who may open the socket.
``model`` / ``content_column``
    Where the JSON body lives. The Yjs columns are spelled the same on every
    collaborative table, so they are not restated.
``normalize``
    Checks and cleans a content frame before the room holds it. A document's
    shape depends on its type; a page is always prose, so it only has to be an
    object.
``load``
    Fetches the body row and the row whose grants govern it, with everything
    the DAC engine reads eager-loaded. Returns ``None`` when either is missing
    or belongs to another guild — which the socket treats as "not found",
    exactly as the REST path does.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional

from sqlalchemy.orm import selectinload, undefer
from sqlmodel import select

from app.core.search import SearchEntityType
from app.core.tools import Tool

#: Both columns are spelled the same on every collaborative table, so a new one
#: declares neither.
YJS_STATE_COLUMN = "yjs_state"
YJS_UPDATED_COLUMN = "yjs_updated_at"


@dataclass(frozen=True)
class Collaborating:
    """One resolved resource: the row holding the body, and the row that says
    who may read or write it. They are the same row for a document."""

    body: Any
    governing: Any
    initiative_id: Optional[int]


@dataclass(frozen=True)
class CollaborativeResource:
    entity_type: SearchEntityType
    tool: Tool
    model: type
    content_column: str
    load: Callable[..., Awaitable[Optional[Collaborating]]]
    normalize: Callable[[Any, Any], dict]

    @property
    def resource_type(self) -> str:
        """The room key's middle term, and the stream register's."""
        return self.entity_type.value


async def _load_document(
    session: Any, resource_id: int, guild_id: int
) -> Optional[Collaborating]:
    from app.models.tenant.document import Document
    from app.models.tenant.resource_grant import ResourceGrant

    statement = (
        select(Document)
        .where(Document.id == resource_id)
        .options(
            selectinload(Document.initiative),
            undefer(Document.actions),
            selectinload(Document.grants).selectinload(ResourceGrant.role),
        )
    )
    document = (await session.exec(statement)).one_or_none()
    if document is None:
        return None
    return Collaborating(
        body=document, governing=document, initiative_id=document.initiative_id
    )


async def _load_wiki_page(
    session: Any, resource_id: int, guild_id: int
) -> Optional[Collaborating]:
    """A page's body is its own; who may read or write it is the wiki's.

    That is the same rule the REST path applies — a page is the wiki's content
    — so the socket asks the same question of the same row.
    """
    from app.models.tenant.resource_grant import ResourceGrant
    from app.models.tenant.wiki import Wiki, WikiPage

    page = (
        await session.exec(select(WikiPage).where(WikiPage.id == resource_id))
    ).one_or_none()
    if page is None:
        return None

    statement = (
        select(Wiki)
        .where(Wiki.id == page.wiki_id)
        .options(
            selectinload(Wiki.initiative),
            undefer(Wiki.actions),
            selectinload(Wiki.grants).selectinload(ResourceGrant.role),
        )
    )
    wiki = (await session.exec(statement)).one_or_none()
    if wiki is None:
        return None
    return Collaborating(body=page, governing=wiki, initiative_id=wiki.initiative_id)


class ContentFrameError(ValueError):
    """A content frame that is not the shape this kind of body takes."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _normalize_document(body: Any, content: Any) -> dict:
    from app.services.tenant import documents as documents_service

    return documents_service.normalize_document_content(
        content, document_type=body.document_type
    )


def _normalize_wiki_page(_body: Any, content: Any) -> dict:
    """A page is always a Lexical body, so the only question is whether this is
    an editor state at all."""
    if not isinstance(content, dict):
        raise ContentFrameError("WIKI_PAGE_CONTENT_INVALID")
    return content


COLLABORATIVE_RESOURCES: dict[str, CollaborativeResource] = {}


def _register(resource: CollaborativeResource) -> CollaborativeResource:
    COLLABORATIVE_RESOURCES[resource.resource_type] = resource
    return resource


def _document_resource() -> CollaborativeResource:
    from app.models.tenant.document import Document

    return CollaborativeResource(
        entity_type=SearchEntityType.document,
        tool=Tool.document,
        model=Document,
        content_column="content",
        load=_load_document,
        normalize=_normalize_document,
    )


def _wiki_page_resource() -> CollaborativeResource:
    from app.models.tenant.wiki import WikiPage

    return CollaborativeResource(
        entity_type=SearchEntityType.wiki_page,
        tool=Tool.wiki,
        model=WikiPage,
        content_column="content",
        load=_load_wiki_page,
        normalize=_normalize_wiki_page,
    )


def resource_for(resource_type: str) -> CollaborativeResource:
    """The declaration for one kind. Raises for a kind nothing registered,
    which is a wiring mistake rather than a request error."""
    if not COLLABORATIVE_RESOURCES:
        _register(_document_resource())
        _register(_wiki_page_resource())
    return COLLABORATIVE_RESOURCES[resource_type]


def registered_types() -> tuple[str, ...]:
    """Every collaborative kind, for the tests that walk them."""
    resource_for(SearchEntityType.document.value)
    return tuple(sorted(COLLABORATIVE_RESOURCES))
