from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional, Sequence, TYPE_CHECKING

from pydantic import ConfigDict, Field

from app.core.relationships import Related
from app.schemas.base import SanitizedBaseModel
from app.schemas.query import PageMeta

from app.models.tenant.document import DocumentType
from app.models.tenant.resource_grant import ResourceAccessLevel
from app.schemas.tenant.resource_grant import ResourceGrantSchema, initiative_readable
from app.schemas.platform.user import UserPublic
from app.schemas.tenant.initiative import InitiativeSummary
from app.schemas.tenant.ownership import OwnerAppSummary
from app.schemas.tenant.property import PropertySummary
from app.schemas.tenant.tool import ToolSummaryBase, serialize_tool

if TYPE_CHECKING:  # pragma: no cover
    from app.db.guild_standing import ActorContext
    from app.models.tenant.document import (
        Document,
        DocumentFileVersion,
    )

LexicalState = Dict[str, Any]
#: One sheet of a workbook, in the canonical shape
#: ``normalize_spreadsheet_content`` produces.
SpreadsheetSheet = Dict[str, Any]


class DocumentProjectLink(SanitizedBaseModel):
    project_id: int
    project_name: Optional[str] = None
    project_icon: Optional[str] = None
    # The initiative the project lives in — its URL addresses it, so the link
    # resolves without a second fetch. None when the project isn't loaded.
    project_initiative_id: Optional[int] = None
    attached_at: datetime


class DocumentBase(SanitizedBaseModel):
    name: str
    initiative_id: int
    featured_image_url: Optional[str] = None
    is_template: bool = False


class DocumentCreate(DocumentBase):
    content: Optional[LexicalState] = Field(default_factory=dict)
    #: A file document is made by uploading the file (``POST /documents/upload``).
    document_type: Literal[
        DocumentType.native,
        DocumentType.whiteboard,
        DocumentType.smart_link,
        DocumentType.spreadsheet,
    ] = DocumentType.native
    # Initial sharing — the same grant list the PUT /grants endpoint takes.
    grants: List[ResourceGrantSchema] = Field(default_factory=initiative_readable)


class DocumentUpdate(SanitizedBaseModel):
    name: Optional[str] = None
    content: Optional[LexicalState] = None
    featured_image_url: Optional[str] = None
    is_template: Optional[bool] = None


class DocumentDuplicateRequest(SanitizedBaseModel):
    name: Optional[str] = None


class DocumentCopyRequest(SanitizedBaseModel):
    target_initiative_id: int
    name: Optional[str] = None


class DocumentSummary(DocumentBase, ToolSummaryBase):
    # ``validate_by_name`` so ``derived_fields`` can set ``owner`` and
    # ``owner_app`` by name; their aliases keep ``from_attributes`` from reading
    # an ORM relationship.
    model_config = ConfigDict(validate_by_name=True)

    initiative: Optional[InitiativeSummary] = None
    #: The person holding the document's owner grant, or None when it is
    #: unowned or an app owns it.
    owner: Optional[UserPublic] = Field(default=None, validation_alias="owner_source")
    #: The installed app holding the owner grant, or None when a person owns
    #: the document or nobody does. At most one of ``owner`` and this is set.
    owner_app: Optional[OwnerAppSummary] = Field(
        default=None, validation_alias="owner_app_source"
    )
    projects: List[DocumentProjectLink] = Field(default_factory=list)
    comment_count: int = 0
    properties: List[PropertySummary] = Field(default_factory=list)
    # File document fields
    document_type: DocumentType = DocumentType.native
    file_url: Optional[str] = None
    file_content_type: Optional[str] = None
    file_size: Optional[int] = None
    original_filename: Optional[str] = None
    # Smart-link URL surfaced on the summary so cards can render the
    # provider-specific icon without fetching the full content JSONB.
    # Only populated when document_type == "smart_link".
    smart_link_url: Optional[str] = None
    yjs_updated_at: Optional[datetime] = None

    @classmethod
    def derived_fields(
        cls, row: Any, *, context: ActorContext, user_id: Optional[int]
    ) -> dict[str, Any]:
        from app.services.tenant.ownership import owner_app_of

        return {
            "owner": _document_owner(row),
            "owner_app": owner_app_of(row),
            "properties": _serialize_document_properties(row),
            "smart_link_url": smart_link_url(row),
        }


class DocumentListResponse(PageMeta):
    items: List[DocumentSummary]
    sort_by: Optional[str] = None
    sort_dir: Optional[str] = None


