"""Duplicating a tool: one set of steps for every tool.

A copy is a create whose values come from another row. Every tool's copy takes
the same steps in the same order here: who may copy, where the copy may go,
what it is called, which columns come along, who it is shared with, and the
tags, properties and files it carries. What differs from tool to tool is what
lives inside it, and that is all ``TOOL_COPIERS`` holds.

``tool_lifecycle.py`` mounts ``POST /{tool}/{id}/duplicate`` for every tool
here, and a project made from a template is a copy as well
(``create_project``).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Optional

from fastapi import HTTPException, status
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api import resource_access
from app.core.messages import DocumentMessages
from app.core.tools import Tool
from app.db.guild_standing import ActorContext
from app.models.platform.user import User
from app.models.tenant._mixins import (
    ArchiveMixin,
    CreatedByMixin,
    ListingProvenanceMixin,
    SoftDeleteMixin,
)
from app.models.tenant.counter import Counter
from app.models.tenant.project import Project
from app.models.tenant.task import Task
from app.schemas.base import RESERVED_SIGIL_CODE, RESERVED_SIGILS
from app.schemas.tenant.resource_grant import ResourceGrantSchema
from app.services import notifications as notifications_service
from app.services.tenant import attachments as attachments_service
from app.services.tenant import counters as counters_service
from app.services.tenant import documents as documents_service
from app.services.tenant import filter_presets as filter_presets_service
from app.services.tenant import project_grants
from app.services.tenant import properties as properties_service
from app.services.tenant import tags as tags_service
from app.services.tenant import task_creation
from app.services.tenant import task_statuses as task_statuses_service
from app.services.tenant.names import ensure_name_free

#: async (session, source, copy, actor) -> the rows made inside ``copy``
Contents = Callable[[AsyncSession, Any, Any, ActorContext], Awaitable[Sequence[Any]]]


@dataclass(frozen=True)
class ToolCopier:
    """What a copy of one tool does beyond the shared steps."""

    #: The tables inside the tool that ``contents`` fills. Every other table
    #: filed under it (``lifecycle_tree.CASCADE_CHILDREN``) stays with the
    #: source; ``tool_copy_test`` holds the two to each other.
    copies: frozenset[type] = frozenset()
    contents: Optional[Contents] = None
    #: Columns a copy starts afresh rather than carries.
    reset: Mapping[str, Any] = field(default_factory=dict)
    #: The refusal when the target initiative already has one of this name;
    #: ``None`` where names may repeat.
    name_taken: Optional[str] = None
    #: Whether a name may carry the reserved sigils, as a document's may: it
    #: starts life as a filename.
    name_takes_sigils: bool = False
    #: async (session, copy_id, user): tell people about the copy, once it is
    #: committed.
    announce: Optional[Callable[[AsyncSession, int, User], Awaitable[None]]] = None


#: What a row says about its own lifecycle and origin rather than its content.
_NOT_CARRIED = frozenset(
    {
        *SoftDeleteMixin.model_fields,
        *ArchiveMixin.model_fields,
        *CreatedByMixin.model_fields,
        *ListingProvenanceMixin.model_fields,
        "created_at",
        "updated_at",
    }
)


def _carried(model: Any, copier: ToolCopier) -> list[str]:
    """The columns a copy takes from its source: everything the tool says about
    itself, but not its identity, its lifecycle, or the rows it points at,
    which are the copy's own."""
    return [
        column.name
        for column in model.__table__.columns
        if not column.primary_key
        and not column.foreign_keys
        and column.name not in _NOT_CARRIED
        and column.name not in copier.reset
    ]


async def load_source(
    session: AsyncSession,
    tool: Tool,
    source_id: int,
    user: Optional[User],
    actor: ActorContext,
) -> Any:
    """The row to copy, once the caller may copy it. Read is enough for a
    template, which is made to be copied; anything else asks for write, so a
    copy is never a quiet fork of somebody else's work."""
    source = await resource_access.load_authorized(
        session, tool, source_id, user, actor
    )
    if not getattr(source, "is_template", False):
        resource_access.authorize(tool, source, user, access="write", context=actor)
    return source


