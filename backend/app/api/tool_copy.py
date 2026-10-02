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

from collections.abc import Awaitable, Callable, Collection, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Optional

from fastapi import HTTPException, status
from sqlmodel import select
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
from app.models.tenant.counter import Counter, CounterGroup
from app.models.tenant.gallery import Gallery, GalleryImage, GalleryImageVersion
from app.models.tenant.post import Post
from app.models.tenant.post_poll import PostPoll, PostPollOption
from app.models.tenant.project import Project
from app.models.tenant.queue import Queue, QueueItem
from app.models.tenant.task import Task
from app.schemas.base import RESERVED_SIGIL_CODE, RESERVED_SIGILS
from app.schemas.tenant.resource_grant import ResourceGrantSchema
from app.services import notifications as notifications_service
from app.services.tenant import attachments as attachments_service
from app.services.tenant import documents as documents_service
from app.services.tenant import filter_presets as filter_presets_service
from app.services.tenant import project_grants
from app.services.tenant import properties as properties_service
from app.services.tenant import relationships
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


def _carried(model: Any, skip: Collection[str] = ()) -> list[str]:
    """The columns a copy takes from its source: everything the row says about
    itself, but not its identity, its lifecycle, the rows it points at, which
    are the copy's own, or ``skip``."""
    return [
        column.name
        for column in model.__table__.columns
        if not column.primary_key
        and not column.foreign_keys
        and column.name not in _NOT_CARRIED
        and column.name not in skip
    ]


def _clone(source: Any, reset: Mapping[str, Any] | None = None, **values: Any) -> Any:
    """A new row of ``source``'s model carrying its columns (:func:`_carried`),
    with ``reset`` and ``values`` set on top. ``source`` is loaded."""
    reset = reset or {}
    model = type(source)
    carried = {c: deepcopy(getattr(source, c)) for c in _carried(model, reset)}
    return model(**{**carried, **reset, **values})


async def _copy_extras(
    session: AsyncSession, pairs: Sequence[tuple[Any, Any]], *, beside: bool
) -> None:
    """The tags and links of rows copied inside a tool, one model at a time,
    and their property values when the copy stays in its initiative."""
    if not pairs:
        return
    model = type(pairs[0][0])
    copies = {source.id: copy.id for source, copy in pairs}
    spec = next((s for s in tags_service.TAG_LINKS.values() if s.entity is model), None)
    if spec is not None:
        await tags_service.copy_entity_tags(session, spec, copies)
        await relationships.copy_links(session, spec.kind, copies)
    if beside and model in properties_service.PROPERTY_LINKS_BY_MODEL:
        await properties_service.copy_values(session, model, copies)


async def _copy_children(
    session: AsyncSession,
    sources: Sequence[Any],
    *,
    beside: bool,
    values: Callable[[Any], Mapping[str, Any]],
    reset: Mapping[str, Any] | None = None,
) -> list[tuple[Any, Any]]:
    """Clone ``sources``, rows inside a tool, with ``values(source)`` set on
    each, then copy their tags and properties; returns the pairs."""
    pairs = [(source, _clone(source, reset, **values(source))) for source in sources]
    session.add_all(clone for _, clone in pairs)
    await session.flush()
    await _copy_extras(session, pairs, beside=beside)
    return pairs


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

    columns = _carried(model, copier.reset)
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
    spec = tags_service.TOOL_TAG_LINKS[tool]
    await tags_service.copy_entity_tags(session, spec, {source.id: copy.id})
    await relationships.copy_links(session, spec.kind, {source.id: copy.id})
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


def _beside(source: Any, copy: Any) -> bool:
    return source.initiative_id == copy.initiative_id


async def _counter_group_contents(
    session: AsyncSession, source: CounterGroup, copy: CounterGroup, actor: ActorContext
) -> list[Counter]:
    counters = (
        await session.exec(select(Counter).where(Counter.counter_group_id == source.id))
    ).all()
    pairs = await _copy_children(
        session,
        counters,
        beside=_beside(source, copy),
        values=lambda _: {"counter_group_id": copy.id},
    )
    return [clone for _, clone in pairs]


async def _queue_contents(
    session: AsyncSession, source: Queue, copy: Queue, actor: ActorContext
) -> list[QueueItem]:
    items = (
        await session.exec(select(QueueItem).where(QueueItem.queue_id == source.id))
    ).all()
    pairs = await _copy_children(
        session,
        items,
        beside=_beside(source, copy),
        values=lambda item: {"queue_id": copy.id, "user_id": item.user_id},
        reset={"held_at_round": None},
    )
    return [clone for _, clone in pairs]


async def _gallery_contents(
    session: AsyncSession, source: Gallery, copy: Gallery, actor: ActorContext
) -> list[GalleryImage]:
    images = (
        await session.exec(
            select(GalleryImage).where(GalleryImage.gallery_id == source.id)
        )
    ).all()
    # Each picture starts again at version 1, authored by whoever copied it; an
    # app is never an author, so its copy keeps the picture's uploader.
    pairs = await _copy_children(
        session,
        images,
        beside=_beside(source, copy),
        values=lambda image: {
            "gallery_id": copy.id,
            "created_by": actor.user_id or image.created_by,
        },
    )
    session.add_all(
        GalleryImageVersion(
            gallery_image_id=clone.id,
            version_number=1,
            created_by=clone.created_by,
            **{c: getattr(clone, c) for c in _IMAGE_FILE_COLUMNS},
        )
        for _, clone in pairs
    )
    copy.cover_image_id = {s.id: c.id for s, c in pairs}.get(source.cover_image_id)
    return [clone for _, clone in pairs]


#: What a picture's version records about its file.
_IMAGE_FILE_COLUMNS = (
    "file_url",
    "thumbnail_url",
    "file_content_type",
    "file_size",
    "original_filename",
    "width",
    "height",
)


async def _post_contents(
    session: AsyncSession, source: Post, copy: Post, actor: ActorContext
) -> list[Any]:
    """The post's polls, with their options and none of the votes."""
    for poll in (
        await session.exec(select(PostPoll).where(PostPoll.post_id == source.id))
    ).all():
        # A draft's poll has not closed: it opens again when the copy is posted.
        ((_, clone),) = await _copy_children(
            session,
            [poll],
            beside=False,
            values=lambda _: {"post_id": copy.id},
            reset={"closes_at": None},
        )
        options = (
            await session.exec(
                select(PostPollOption).where(PostPollOption.poll_id == poll.id)
            )
        ).all()
        await _copy_children(
            session, options, beside=False, values=lambda _: {"poll_id": clone.id}
        )
    return []


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
        copies=frozenset({Counter}), contents=_counter_group_contents
    ),
    Tool.queue: ToolCopier(
        copies=frozenset({QueueItem}),
        contents=_queue_contents,
        # A copy starts its rotation from the top.
        reset={"is_active": False, "current_round": 1},
    ),
    Tool.gallery: ToolCopier(
        copies=frozenset({GalleryImage}), contents=_gallery_contents
    ),
    Tool.dashboard: ToolCopier(),
    # A copy of a notice is a draft: not published, scheduled or pinned.
    Tool.post: ToolCopier(
        contents=_post_contents,
        reset={
            "published_at": None,
            "scheduled_for": None,
            "pinned_at": None,
            "pinned_by": None,
            "pin_expires_at": None,
        },
    ),
}
