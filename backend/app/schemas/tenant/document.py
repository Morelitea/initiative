from __future__ import annotations

from datetime import datetime
from typing import (
    Annotated,
    Any,
    Dict,
    List,
    Literal,
    Optional,
    Sequence,
    TYPE_CHECKING,
)

from pydantic import ConfigDict, Field

from app.core.identity_boundary import UPLOAD_PATH
from app.core.relationships import Related
from app.schemas.base import LexicalState, SanitizedBaseModel
from app.schemas.tenant.property import PropertiesOnCreate
from app.schemas.query import PageMeta

from app.models.tenant.document import DocumentType
from app.models.tenant.resource_grant import ResourceAccessLevel
from app.schemas.tenant.resource_grant import ResourceGrantSchema, initiative_readable
from app.schemas.platform.user import UserPublic
from app.schemas.tenant.initiative import InitiativeSummary
from app.schemas.tenant.ownership import OwnerAppSummary
from app.schemas.tenant.tool import ToolSummaryBase, serialize_tool

if TYPE_CHECKING:  # pragma: no cover
    from app.db.guild_standing import ActorContext
    from app.models.tenant.document import Document

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


class DocumentCreate(DocumentBase, PropertiesOnCreate):
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
    #: The ``content_version`` of the read this ``content`` was made from.
    #: Given and still current, the write merges in, into a live editing
    #: session too; given and out of date, it is refused with
    #: ``*_CONTENT_CHANGED``. Left out, a live session refuses the write.
    content_version: Optional[str] = None
    featured_image_url: Optional[str] = None
    is_template: Optional[bool] = None


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
    #: ``DocumentBase``'s, marked here: a request takes it as it is.
    featured_image_url: Annotated[Optional[str], UPLOAD_PATH] = None
    projects: List[DocumentProjectLink] = Field(default_factory=list)
    comment_count: int = 0
    # File document fields, read from its current version
    document_type: DocumentType = DocumentType.native
    file_url: Annotated[Optional[str], UPLOAD_PATH] = None
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

        version = row.current_version
        return {
            "owner": _document_owner(row),
            "owner_app": owner_app_of(row),
            "smart_link_url": smart_link_url(row),
            **{name: getattr(version, name, None) for name in _FILE_FIELDS},
        }


#: What a document reports of its current version.
_FILE_FIELDS = ("file_url", "file_content_type", "file_size", "original_filename")


class DocumentListResponse(PageMeta):
    items: List[DocumentSummary]
    sort_by: Optional[str] = None
    sort_dir: Optional[str] = None


class DocumentRead(DocumentSummary):
    content: LexicalState = Field(default_factory=dict)
    #: The version of ``content`` this read returns. Send it back with a
    #: ``PATCH`` of ``content`` so the write merges into the body only if
    #: nobody has changed it since. ``null`` when the body was left out.
    content_version: Optional[str] = None


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
    mark without the content: ``Document.smart_link_url``, read in the row's
    own SELECT."""
    return document.smart_link_url or None


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


class SpreadsheetImportRead(SanitizedBaseModel):
    """The sheets a file held, ready to be added to a workbook.

    Nothing is written by the read that produces this: the editor adds these
    to its live document itself, in one transaction, so an import is one thing
    to undo.
    """

    sheets: List[SpreadsheetSheet] = Field(default_factory=list)
