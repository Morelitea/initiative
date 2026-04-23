"""CRUD endpoints for initiative-scoped custom property definitions."""

from datetime import datetime, timezone
from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func
from sqlalchemy.orm import selectinload
from sqlmodel import select

from app.api.deps import RLSSessionDep, SessionDep, get_current_active_user
from app.core.messages import PropertyMessages
from app.db.session import reapply_rls_context
from app.models.document import Document
from app.models.initiative import InitiativeMember
from app.models.property import (
    DocumentPropertyValue,
    PropertyAppliesTo,
    PropertyDefinition,
    PropertyType,
    TaskPropertyValue,
)
from app.models.task import Task
from app.models.user import User
from app.schemas.property import (
    PropertyDefinitionCreate,
    PropertyDefinitionRead,
    PropertyDefinitionUpdate,
    PropertyDefinitionUpdateResponse,
)
from app.schemas.tag import TaggedDocumentSummary, TaggedTaskSummary
from app.services import permissions as permissions_service
from app.services import properties as properties_service

router = APIRouter()


class PropertyEntitiesResult(BaseModel):
    """Response for GET /property-definitions/{id}/entities."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    tasks: List[TaggedTaskSummary] = Field(default_factory=list)
    documents: List[TaggedDocumentSummary] = Field(default_factory=list)


async def _get_definition_or_404(
    session: SessionDep,
    definition_id: int,
) -> PropertyDefinition:
    """Fetch a definition by id, relying on RLS for scope enforcement."""
    stmt = select(PropertyDefinition).where(PropertyDefinition.id == definition_id)
    result = await session.exec(stmt)
    defn = result.one_or_none()
    if defn is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=PropertyMessages.DEFINITION_NOT_FOUND,
        )
    return defn


async def _check_duplicate_name(
    session: SessionDep,
    initiative_id: int,
    name: str,
    exclude_id: Optional[int] = None,
) -> None:
    stmt = select(PropertyDefinition).where(
        PropertyDefinition.initiative_id == initiative_id,
        func.lower(PropertyDefinition.name) == name.lower().strip(),
    )
    if exclude_id is not None:
        stmt = stmt.where(PropertyDefinition.id != exclude_id)
    result = await session.exec(stmt)
    if result.one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=PropertyMessages.NAME_ALREADY_EXISTS,
        )


async def _ensure_initiative_member(
    session: SessionDep,
    initiative_id: int,
    user_id: int,
) -> None:
    """Explicit membership check before insert.

    RLS would block a non-member's INSERT as well, but the resulting error
    is opaque. Surfacing a clean 403 here makes API errors actionable.
    """
    stmt = select(InitiativeMember).where(
        InitiativeMember.initiative_id == initiative_id,
        InitiativeMember.user_id == user_id,
    )
    result = await session.exec(stmt)
    if result.one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=PropertyMessages.DEFINITION_NOT_FOUND,
        )


def _serialize_options(options: Optional[list]) -> Optional[list[dict]]:
    """Coerce PropertyOption models into plain dicts for JSONB storage."""
    if options is None:
        return None
    serialized: list[dict] = []
    for opt in options:
        if hasattr(opt, "model_dump"):
            serialized.append(opt.model_dump(exclude_none=True))
        elif isinstance(opt, dict):
            serialized.append(opt)
    return serialized


@router.get("/", response_model=List[PropertyDefinitionRead])
async def list_property_definitions(
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    initiative_id: Optional[int] = Query(default=None),
    applies_to: Optional[PropertyAppliesTo] = Query(default=None),
) -> List[PropertyDefinition]:
    """List property definitions.

    With ``initiative_id``, returns definitions for that initiative only
    (filtered explicitly and subject to RLS). Without it, RLS returns the
    union across every initiative the caller can see — used by global
    views (My Tasks, Created Tasks, global Documents list).
    """
    stmt = select(PropertyDefinition)
    if initiative_id is not None:
        stmt = stmt.where(PropertyDefinition.initiative_id == initiative_id)
    if applies_to is not None:
        if applies_to is PropertyAppliesTo.both:
            stmt = stmt.where(PropertyDefinition.applies_to == PropertyAppliesTo.both)
        else:
            stmt = stmt.where(
                PropertyDefinition.applies_to.in_([applies_to, PropertyAppliesTo.both])
            )
    stmt = stmt.order_by(PropertyDefinition.position.asc(), PropertyDefinition.name.asc())
    result = await session.exec(stmt)
    return result.all()


@router.post("/", response_model=PropertyDefinitionRead, status_code=status.HTTP_201_CREATED)
async def create_property_definition(
    payload: PropertyDefinitionCreate,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> PropertyDefinition:
    """Create a new property definition on an initiative.

    Requires the caller to be a member of the target initiative.
    """
    await _ensure_initiative_member(session, payload.initiative_id, current_user.id)
    await _check_duplicate_name(session, payload.initiative_id, payload.name)

    defn = PropertyDefinition(
        initiative_id=payload.initiative_id,
        name=payload.name.strip(),
        type=payload.type,
        applies_to=payload.applies_to,
        position=payload.position,
        color=payload.color,
        options=_serialize_options(payload.options),
    )
    session.add(defn)
    await session.commit()
    await reapply_rls_context(session)
    await session.refresh(defn)
    return defn


@router.get("/{definition_id}", response_model=PropertyDefinitionRead)
async def get_property_definition(
    definition_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> PropertyDefinition:
    """Fetch a single property definition."""
    return await _get_definition_or_404(session, definition_id)


@router.patch("/{definition_id}", response_model=PropertyDefinitionUpdateResponse)
async def update_property_definition(
    definition_id: int,
    payload: PropertyDefinitionUpdate,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> PropertyDefinitionUpdateResponse:
    """Update a property definition.

    Type changes are not allowed via this endpoint; callers should
    delete the definition and re-create. Changing the option list on a
    select / multi_select definition returns ``orphaned_value_count`` so
    the SPA can warn about dangling values.
    """
    defn = await _get_definition_or_404(session, definition_id)

    data = payload.model_dump(exclude_unset=True)

    if "name" in data and data["name"] is not None:
        await _check_duplicate_name(
            session,
            defn.initiative_id,
            data["name"],
            exclude_id=defn.id,
        )
        defn.name = data["name"].strip()

    if "applies_to" in data and data["applies_to"] is not None:
        defn.applies_to = data["applies_to"]

    if "position" in data and data["position"] is not None:
        defn.position = data["position"]

    if "color" in data:
        defn.color = data["color"]

    orphaned_value_count = 0
    if "options" in data:
        if defn.type not in {PropertyType.select, PropertyType.multi_select}:
            # Silently ignore options for non-select types to stay consistent
            # with the create-side behavior.
            defn.options = None
        else:
            options_payload = payload.options or []
            if not options_payload:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=PropertyMessages.OPTIONS_REQUIRED,
                )
            new_slugs = {opt.value for opt in options_payload}
            orphaned_value_count = await properties_service.count_orphaned_values(
                session, defn.id, new_slugs
            )
            defn.options = _serialize_options(options_payload)

    defn.updated_at = datetime.now(timezone.utc)
    session.add(defn)
    await session.commit()
    await reapply_rls_context(session)
    await session.refresh(defn)
    return PropertyDefinitionUpdateResponse(
        definition=PropertyDefinitionRead.model_validate(defn),
        orphaned_value_count=orphaned_value_count,
    )


@router.delete("/{definition_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_property_definition(
    definition_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> None:
    """Delete a property definition. Cascades to remove all attached values."""
    defn = await _get_definition_or_404(session, definition_id)
    await session.delete(defn)
    await session.commit()


@router.get("/{definition_id}/entities", response_model=PropertyEntitiesResult)
async def get_property_entities(
    definition_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> PropertyEntitiesResult:
    """List all documents and tasks with a value for this property.

    Results are constrained by the user's project / document visibility.
    """
    defn = await _get_definition_or_404(session, definition_id)

    project_access_subq = permissions_service.visible_project_ids_subquery(current_user.id)
    doc_access_subq = permissions_service.visible_document_ids_subquery(current_user.id)

    tasks_stmt = (
        select(Task)
        .join(TaskPropertyValue, TaskPropertyValue.task_id == Task.id)
        .where(
            TaskPropertyValue.property_id == defn.id,
            Task.project_id.in_(project_access_subq),
        )
        .options(selectinload(Task.project))
    )
    tasks_result = await session.exec(tasks_stmt)
    tasks = tasks_result.all()
    task_summaries = [
        TaggedTaskSummary(
            id=task.id,
            title=task.title,
            project_id=task.project_id,
            project_name=task.project.name if task.project else None,
        )
        for task in tasks
    ]

    documents_stmt = (
        select(Document)
        .join(DocumentPropertyValue, DocumentPropertyValue.document_id == Document.id)
        .where(
            DocumentPropertyValue.property_id == defn.id,
            Document.id.in_(doc_access_subq),
        )
        .options(selectinload(Document.initiative))
    )
    documents_result = await session.exec(documents_stmt)
    documents = documents_result.all()
    document_summaries = [
        TaggedDocumentSummary(
            id=doc.id,
            title=doc.title,
            initiative_id=doc.initiative_id,
            initiative_name=doc.initiative.name if doc.initiative else None,
        )
        for doc in documents
    ]

    return PropertyEntitiesResult(tasks=task_summaries, documents=document_summaries)