class DocumentCountsResponse(SanitizedBaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    total_count: int
    untagged_count: int
    tag_counts: Dict[int, int]


class DocumentRead(DocumentSummary):
    content: LexicalState = Field(default_factory=dict)


class DocumentFileVersionRead(SanitizedBaseModel):
    """A single stored version of a file-type document. The binary is fetched
    via the version download endpoint by id — ``file_url`` is intentionally
    not exposed."""

    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

    id: int
    version_number: int
    file_content_type: Optional[str] = None
    file_size: Optional[int] = None
    original_filename: Optional[str] = None
    created_by: int
    created_at: datetime
    is_current: bool = False


class ProjectDocumentSummary(SanitizedBaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    document_id: int
    name: str
    updated_at: datetime
    attached_at: datetime


def _serialize_project_links(
    projects: Sequence[Related],
) -> List[DocumentProjectLink]:
    """The projects a document is attached to.

    Handed in, because a document list serialises many of these at once and the
    edges live in their own table: the caller loads the whole page's worth in
    one go (``relationships.related_for_many``) rather than each document
    fetching its own.
    """
    return [
        DocumentProjectLink(
            project_id=related.id,
            project_name=getattr(related.entity, "name", None),
            project_icon=getattr(related.entity, "icon", None),
            project_initiative_id=getattr(related.entity, "initiative_id", None),
            attached_at=related.linked_at,
        )
        for related in projects
    ]


def _serialize_document_properties(document: "Document") -> List[PropertySummary]:
    """Serialize loaded document property values.

    Requires ``property_values.property_definition`` (and ``.value_user``
    for user_reference) to be eager-loaded — otherwise they are skipped.
    """
    # Local import avoids the schema layer pulling in the service at
    # module import time.
    from app.services.tenant.properties import summaries_from_rows

    rows = getattr(document, "property_values", None) or []
    return summaries_from_rows(rows)


def _document_owner(document: "Document") -> Optional[UserPublic]:
    """The user holding the document's owner grant, or None when it is unowned.

    Read off the grants the loader brings with their users, as a project reads
    its own; ownership is recorded there and nowhere else.
    """
    for grant in getattr(document, "grants", None) or []:
        if (
            grant.user_id is not None
            and grant.level == ResourceAccessLevel.owner
            and grant.user
        ):
            return UserPublic.model_validate(grant.user)
    return None


def smart_link_url(document: Any) -> Optional[str]:
    """The address a link document points at, so a card can draw its provider's
    mark without the content."""
    if document.document_type != DocumentType.smart_link:
        return None
    content = document.content if isinstance(document.content, dict) else {}
    url = content.get("url")
    return url if isinstance(url, str) and url else None


def serialize_document_summary(
    document: "Document",
    *,
    context: ActorContext,
    user_id: Optional[int] = None,
    projects: Sequence[Related] = (),
) -> DocumentSummary:
    return serialize_tool(
        DocumentSummary,
        document,
        context=context,
        user_id=user_id,
        projects=_serialize_project_links(projects),
    )


def serialize_document(
    document: "Document",
    *,
    context: ActorContext,
    user_id: Optional[int] = None,
    include_content: bool = True,
) -> DocumentRead:
    """The full document. ``include_content=False`` leaves the body out — every
    other field is unchanged, including the smart-link URL that is derived from
    it."""
    return serialize_tool(
        DocumentRead,
        document,
        context=context,
        user_id=user_id,
        **({} if include_content else {"content": {}}),
    )


def serialize_document_file_version(
    version: "DocumentFileVersion",
    *,
    is_current: bool,
) -> DocumentFileVersionRead:
    return DocumentFileVersionRead(
        id=version.id,
        version_number=version.version_number,
        file_content_type=version.file_content_type,
        file_size=version.file_size,
        original_filename=version.original_filename,
        created_by=version.created_by,
        created_at=version.created_at,
        is_current=is_current,
    )


def serialize_document_file_versions(
    versions: List["DocumentFileVersion"],
) -> List[DocumentFileVersionRead]:
    """Serialize versions, marking the highest ``version_number`` as current."""
    if not versions:
        return []
    current_number = max(v.version_number for v in versions)
    return [
        serialize_document_file_version(
            v, is_current=v.version_number == current_number
        )
        for v in versions
    ]


def serialize_project_document_link(
    related: Related,
) -> ProjectDocumentSummary | None:
    """One attached document, from the project's side.

    ``None`` when the far end is gone or the reader cannot open it: the edge
    cleared the gate, the document did not, and an attachment nobody may read
    is simply absent from the answer.
    """
    document = related.entity
    if document is None or getattr(document, "id", None) is None:
        return None
    return ProjectDocumentSummary(
        document_id=document.id,
        name=document.name,
        updated_at=document.updated_at,
        attached_at=related.linked_at,
    )


class SpreadsheetImportRead(SanitizedBaseModel):
    """The sheets a file held, ready to be added to a workbook.

    Nothing is written by the read that produces this: the editor adds these
    to its live document itself, in one transaction, so an import is one thing
    to undo.
    """

    sheets: List[SpreadsheetSheet] = Field(default_factory=list)
