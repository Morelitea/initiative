from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional, TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

from app.models.document import DocumentPermissionLevel
from app.schemas.initiative import InitiativeRead, serialize_initiative
from app.schemas.tag import TagSummary

if TYPE_CHECKING:  # pragma: no cover
    from app.models.document import Document, ProjectDocument

LexicalState = Dict[str, Any]
DocumentTypeStr = Literal["native", "file"]


class DocumentProjectLink(BaseModel):
    project_id: int
    project_name: Optional[str] = None
    project_icon: Optional[str] = None
    attached_at: datetime


class DocumentBase(BaseModel):
    title: str
    initiative_id: int
    featured_image_url: Optional[str] = None
    is_template: bool = False


class DocumentCreate(DocumentBase):
    content: Optional[LexicalState] = Field(default_factory=dict)
    role_permissions: Optional[List[DocumentRolePermissionCreate]] = None
    user_permissions: Optional[List[DocumentPermissionCreate]] = None


class DocumentUpdate(BaseModel):
    title: Optional[str] = None
    content: Optional[LexicalState] = None
    featured_image_url: Optional[str] = None
    is_template: Optional[bool] = None


class DocumentDuplicateRequest(BaseModel):
    title: Optional[str] = None


class DocumentCopyRequest(BaseModel):
    target_initiative_id: int
    title: Optional[str] = None


class DocumentRolePermissionCreate(BaseModel):
    initiative_role_id: int
    level: DocumentPermissionLevel = DocumentPermissionLevel.read


class DocumentRolePermissionUpdate(BaseModel):
    level: DocumentPermissionLevel


class DocumentRolePermissionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, json_schema_serialization_defaults_required=True)

    initiative_role_id: int
    role_name: str = ""
    role_display_name: str = ""
    level: DocumentPermissionLevel
    created_at: datetime


class DocumentPermissionCreate(BaseModel):
    user_id: int
    level: DocumentPermissionLevel = DocumentPermissionLevel.write


class DocumentPermissionBulkCreate(BaseModel):
    user_ids: List[int]
    level: DocumentPermissionLevel = DocumentPermissionLevel.read


class DocumentPermissionBulkDelete(BaseModel):
    user_ids: List[int]


class DocumentPermissionUpdate(BaseModel):
    level: DocumentPermissionLevel


class DocumentPermissionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, json_schema_serialization_defaults_required=True)

    user_id: int
    level: DocumentPermissionLevel
    created_at: datetime


class DocumentAutocomplete(BaseModel):
    """Lightweight document info for autocomplete/wikilinks."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    updated_at: datetime


class DocumentBacklink(BaseModel):
    """Document that links to another document."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    updated_at: datetime


class DocumentSummary(DocumentBase):
    model_config = ConfigDict(from_attributes=True, json_schema_serialization_defaults_required=True)

    id: int
    created_by_id: int
    updated_by_id: int
    created_at: datetime
    updated_at: datetime
    initiative: Optional[InitiativeRead] = None
    projects: List[DocumentProjectLink] = Field(default_factory=list)
    comment_count: int = 0
    permissions: List[DocumentPermissionRead] = Field(default_factory=list)
    role_permissions: List[DocumentRolePermissionRead] = Field(default_factory=list)
    tags: List[TagSummary] = Field(default_factory=list)
    # File document fields
    document_type: DocumentTypeStr = "native"
    file_url: Optional[str] = None
    file_content_type: Optional[str] = None
    file_size: Optional[int] = None
    original_filename: Optional[str] = None
    my_permission_level: Optional[str] = None


class DocumentListResponse(BaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    items: List[DocumentSummary]
    total_count: int
    page: int
    page_size: int
    has_next: bool
    sort_by: Optional[str] = None
    sort_dir: Optional[str] = None


class DocumentCountsResponse(BaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    total_count: int
    untagged_count: int
    tag_counts: Dict[int, int]


class DocumentRead(DocumentSummary):
    content: LexicalState = Field(default_factory=dict)


class ProjectDocumentSummary(BaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    document_id: int
    title: str
    updated_at: datetime
    attached_at: datetime


def _serialize_project_links(document: "Document") -> List[DocumentProjectLink]:
    links: List[DocumentProjectLink] = []
    for link in getattr(document, "project_links", []) or []:
        project = getattr(link, "project", None)
        links.append(
            DocumentProjectLink(
                project_id=link.project_id,
                project_name=getattr(project, "name", None),
                project_icon=getattr(project, "icon", None),
                attached_at=link.attached_at,
            )
        )
    return links


def _serialize_permissions(document: "Document") -> List[DocumentPermissionRead]:
    """Serialize all document permissions."""
    permissions = getattr(document, "permissions", None) or []
    return [
        DocumentPermissionRead(
            user_id=permission.user_id,
            level=permission.level,
            created_at=permission.created_at,
        )
        for permission in permissions
    ]


def _serialize_role_permissions(document: "Document") -> List[DocumentRolePermissionRead]:
    """Serialize all document role permissions."""
    role_permissions = getattr(document, "role_permissions", None) or []
    result: List[DocumentRolePermissionRead] = []
    for rp in role_permissions:
        role = getattr(rp, "role", None)
        result.append(
            DocumentRolePermissionRead(
                initiative_role_id=rp.initiative_role_id,
                role_name=getattr(role, "name", "") if role else "",
                role_display_name=getattr(role, "display_name", "") if role else "",
                level=rp.level,
                created_at=rp.created_at,
            )
        )
    return result


def _serialize_document_tags(document: "Document") -> List[TagSummary]:
    """Serialize document tags to TagSummary list."""
    tag_links = getattr(document, "tag_links", None) or []
    tags: List[TagSummary] = []
    for link in tag_links:
        tag = getattr(link, "tag", None)
        if tag:
            tags.append(TagSummary(id=tag.id, name=tag.name, color=tag.color))
    return tags


def serialize_document_summary(
    document: "Document",
    *,
    my_permission_level: Optional[str] = None,
) -> DocumentSummary:
    initiative = serialize_initiative(document.initiative) if document.initiative else None
    return DocumentSummary(
        id=document.id,
        initiative_id=document.initiative_id,
        title=document.title,
        featured_image_url=document.featured_image_url,
        is_template=document.is_template,
        created_by_id=document.created_by_id,
        updated_by_id=document.updated_by_id,
        created_at=document.created_at,
        updated_at=document.updated_at,
        initiative=initiative,
        projects=_serialize_project_links(document),
        comment_count=getattr(document, "comment_count", 0),
        permissions=_serialize_permissions(document),
        role_permissions=_serialize_role_permissions(document),
        tags=_serialize_document_tags(document),
        document_type=document.document_type.value if document.document_type else "native",
        file_url=document.file_url,
        file_content_type=document.file_content_type,
        file_size=document.file_size,
        original_filename=document.original_filename,
        my_permission_level=my_permission_level,
    )


def serialize_document(
    document: "Document",
    *,
    my_permission_level: Optional[str] = None,
) -> DocumentRead:
    summary = serialize_document_summary(document, my_permission_level=my_permission_level)
    return DocumentRead(
        **summary.model_dump(),
        content=document.content or {},
    )


def serialize_project_document_link(link: "ProjectDocument") -> ProjectDocumentSummary | None:
    document = getattr(link, "document", None)
    if not document or document.id is None:
        return None
    return ProjectDocumentSummary(
        document_id=document.id,
        title=document.title,
        updated_at=document.updated_at,
        attached_at=link.attached_at,
    )
