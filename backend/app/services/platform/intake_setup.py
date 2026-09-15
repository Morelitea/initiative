"""Binding a stream to a project, and setting one up from a blueprint.

The platform holds one pointer — ``app_settings.operations_guild_id`` — and
everything else is ordinary per-guild config inside the guild it names. This
module is what the owner's settings page calls to read and change both.

Every write here is the platform owner's (``config.manage``): binding a stream
is deployment configuration of the same class as OIDC, SMTP and branding.
Reaching the guild's own schema is the system engine routed into it as a guild
admin, the same way every other platform surface that reads guild rows does.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from fastapi import HTTPException, status as http_status
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.intake import IntakeStream
from app.core.messages import IntakeMessages
from app.db.session import set_rls_context
from app.models.platform.app_setting import AppSetting
from app.models.platform.guild import Guild, GuildStatus
from app.models.platform.user import User
from app.models.tenant.initiative import Initiative
from app.models.tenant.intake import IntakeBinding, IntakeCase
from app.models.tenant.project import Project
from app.models.tenant.task import Task, TaskStatus
from app.services.platform.intake import operations_guild_id


@dataclass(frozen=True)
class BindingView:
    """One stream's binding, with the names the settings page shows."""

    stream: IntakeStream
    binding_id: Optional[int]
    project_id: Optional[int]
    project_name: Optional[str]
    #: Whether the bound project has been archived or trashed since. Archived
    #: content takes no writes, so a stream pointed at one receives nothing
    #: until it is brought back or pointed somewhere else.
    project_archived: bool
    initiative_id: Optional[int]
    initiative_name: Optional[str]
    default_status_id: Optional[int]
    default_status_name: Optional[str]
    enabled: bool
    #: The most recent case this stream opened. The monitoring that matters on
    #: this page: is the thing on.
    last_case_at: Optional[str]


async def _route(session: AsyncSession, guild_id: int) -> None:
    """Route the system session into a guild's schema as its admin.

    ``expunge_all`` first: ids are unique only within a schema, so nothing
    cached from ``public`` (or from another guild) may be handed back here.
    """
    session.expunge_all()
    await set_rls_context(session, guild_id=guild_id, guild_role="admin")


async def _unroute(session: AsyncSession) -> None:
    """Back to the neutral public baseline, to read or write shared config."""
    session.expunge_all()
    await set_rls_context(session)


async def set_operations_guild(
    session: AsyncSession, guild_id: Optional[int]
) -> Optional[int]:
    """Point this deployment's operations work at ``guild_id``, or at nothing.

    ``None`` unsets it, which stops every stream at once without touching the
    bindings inside the guild — so pointing back restores exactly what was
    there. An ordinary guild is required: a suspended one could not be worked
    in, so it is refused rather than silently accepted.
    """
    await _unroute(session)
    if guild_id is not None:
        guild = (
            await session.exec(select(Guild).where(Guild.id == guild_id))
        ).one_or_none()
        if guild is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=IntakeMessages.GUILD_NOT_FOUND,
            )
        if guild.status != GuildStatus.active.value:
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail=IntakeMessages.GUILD_NOT_ACTIVE,
            )

    row = (await session.exec(select(AppSetting).where(AppSetting.id == 1))).first()
    if row is None:
        row = AppSetting(id=1)
    row.operations_guild_id = guild_id
    session.add(row)
    await session.commit()
    return guild_id


async def _resolve_project(
    session: AsyncSession, project_id: int
) -> tuple[Project, Initiative]:
    """The project a binding names, and the initiative that will read its cases.

    Routed session; both rows must be in this guild's schema, which the schema
    boundary already guarantees for anything this query can see.
    """
    project = (
        await session.exec(
            select(Project)
            .where(Project.id == project_id)
            .execution_options(populate_existing=True)
        )
    ).one_or_none()
    if project is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail=IntakeMessages.PROJECT_NOT_FOUND,
        )
    if project.archived_at is not None or project.deleted_at is not None:
        # Archived and trashed content takes no writes, so a case could not be
        # filed here. Refused at the moment of binding rather than discovered
        # the first time something needs to land.
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail=IntakeMessages.PROJECT_NOT_LIVE,
        )
    initiative = (
        await session.exec(
            select(Initiative)
            .where(Initiative.id == project.initiative_id)
            .execution_options(populate_existing=True)
        )
    ).one_or_none()
    if initiative is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail=IntakeMessages.INITIATIVE_NOT_FOUND,
        )
    return project, initiative