async def duplicate(
    session: AsyncSession,
    tool: Tool,
    source: Any,
    *,
    initiative_id: Optional[int],
    name: Optional[str],
    user: Optional[User],
    actor: ActorContext,
    payload: Any,
    values: Mapping[str, Any] | None = None,
    grants: Optional[list[ResourceGrantSchema]] = None,
) -> Any:
    """Copy ``source`` into ``initiative_id`` (its own when ``None``), held to
    what a create there is held to. Beside its source the copy is called
    "<name> (Copy)" unless ``name`` is given; elsewhere it keeps the name.

    ``values`` overrides carried columns (a project made from a template takes
    its own dates), and ``grants`` replaces the source's sharing. Raises
    ``StorageQuotaExceededError`` when its files do not fit. The caller
    commits.
    """
    copier = TOOL_COPIERS[tool]
    model = type(source)
    initiative_id = initiative_id or source.initiative_id
    beside = initiative_id == source.initiative_id
    await resource_access.prepare_create(session, tool, initiative_id, user, actor)
    name = (name or "").strip() or (f"{source.name} (Copy)" if beside else source.name)
    if not copier.name_takes_sigils and RESERVED_SIGILS.intersection(name):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=RESERVED_SIGIL_CODE,
        )
    if copier.name_taken is not None:
        await ensure_name_free(
            session,
            model.name,
            name,
            model.initiative_id == initiative_id,
            detail=copier.name_taken,
        )

    columns = _carried(model, copier)
    # Deferred columns (a document's body) are read too.
    await session.refresh(source, columns)
    copy = model(
        **{
            **{column: deepcopy(getattr(source, column)) for column in columns},
            **copier.reset,
            **(values or {}),
            "name": name,
            "initiative_id": initiative_id,
        }
    )
    session.add(copy)
    await session.flush()
    await resource_access.grant_initial_sharing(
        session,
        actor,
        tool,
        user=user,
        resource_id=copy.id,
        initiative_id=initiative_id,
        payload=payload,
        grants=(
            resource_access.duplicate_sharing(source, initiative_id=initiative_id)
            if grants is None
            else grants
        ),
    )
    # Everything inside is reached through the copy, so its sharing lands first.
    await session.flush()

    rows = (
        list(await copier.contents(session, source, copy, actor))
        if copier.contents
        else []
    )
    await tags_service.copy_entity_tags(
        session, tags_service.TOOL_TAG_LINKS[tool], {source.id: copy.id}
    )
    # Definitions belong to an initiative, so values only go where they apply.
    if beside and model in properties_service.PROPERTY_LINKS_BY_MODEL:
        await properties_service.copy_values(session, model, {source.id: copy.id})
    # Files kept for another initiative are copied for the copy's.
    await attachments_service.claim_uploads(session, copy, *rows)
    return copy


async def _project_contents(
    session: AsyncSession, source: Project, copy: Project, actor: ActorContext
) -> list[Task]:
    status_mapping = await task_statuses_service.clone_statuses(
        session, source_project_id=source.id, target_project_id=copy.id
    )
    statuses = await task_statuses_service.ensure_default_statuses(session, copy.id)
    # Presets' status filters name per-project ids, so they go through the
    # mapping too.
    await filter_presets_service.clone_presets(
        session,
        source_project_id=source.id,
        target_project_id=copy.id,
        status_mapping=status_mapping,
    )
    await filter_presets_service.ensure_default_presets(session, copy.id)
    return await task_creation.copy_project_tasks(
        session,
        source,
        copy,
        status_mapping=status_mapping,
        fallback_status_ids={status.category: status.id for status in statuses},
    )


async def _announce_project(session: AsyncSession, project_id: int, user: User) -> None:
    project = await project_grants.get_project_hydrated(session, project_id)
    await notifications_service.notify_project_added(session, project, user)


TOOL_COPIERS: dict[Tool, ToolCopier] = {
    Tool.project: ToolCopier(
        copies=frozenset({Task}),
        contents=_project_contents,
        reset={"is_template": False, "pinned_at": None},
        announce=_announce_project,
    ),
    Tool.document: ToolCopier(
        contents=documents_service.copy_contents,
        reset={"is_template": False, "yjs_state": None, "yjs_updated_at": None},
        name_taken=DocumentMessages.NAME_ALREADY_EXISTS,
        name_takes_sigils=True,
    ),
    Tool.counter_group: ToolCopier(
        copies=frozenset({Counter}),
        contents=lambda session, source, copy, actor: counters_service.copy_counters(
            session, source, copy
        ),
    ),
}
