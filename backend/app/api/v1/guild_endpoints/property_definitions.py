"""CRUD endpoints for initiative-scoped custom property definitions."""

from datetime import datetime, timezone
from typing import Annotated, List, Optional, Sequence

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func
from sqlalchemy.orm import selectinload
from sqlmodel import select

from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import (
    GuildContext,
    RLSSessionDep,
    get_current_active_user,
    get_guild_membership,
)
from app.core.messages import PropertyMessages
from app.db.session import reapply_rls_context
from app.models.calendar_event import CalendarEvent
from app.models.document import Document
from app.models.guild import GuildRole
from app.models.initiative import Initiative, InitiativeMember
from app.models.property import (
    CalendarEventPropertyValue,
    DocumentPropertyValue,
    PropertyDefinition,
    PropertyType,
    TaskPropertyValue,
)
from app.models.task import Task
from app.core.capabilities import Capability, user_has_capability
from app.models.user import User
from app.schemas.property import (
    PropertyDefinitionCreate,
    PropertyDefinitionRead,
    PropertyDefinitionUpdate,
    PropertyDefinitionUpdateResponse,
)
from app.schemas.tag import (
    TaggedDocumentSummary,
    TaggedEventSummary,
    TaggedTaskSummary,
)
from app.services import permissions as permissions_service
from app.services import properties as properties_service

router = APIRouter()

GuildContextDep = Annotated[GuildContext, Depends(get_guild_membership)]


class PropertyEntitiesResult(BaseModel):
    """Response for GET /property-definitions/{id}/entities."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    tasks: List[TaggedTaskSummary] = Field(default_factory=list)
    documents: List[TaggedDocumentSummary] = Field(default_factory=list)
    events: List[TaggedEventSummary] = Field(default_factory=list)


async def _get_definition_or_404(
    session: AsyncSession,
    definition_id: int,
) -> PropertyDefinition:
    """Fetch a definition by id, relying on RLS for scope enforcement.

    MUST be called with a routed session (``RLSSessionDep``). Under
    schema-per-guild, ``property_definitions`` lives only in the active
    guild's schema, and definition ids are unique per-guild — looking the
    id up on an unrouted session would hit the frozen ``public`` backup
    and resolve the wrong (or no) row.
    """
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
    session: AsyncSession,
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
    session: AsyncSession,
    guild_context: GuildContext,
    initiative_id: int,
    user: User,
) -> None:
    """Explicit membership check before insert, run in the active guild's schema.

    Under schema-per-guild, ``property_definitions`` and
    ``initiative_members`` live only in the request's active guild schema,
    and ``initiative_id`` is meaningful only within that schema. The check
    therefore runs on the request's routed session (``RLSSessionDep``) so it
    resolves against live data for the active guild — not the frozen
    ``public`` backup an unrouted admin session would read.

    Mirrors the RLS policy bypasses: superadmins and guild admins of the
    active guild pass without an explicit ``InitiativeMember`` row (same
    semantics as the restrictive RLS policy's ``OR IS_ADMIN OR IS_SUPER``
    clause). The guild-admin check reads ``guild_context.role`` — already
    resolved from the shared ``guild_memberships`` table — so no extra
    query is needed.

    A definition can only be created in the caller's active guild, so we
    also confirm the initiative exists in this schema; an id from another
    guild (or a deleted one) is treated as "not a member" and surfaces a
    clean ``NOT_INITIATIVE_MEMBER`` 403 rather than the misleading
    ``DEFINITION_NOT_FOUND`` code (or a downstream FK error on insert).
    """
    # Superadmin bypass — sees every guild's schema, skip the existence check.
    if user_has_capability(user, Capability.DATA_BYPASS):
        return

    # The initiative id must resolve in the active guild's schema. Ids are
    # unique per-guild, so a foreign or deleted id has no row here. This runs
    # before the guild-admin bypass on purpose — admins need the FK guard too.
    # Constraint: it assumes the routed session can see every initiative row in
    # the schema; if per-schema initiative-scoped RLS policies are ever
    # reintroduced, this lookup must use a policy-exempt path or guild admins
    # outside the initiative will false-403 here.
    init_stmt = select(Initiative.id).where(Initiative.id == initiative_id)
    if (await session.exec(init_stmt)).one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=PropertyMessages.NOT_INITIATIVE_MEMBER,
        )

    # Guild-admin bypass: admins of the active guild may manage any
    # initiative in that guild. GuildContext already resolved the role.
    if guild_context.role == GuildRole.admin:
        return

    # Direct initiative membership, resolved in the active guild's schema.
    stmt = select(InitiativeMember).where(
        InitiativeMember.initiative_id == initiative_id,
        InitiativeMember.user_id == user.id,
    )
    result = await session.exec(stmt)
    if result.one_or_none() is not None:
        return

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=PropertyMessages.NOT_INITIATIVE_MEMBER,
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
) -> Sequence[PropertyDefinition]:
    """List property definitions.

    With ``initiative_id``, returns definitions for that initiative only
    (filtered explicitly and subject to RLS). Without it, RLS returns the
    union across every initiative the caller can see — used by global
    views (My Tasks, Created Tasks, global Documents list).
    """
    stmt = select(PropertyDefinition)
    if initiative_id is not None:
        stmt = stmt.where(PropertyDefinition.initiative_id == initiative_id)
    stmt = stmt.order_by(
        PropertyDefinition.position.asc(), PropertyDefinition.name.asc()
    )
    result = await session.exec(stmt)
    return result.all()


@router.post(
    "/", response_model=PropertyDefinitionRead, status_code=status.HTTP_201_CREATED
)
async def create_property_definition(
    payload: PropertyDefinitionCreate,
    session: RLSSessionDep,
    guild_context: GuildContextDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> PropertyDefinition:
    """Create a new property definition on an initiative.

    Requires the caller to be a member of the target initiative (or a
    guild admin / superadmin). The membership check runs on the routed
    request session, so it resolves against the active guild's schema —
    the only place the target initiative and its definitions live under
    schema-per-guild.
    """
    await _ensure_initiative_member(
        session, guild_context, payload.initiative_id, current_user
    )
    await _check_duplicate_name(session, payload.initiative_id, payload.name)

    defn = PropertyDefinition(
        initiative_id=payload.initiative_id,
        name=payload.name.strip(),
        type=payload.type,
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

    project_access_subq = permissions_service.visible_project_ids_subquery(
        current_user.id
    )
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

    # Events are scoped directly by initiative (no project indirection); RLS
    # on calendar_event_property_values already constrains visibility to
    # initiatives the caller belongs to, matching the task/doc treatment.
    events_stmt = (
        select(CalendarEvent)
        .join(
            CalendarEventPropertyValue,
            CalendarEventPropertyValue.event_id == CalendarEvent.id,
        )
        .where(CalendarEventPropertyValue.property_id == defn.id)
        .options(selectinload(CalendarEvent.initiative))
    )
    events_result = await session.exec(events_stmt)
    events = events_result.all()
    event_summaries = [
        TaggedEventSummary(
            id=event.id,
            title=event.title,
            initiative_id=event.initiative_id,
            initiative_name=event.initiative.name if event.initiative else None,
        )
        for event in events
    ]

    return PropertyEntitiesResult(
        tasks=task_summaries,
        documents=document_summaries,
        events=event_summaries,
    )