async def _write_binding(
    session: AsyncSession,
    *,
    stream: IntakeStream,
    project: Project,
    project_id: int,
    default_status_id: Optional[int],
    enabled: bool,
) -> IntakeBinding:
    """Create or update the binding row. Routed session; flushes, no commit.

    A named landing status must belong to the named project; anything else is
    refused here rather than quietly ignored, because the page that sent it
    showed the owner a list of that project's statuses.
    """
    if default_status_id is not None:
        named = (
            await session.exec(
                select(TaskStatus.id)
                .where(TaskStatus.id == default_status_id)
                .where(TaskStatus.project_id == project.id)
            )
        ).one_or_none()
        if named is None:
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail=IntakeMessages.STATUS_NOT_IN_PROJECT,
            )

    binding = (
        await session.exec(
            select(IntakeBinding)
            .where(IntakeBinding.stream == stream.value)
            .execution_options(populate_existing=True)
        )
    ).one_or_none()
    # ``project_id`` rather than ``project.id``: the row was fetched by that id,
    # so they are the same value and only one of them is known to be an int.
    if binding is None:
        binding = IntakeBinding(stream=stream, project_id=project_id)
    binding.project_id = project_id
    binding.default_status_id = default_status_id
    binding.enabled = enabled
    session.add(binding)
    await session.flush()
    return binding


async def bind(
    session: AsyncSession,
    *,
    stream: IntakeStream,
    project_id: int,
    default_status_id: Optional[int] = None,
    enabled: bool = True,
) -> BindingView:
    """Route ``stream`` into ``project_id``, replacing any existing binding.

    Cases are keyed by project, so repointing a stream starts fresh in the new
    project and leaves the old one's history where the work is.
    """
    guild_id = await _require_operations_guild(session)
    await _route(session, guild_id)

    project, initiative = await _resolve_project(session, project_id)
    binding = await _write_binding(
        session,
        stream=stream,
        project=project,
        project_id=project_id,
        default_status_id=default_status_id,
        enabled=enabled,
    )
    await session.commit()
    await session.refresh(binding)
    return await _view(session, stream, binding, project, initiative)


async def unbind(session: AsyncSession, stream: IntakeStream) -> None:
    """Stop routing ``stream`` anywhere. The project and its cases stay."""
    guild_id = await _require_operations_guild(session)
    await _route(session, guild_id)
    binding = (
        await session.exec(
            select(IntakeBinding)
            .where(IntakeBinding.stream == stream.value)
            .execution_options(populate_existing=True)
        )
    ).one_or_none()
    if binding is not None:
        await session.delete(binding)
        await session.commit()


async def _require_operations_guild(session: AsyncSession) -> int:
    await _unroute(session)
    guild_id = await operations_guild_id(session)
    if guild_id is None:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail=IntakeMessages.NO_OPERATIONS_GUILD,
        )
    return guild_id


async def _view(
    session: AsyncSession,
    stream: IntakeStream,
    binding: Optional[IntakeBinding],
    project: Optional[Project],
    initiative: Optional[Initiative],
) -> BindingView:
    if binding is None:
        return BindingView(
            stream=stream,
            binding_id=None,
            project_id=None,
            project_name=None,
            project_archived=False,
            initiative_id=None,
            initiative_name=None,
            default_status_id=None,
            default_status_name=None,
            enabled=False,
            last_case_at=None,
        )
    status_name = None
    if binding.default_status_id is not None:
        status_name = (
            await session.exec(
                select(TaskStatus.name).where(
                    TaskStatus.id == binding.default_status_id
                )
            )
        ).one_or_none()
    # Cases only — the seed task a blueprint imports and anything the team adds
    # by hand are ordinary tasks in the project, not cases this stream opened.
    # Joined through the task, which is where the project a case is in lives.
    last_case_at = (
        await session.exec(
            select(IntakeCase.opened_at)
            .join(Task, Task.id == IntakeCase.task_id)
            .where(Task.project_id == binding.project_id)
            .where(IntakeCase.stream == binding.stream)
            .order_by(IntakeCase.opened_at.desc())
            .limit(1)
        )
    ).one_or_none()
    return BindingView(
        stream=stream,
        binding_id=binding.id,
        project_id=binding.project_id,
        project_name=project.name if project else None,
        project_archived=bool(
            project is not None
            and (project.archived_at is not None or project.deleted_at is not None)
        ),
        initiative_id=initiative.id if initiative else None,
        initiative_name=initiative.name if initiative else None,
        default_status_id=binding.default_status_id,
        default_status_name=status_name,
        enabled=binding.enabled,
        last_case_at=last_case_at.isoformat() if last_case_at else None,
    )


