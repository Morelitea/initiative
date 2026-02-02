from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional, TYPE_CHECKING

from pydantic import BaseModel, Field

from app.models.document import DocumentPermissionLevel
from app.schemas.initiative import InitiativeRead, serialize_initiative

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
    user_id: int
    level: DocumentPermissionLevel
    created_at: datetime

    class Config:
        from_attributes = True


class DocumentSummary(DocumentBase):
    id: int
    created_by_id: int
    updated_by_id: int
    created_at: datetime
    updated_at: datetime
    initiative: Optional[InitiativeRead] = None
    projects: List[DocumentProjectLink] = Field(default_factory=list)
    comment_count: int = 0
    permissions: List[DocumentPermissionRead] = Field(default_factory=list)
    # File document fields
    document_type: DocumentTypeStr = "native"
    file_url: Optional[str] = None
    file_content_type: Optional[str] = None
    file_size: Optional[int] = None
    original_filename: Optional[str] = None

    class Config:
        from_attributes = True


class DocumentRead(DocumentSummary):
    content: LexicalState = Field(default_factory=dict)


class ProjectDocumentSummary(BaseModel):
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


def serialize_document_summary(document: "Document") -> DocumentSummary:
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
        document_type=document.document_type.value if document.document_type else "native",
        file_url=document.file_url,
        file_content_type=document.file_content_type,
        file_size=document.file_size,
        original_filename=document.original_filename,
    )


def serialize_document(document: "Document") -> DocumentRead:
    summary = serialize_document_summary(document)
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