async def list_bindings(
    session: AsyncSession,
) -> tuple[Optional[int], list[BindingView]]:
    """Every stream and where it currently lands.

    Returns one view per stream, bound or not, so the settings page renders the
    full set rather than only what somebody has already configured.
    """
    await _unroute(session)
    guild_id = await operations_guild_id(session)
    if guild_id is None:
        return None, [await _view(session, s, None, None, None) for s in IntakeStream]

    await _route(session, guild_id)
    bindings = {
        IntakeStream(row.stream): row
        for row in await session.exec(
            select(IntakeBinding).execution_options(populate_existing=True)
        )
    }
    views: list[BindingView] = []
    for stream in IntakeStream:
        binding = bindings.get(stream)
        project = initiative = None
        if binding is not None:
            # No live-only filter: a binding to a project that has since been
            # archived is exactly what the page has to be able to show.
            project = (
                await session.exec(
                    select(Project)
                    .where(Project.id == binding.project_id)
                    .execution_options(populate_existing=True)
                )
            ).one_or_none()
            if project is not None:
                initiative = (
                    await session.exec(
                        select(Initiative)
                        .where(Initiative.id == project.initiative_id)
                        .execution_options(populate_existing=True)
                    )
                ).one_or_none()
        views.append(await _view(session, stream, binding, project, initiative))
    return guild_id, views


async def provision_from_blueprint(
    session: AsyncSession,
    *,
    stream: IntakeStream,
    initiative_id: int,
    importer: User,
) -> BindingView:
    """Import the stream's blueprint into ``initiative_id`` and bind to it.

    The import and the binding are one transaction, so a deployment either
    gains a set-up stream or is left exactly as it was. ``import_project``
    flushes without committing, which is what lets the two compose.

    An ordinary project import otherwise: what it produces is a project the
    team can rename, restructure and add to, and the binding only names it.
    """
    from app.blueprints.intake import blueprint_for
    from app.services.tenant.project_import import import_project

    guild_id = await _require_operations_guild(session)
    await _route(session, guild_id)

    initiative = (
        await session.exec(
            select(Initiative)
            .where(Initiative.id == initiative_id)
            .execution_options(populate_existing=True)
        )
    ).one_or_none()
    if initiative is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail=IntakeMessages.INITIATIVE_NOT_FOUND,
        )

    result = await import_project(
        session,
        envelope=blueprint_for(stream),
        target_initiative=initiative,
        importer=importer,
    )
    project, _ = await _resolve_project(session, result.project_id)
    binding = await _write_binding(
        session,
        stream=stream,
        project=project,
        project_id=result.project_id,
        default_status_id=None,
        enabled=True,
    )
    await session.commit()
    await session.refresh(binding)
    return await _view(session, stream, binding, project, initiative)


async def list_options(session: AsyncSession) -> list[dict]:
    """The operations guild's initiatives, their projects, and each project's
    statuses — what the settings page's pickers offer.

    Names and ids only, for the one guild the deployment has named. Empty when
    it has named none, which is what the page shows before anything is set up.
    """
    await _unroute(session)
    guild_id = await operations_guild_id(session)
    if guild_id is None:
        return []

    await _route(session, guild_id)
    initiatives = (
        await session.exec(
            select(Initiative)
            .where(Initiative.deleted_at.is_(None))
            .order_by(Initiative.name)
            .execution_options(populate_existing=True)
        )
    ).all()
    projects = (
        await session.exec(
            select(Project)
            .where(Project.deleted_at.is_(None))
            .where(Project.archived_at.is_(None))
            .order_by(Project.name)
            .execution_options(populate_existing=True)
        )
    ).all()
    statuses = (
        await session.exec(
            select(TaskStatus).order_by(TaskStatus.project_id, TaskStatus.position)
        )
    ).all()

    by_project: dict[int, list[dict]] = {}
    for status in statuses:
        by_project.setdefault(status.project_id, []).append(
            {"id": status.id, "name": status.name}
        )
    by_initiative: dict[int, list[dict]] = {}
    for project in projects:
        by_initiative.setdefault(project.initiative_id, []).append(
            {
                "id": project.id,
                "name": project.name,
                "statuses": by_project.get(project.id, []),
            }
        )
    return [
        {
            "id": initiative.id,
            "name": initiative.name,
            "projects": by_initiative.get(initiative.id, []),
        }
        for initiative in initiatives
    ]
