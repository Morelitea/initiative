"""
Test data factories for creating database models.

This module provides factory functions for creating test instances of database
models with sensible defaults. Each factory function can accept overrides for
any field.

Schema-per-guild: tenant models live in per-guild Postgres schemas, never in
``public``. Every tenant factory therefore routes its session to the target
guild's schema (``route_session_to_guild``) before reading or writing, derived
from the parent object it receives — so factory calls are deterministic
regardless of flush composition. Raw ``session.add()`` of tenant models in
tests is covered by the fail-closed flush router in ``schema_harness``.
"""

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.encryption import (
    encrypt_field,
    hash_email,
    SALT_APP_SERVICE_SECRET,
    SALT_EMAIL,
)
from app.core.tools import TOGGLEABLE_TOOLS, Tool
from app.core.security import (
    create_access_token,
    get_password_hash,
    mint_access_token,
)
from app.models.platform.app_service_registration import AppServiceRegistration
from app.models.tenant.calendar import Calendar
from app.models.platform.marketplace import (
    MarketplaceListing,
    UID_ALPHABET,
    UID_LENGTH,
)
from app.models.tenant.dashboard import Dashboard
from app.models.tenant.guild_app import GuildApp
from app.models.tenant.guild_app_user_delegation import GuildAppUserDelegation
from app.models.tenant.calendar_event import CalendarEvent
from app.models.tenant.comment import Comment
from app.models.tenant.counter import Counter, CounterGroup
from app.models.tenant.document import Document, DocumentType
from app.models.platform.guild import Guild, GuildMembership, GuildRole
from app.models.platform.guild_administration import GuildAdministration
from app.services.marketplace import catalog as marketplace_catalog
from app.services.marketplace.registration_lookup import invalidate_registrations
from app.services.tenant.dashboard_definition import (
    normalize_dashboard_definition,
)
from app.models.tenant.initiative import Initiative, InitiativeMember
from app.models.tenant.project import Project
from app.models.tenant.resource_grant import ResourceGrant, ResourceAccessLevel
from app.models.tenant.property import (
    CalendarEventPropertyValue,
    DocumentPropertyValue,
    PropertyDefinition,
    PropertyType,
    TaskPropertyValue,
)
from app.models.tenant.queue import Queue, QueueItem
from app.models.tenant.tag import Tag
from app.models.tenant.task import (
    Subtask,
    Task,
    TaskAssignee,
    TaskPriority,
    TaskStatus,
    TaskStatusCategory,
)
from app.models.tenant.upload import Upload
from app.models.platform.auth_provider import AuthProvider, AuthProviderKind
from app.models.platform.federated_identity import FederatedIdentity
from app.models.platform.user import User, UserRole, UserStatus
from app.services.auth.platform_provider import PLATFORM_OIDC_SLUG
from app.services.tenant.initiatives import create_builtin_roles
from app.services.tenant.task_completion import sync_completed_at
from app.testing.schema_harness import route_session_to_guild


async def create_user(
    session: AsyncSession,
    commit: bool = True,
    **overrides: Any,
) -> User:
    """
    Create a test user with sensible defaults.

    Args:
        session: Database session
        commit: Whether to commit the transaction (default True)
        **overrides: Override any default field values

    Returns:
        Created User instance

    Example:
        user = await create_user(
            session,
            email="test@example.com",
            role=UserRole.operator
        )
    """
    email_raw = (
        overrides.pop(
            "email", f"user-{datetime.now(timezone.utc).timestamp()}@example.com"
        )
        .lower()
        .strip()
    )
    defaults = {
        "email_hash": hash_email(email_raw),
        "email_encrypted": encrypt_field(email_raw, SALT_EMAIL),
        "full_name": "Test User",
        "hashed_password": get_password_hash("testpassword123"),
        "role": UserRole.member,
        "status": UserStatus.active,
        "email_verified": True,
        "week_starts_on": 0,
        "timezone": "UTC",
        "overdue_notification_time": "21:00",
        "email_initiative_addition": True,
        "email_task_assignment": True,
        "email_project_added": True,
        "email_overdue_tasks": True,
        "email_mentions": True,
        "push_initiative_addition": True,
        "push_task_assignment": True,
        "push_project_added": True,
        "push_overdue_tasks": True,
        "push_mentions": True,
        "email_events": True,
        "push_events": True,
        "email_event_reminders": True,
        "push_event_reminders": True,
        "event_reminder_minutes_before": 15,
    }

    user_data = {**defaults, **overrides}
    user = User(**user_data)
    session.add(user)

    if commit:
        await session.commit()
        await session.refresh(user)

    return user


async def create_guild(
    session: AsyncSession,
    creator: User | None = None,
    commit: bool = True,
    **overrides: Any,
) -> Guild:
    """
    Create a test guild with sensible defaults.

    Args:
        session: Database session
        creator: User who creates the guild (will be created if not provided)
        commit: Whether to commit the transaction (default True)
        **overrides: Override any default field values

    Returns:
        Created Guild instance

    Example:
        guild = await create_guild(session, name="Test Guild")
    """
    if creator is None:
        creator = await create_user(session, commit=commit)

    # The operator-set fields live on ``guild_administration``, so overrides for
    # them are routed to that row rather than to the guild. Tests keep passing
    # them as if they were guild fields.
    administration_defaults: dict[str, Any] = {
        # Test guilds are sign-in-enabled by default so the guild-auth surface is
        # exercisable without extra setup; production guilds default off (the
        # operator opts each guild in from the Guilds dashboard). Pass
        # guild_auth_enabled=False to exercise the disabled paths.
        "guild_auth_enabled": True,
    }
    administration_data = {
        **administration_defaults,
        **{
            field: overrides.pop(field)
            for field in (
                "max_storage_bytes",
                "max_users",
                "tier_name",
                "guild_auth_enabled",
            )
            if field in overrides
        },
    }

    defaults = {
        "name": f"Test Guild {datetime.now(timezone.utc).timestamp()}",
        "description": "A test guild for integration testing",
        "created_by": creator.id,
    }

    guild_data = {**defaults, **overrides}
    guild = Guild(**guild_data)
    session.add(guild)
    await session.flush()
    # Every guild has exactly one, created with it — same as the service path.
    session.add(GuildAdministration(guild_id=guild.id, **administration_data))

    if commit:
        await session.commit()
        await session.refresh(guild)
        # Schema-native: commit the guild row, then provision its schema so the
        # routing harness can send this guild's guild-scoped writes into it.
        from app.db.schema_provisioning import provision_guild

        await provision_guild(guild.id)

    return guild


async def guild_administration(
    session: AsyncSession, guild: Guild, commit: bool = True, **fields: Any
) -> GuildAdministration:
    """Read (and optionally set) a guild's operator-set row.

    The caps, plan label, and sign-in entitlement live on ``guild_administration``
    rather than on the guild, so a test that used to poke ``guild.max_users``
    goes through here instead. Called with no ``fields`` it is a plain read.
    """
    row = (
        await session.exec(
            select(GuildAdministration).where(GuildAdministration.guild_id == guild.id)
        )
    ).one()
    for name, value in fields.items():
        setattr(row, name, value)
    if fields:
        session.add(row)
        if commit:
            await session.commit()
            await session.refresh(row)
        else:
            await session.flush()
    return row


async def create_guild_membership(
    session: AsyncSession,
    user: User | None = None,
    guild: Guild | None = None,
    role: GuildRole = GuildRole.member,
    commit: bool = True,
    **overrides: Any,
) -> GuildMembership:
    """
    Create a guild membership (linking a user to a guild).

    Args:
        session: Database session
        user: User to add to guild (will be created if not provided)
        guild: Guild to add user to (will be created if not provided)
        role: Guild role for the user (default: member)
        commit: Whether to commit the transaction (default True)
        **overrides: Override any default field values

    Returns:
        Created GuildMembership instance

    Example:
        membership = await create_guild_membership(
            session,
            user=test_user,
            guild=test_guild,
            role=GuildRole.admin
        )
    """
    if user is None:
        user = await create_user(session, commit=commit)

    if guild is None:
        guild = await create_guild(session, commit=commit)

    defaults = {
        "user_id": user.id,
        "guild_id": guild.id,
        "role": role,
        "position": 0,
    }

    membership_data = {**defaults, **overrides}
    membership = GuildMembership(**membership_data)
    session.add(membership)

    if commit:
        await session.commit()
        await session.refresh(membership)

    return membership


def get_auth_token(user: User) -> str:
    """
    Generate a valid JWT access token for a user.

    Args:
        user: User to generate token for

    Returns:
        JWT access token string

    Example:
        token = get_auth_token(test_user)
        headers = {"Authorization": f"Bearer {token}"}
        response = await client.get("/api/v1/users/me", headers=headers)
    """
    return create_access_token(subject=str(user.id), token_version=user.token_version)


def get_new_access_token(
    user: User,
    *,
    session_id: uuid.UUID | None = None,
    amr: list[str] | None = None,
    satisfied_providers: list[int] | None = None,
) -> str:
    """Mint a *new-model* access token (aud ``initiative:access``) for a user.

    Mirrors :func:`get_auth_token` but for the dual-verify path: exercises that
    the session-JWT verifiers accept the new scheme. ``session_id``/``amr``/
    ``sat`` default to a throwaway session with ``pwd`` since the verify path
    only checks ``sub``/``ver``.
    """
    token, _ = mint_access_token(
        user_id=user.id,
        token_version=user.token_version,
        session_id=session_id or uuid.uuid4(),
        amr=amr if amr is not None else ["pwd"],
        satisfied_providers=satisfied_providers
        if satisfied_providers is not None
        else [],
    )
    return token


def get_auth_headers(user: User) -> dict[str, str]:
    """
    Get authorization headers for API requests.

    Args:
        user: User to authenticate as

    Returns:
        Dictionary with Authorization header

    Example:
        headers = get_auth_headers(test_user)
        response = await client.get("/api/v1/users/me", headers=headers)
    """
    token = get_auth_token(user)
    return {"Authorization": f"Bearer {token}"}


async def create_initiative(
    session: AsyncSession,
    guild: Guild,
    creator: User,
    commit: bool = True,
    **overrides: Any,
) -> Initiative:
    """
    Create a test initiative with sensible defaults.

    Args:
        session: Database session
        guild: Guild the initiative belongs to
        creator: User who creates the initiative (will become project manager)
        commit: Whether to commit the transaction (default True)
        **overrides: Override any default field values

    Returns:
        Created Initiative instance

    Example:
        initiative = await create_initiative(session, guild, user, name="Test Initiative")
    """
    await route_session_to_guild(session, guild.id)

    defaults = {
        "name": f"Test Initiative {datetime.now(timezone.utc).timestamp()}",
        "description": "A test initiative",
        "guild_id": guild.id,
        "queues_enabled": True,
        "counter_groups_enabled": True,
    }

    initiative_data = {**defaults, **overrides}
    initiative = Initiative(**initiative_data)
    session.add(initiative)

    if commit:
        await session.flush()

        # Create built-in roles (PM + Member)
        pm_role, _member_role = await create_builtin_roles(
            session, initiative_id=initiative.id
        )

        # Add creator as project manager with proper role_id
        membership = InitiativeMember(
            initiative_id=initiative.id,
            user_id=creator.id,
            role_id=pm_role.id,
            guild_id=initiative.guild_id,
        )
        session.add(membership)
        await session.commit()
        await session.refresh(initiative)

    return initiative


async def create_project(
    session: AsyncSession,
    initiative: Initiative,
    owner: User,
    commit: bool = True,
    **overrides: Any,
) -> Project:
    """
    Create a test project with sensible defaults.

    Args:
        session: Database session
        initiative: Initiative the project belongs to
        owner: User who owns the project
        commit: Whether to commit the transaction (default True)
        **overrides: Override any default field values

    Returns:
        Created Project instance

    Example:
        project = await create_project(session, initiative, user, name="Test Project")
    """
    await route_session_to_guild(session, initiative.guild_id)

    defaults = {
        "name": f"Test Project {datetime.now(timezone.utc).timestamp()}",
        "description": "A test project",
        "initiative_id": initiative.id,
        "owner_id": owner.id,
        "guild_id": initiative.guild_id,
    }

    project_data = {**defaults, **overrides}
    project = Project(**project_data)
    session.add(project)

    if commit:
        await session.commit()
        await session.refresh(project)

        # Owner grant so the project is visible via DAC.
        session.add(
            ResourceGrant(
                resource_type="project",
                resource_id=project.id,
                user_id=owner.id,
                level=ResourceAccessLevel.owner,
                guild_id=project.guild_id,
                initiative_id=project.initiative_id,
            )
        )
        await session.commit()

    return project


async def create_task(
    session: AsyncSession,
    project: Project,
    *,
    title: str | None = None,
    status_category: TaskStatusCategory = TaskStatusCategory.todo,
    assignees: list[User] | None = None,
    commit: bool = True,
    **overrides: Any,
) -> Task:
    """Create a test task (guild-scoped), with a status of the requested
    category and optional assignees.

    Reuses an existing project status of the same category if one exists,
    otherwise creates one. Pass ``status_category=TaskStatusCategory.done`` and
    ``assignees=[user]`` to build a completed, assigned task (e.g. for stats).
    """
    from sqlmodel import select as _select

    await route_session_to_guild(session, project.guild_id)

    status = (
        await session.exec(
            _select(TaskStatus)
            .where(
                TaskStatus.project_id == project.id,
                TaskStatus.category == status_category,
            )
            .limit(1)
        )
    ).first()
    if status is None:
        status = TaskStatus(
            guild_id=project.guild_id,
            project_id=project.id,
            name=status_category.value.replace("_", " ").title(),
            category=status_category,
            position=0,
            is_default=status_category == TaskStatusCategory.todo,
        )
        session.add(status)
        await session.flush()

    defaults: dict[str, Any] = {
        "title": title or f"Test Task {datetime.now(timezone.utc).timestamp()}",
        "project_id": project.id,
        "guild_id": project.guild_id,
        "task_status_id": status.id,
        "priority": TaskPriority.medium,
    }
    task = Task(**{**defaults, **overrides})
    # Match what the endpoints do, so a factory-built done task is a valid one:
    # done-ness and completed_at always agree. A ``completed_at`` override on a
    # done task survives (letting a test date a completion), and one on a task
    # that isn't done is dropped rather than persisted as an impossible row.
    sync_completed_at(task, status.category, now=datetime.now(timezone.utc))
    session.add(task)
    if commit:
        await session.commit()
        await session.refresh(task)

    for user in assignees or []:
        session.add(
            TaskAssignee(task_id=task.id, user_id=user.id, guild_id=project.guild_id)
        )
    if commit and assignees:
        await session.commit()

    return task


async def create_queue(
    session: AsyncSession,
    initiative: Initiative,
    creator: User,
    commit: bool = True,
    **overrides: Any,
) -> Queue:
    """
    Create a test queue with sensible defaults.

    Args:
        session: Database session
        initiative: Initiative the queue belongs to
        creator: User who creates the queue
        commit: Whether to commit the transaction (default True)
        **overrides: Override any default field values

    Returns:
        Created Queue instance
    """
    await route_session_to_guild(session, initiative.guild_id)

    defaults = {
        "name": f"Test Queue {datetime.now(timezone.utc).timestamp()}",
        "description": "A test queue",
        "initiative_id": initiative.id,
        "guild_id": initiative.guild_id,
        "created_by": creator.id,
    }

    queue_data = {**defaults, **overrides}
    queue = Queue(**queue_data)
    session.add(queue)

    if commit:
        await session.commit()
        await session.refresh(queue)

        # Owner grant for creator.
        session.add(
            ResourceGrant(
                resource_type="queue",
                resource_id=queue.id,
                user_id=creator.id,
                guild_id=queue.guild_id,
                initiative_id=queue.initiative_id,
                level=ResourceAccessLevel.owner,
            )
        )
        await session.commit()

    return queue


async def create_queue_item(
    session: AsyncSession,
    queue: Queue,
    commit: bool = True,
    **overrides: Any,
) -> QueueItem:
    """
    Create a test queue item with sensible defaults.

    Args:
        session: Database session
        queue: Queue the item belongs to
        commit: Whether to commit the transaction (default True)
        **overrides: Override any default field values

    Returns:
        Created QueueItem instance
    """
    await route_session_to_guild(session, queue.guild_id)

    defaults = {
        "queue_id": queue.id,
        "guild_id": queue.guild_id,
        "label": f"Item {datetime.now(timezone.utc).timestamp()}",
        "position": 0,
        "is_visible": True,
    }

    item_data = {**defaults, **overrides}
    item = QueueItem(**item_data)
    session.add(item)

    if commit:
        await session.commit()
        await session.refresh(item)

    return item


async def create_initiative_member(
    session: AsyncSession,
    initiative: Initiative,
    user: User,
    role_name: str = "member",
    commit: bool = True,
) -> InitiativeMember:
    """
    Create an initiative member with proper role_id.

    Args:
        session: Database session
        initiative: Initiative to add user to
        user: User to add
        role_name: Role name ("project_manager" or "member")
        commit: Whether to commit the transaction

    Returns:
        Created InitiativeMember instance
    """
    from app.models.tenant.initiative import InitiativeRoleModel
    from sqlmodel import select

    await route_session_to_guild(session, initiative.guild_id)

    # Find the matching role for this initiative
    stmt = select(InitiativeRoleModel).where(
        InitiativeRoleModel.initiative_id == initiative.id,
        InitiativeRoleModel.name == role_name,
    )
    result = await session.exec(stmt)
    role = result.one_or_none()
    if role is None:
        raise ValueError(
            f"Role '{role_name}' not found for initiative {initiative.id}. "
            "Ensure builtin roles exist (use create_initiative factory)."
        )

    membership = InitiativeMember(
        initiative_id=initiative.id,
        user_id=user.id,
        role_id=role.id,
        guild_id=initiative.guild_id,
    )
    session.add(membership)

    if commit:
        await session.commit()

    return membership


async def create_property_definition(
    session: AsyncSession,
    initiative: Initiative,
    *,
    name: str | None = None,
    type: PropertyType = PropertyType.text,
    options: list[dict] | None = None,
    color: str | None = None,
    position: float = 0.0,
    commit: bool = True,
    **overrides: Any,
) -> PropertyDefinition:
    """
    Create a test property definition with sensible defaults.

    Auto-generates a unique name if not provided. When ``type`` is a
    select/multi_select and ``options`` is None, seeds a default option
    list so the definition is valid.

    Args:
        session: Database session
        initiative: Initiative the definition belongs to
        name: Property name (auto-generated if None)
        type: Property type (default: text)
        options: Option list for select/multi_select types
        color: Optional hex color
        position: Sort position (default: 0.0)
        commit: Whether to commit the transaction (default True)
        **overrides: Override any default field values

    Returns:
        Created PropertyDefinition instance
    """
    await route_session_to_guild(session, initiative.guild_id)

    if name is None:
        name = f"Prop {datetime.now(timezone.utc).timestamp()}"

    if type in {PropertyType.select, PropertyType.multi_select} and options is None:
        options = [
            {"value": "a", "label": "A"},
            {"value": "b", "label": "B"},
        ]
    elif type not in {PropertyType.select, PropertyType.multi_select}:
        # Non-select types don't store options.
        options = None

    defaults = {
        "initiative_id": initiative.id,
        "name": name,
        "type": type,
        "position": position,
        "color": color,
        "options": options,
    }

    data = {**defaults, **overrides}
    definition = PropertyDefinition(**data)
    session.add(definition)

    if commit:
        await session.commit()
        await session.refresh(definition)

    return definition


async def create_document_property_value(
    session: AsyncSession,
    document: Document,
    definition: PropertyDefinition,
    *,
    commit: bool = True,
    **value_kwargs: Any,
) -> DocumentPropertyValue:
    """
    Attach a typed property value to a document.

    Accepts any of ``value_text``, ``value_number``, ``value_boolean``,
    ``value_date``, ``value_datetime``, ``value_user_id``, ``value_json``.

    Args:
        session: Database session
        document: Document to attach the value to
        definition: PropertyDefinition the value references
        commit: Whether to commit the transaction (default True)
        **value_kwargs: Typed column values

    Returns:
        Created DocumentPropertyValue instance
    """
    await route_session_to_guild(session, document.guild_id)

    row = DocumentPropertyValue(
        document_id=document.id,
        property_id=definition.id,
        **value_kwargs,
    )
    session.add(row)

    if commit:
        await session.commit()

    return row


async def create_task_property_value(
    session: AsyncSession,
    task: Task,
    definition: PropertyDefinition,
    *,
    commit: bool = True,
    **value_kwargs: Any,
) -> TaskPropertyValue:
    """
    Attach a typed property value to a task.

    Accepts any of ``value_text``, ``value_number``, ``value_boolean``,
    ``value_date``, ``value_datetime``, ``value_user_id``, ``value_json``.

    Args:
        session: Database session
        task: Task to attach the value to
        definition: PropertyDefinition the value references
        commit: Whether to commit the transaction (default True)
        **value_kwargs: Typed column values

    Returns:
        Created TaskPropertyValue instance
    """
    await route_session_to_guild(session, task.guild_id)

    row = TaskPropertyValue(
        task_id=task.id,
        property_id=definition.id,
        **value_kwargs,
    )
    session.add(row)

    if commit:
        await session.commit()

    return row


async def create_calendar(
    session: AsyncSession,
    initiative: Initiative,
    creator: User,
    *,
    name: str | None = None,
    commit: bool = True,
    **overrides: Any,
) -> Calendar:
    """Create a test calendar with sensible defaults.

    Mirrors the create endpoint's default sharing: the creator owns it and
    every initiative member can read it. The initiative is expected to be
    calendars-enabled — callers that need to test the feature flag should
    toggle that on the passed-in ``initiative``.
    """
    await route_session_to_guild(session, initiative.guild_id)

    defaults = {
        "guild_id": initiative.guild_id,
        "initiative_id": initiative.id,
        "created_by": creator.id,
        "name": name or f"Calendar {datetime.now(timezone.utc).timestamp()}",
    }

    data = {**defaults, **overrides}
    calendar = Calendar(**data)
    session.add(calendar)

    if commit:
        await session.commit()
        await session.refresh(calendar)

        session.add(
            ResourceGrant(
                resource_type="calendar",
                resource_id=calendar.id,
                user_id=creator.id,
                level=ResourceAccessLevel.owner,
                guild_id=calendar.guild_id,
                initiative_id=calendar.initiative_id,
            )
        )
        session.add(
            ResourceGrant(
                resource_type="calendar",
                resource_id=calendar.id,
                all_initiative_members=True,
                level=ResourceAccessLevel.read,
                guild_id=calendar.guild_id,
                initiative_id=calendar.initiative_id,
            )
        )
        await session.commit()

    return calendar


async def create_guild_calendar(
    session: AsyncSession,
    guild: Guild,
    creator: User,
    *,
    name: str | None = None,
    shared_with_everyone: bool = True,
    **overrides: Any,
) -> Calendar:
    """A guild calendar — the one the calendar app installs.

    Belongs to no initiative, which is the whole of what makes it different: it
    holds its own events and reaches into nothing. Mirrors what
    ``guild_apps.create_app_artifacts`` builds, so a test exercises the same row
    an install produces rather than an approximation of one.
    """
    await route_session_to_guild(session, guild.id)

    calendar = Calendar(
        **{
            "guild_id": guild.id,
            "initiative_id": None,
            "created_by": creator.id,
            "name": name or "Guild calendar",
            **overrides,
        }
    )
    session.add(calendar)
    await session.commit()
    await session.refresh(calendar)

    session.add(
        ResourceGrant(
            resource_type="calendar",
            resource_id=calendar.id,
            user_id=creator.id,
            level=ResourceAccessLevel.owner,
            guild_id=guild.id,
            initiative_id=None,
        )
    )
    if shared_with_everyone:
        # At guild scope the everyone grant reads as every member of the guild.
        session.add(
            ResourceGrant(
                resource_type="calendar",
                resource_id=calendar.id,
                all_initiative_members=True,
                level=ResourceAccessLevel.read,
                guild_id=guild.id,
                initiative_id=None,
            )
        )
    await session.commit()
    return calendar


async def create_guild_app(
    session: AsyncSession,
    guild: Guild,
    creator: User,
    *,
    definition: dict[str, Any],
    listing_uid: str = "TESTAPP0000001",
    listing_version: str = "1.0.0",
    name: str = "Test app",
    **overrides: Any,
) -> GuildApp:
    """An installed app, written straight into the guild's schema.

    Deliberately not routed through the install endpoint. A ``service`` app's
    definition is publishable and storable today but the install path does not
    mount one yet (``GUILD_INSTALLABLE_APP_KINDS``), and the configuration and
    connection machinery it carries needs an install to exist to be exercised
    at all. This is that install: the same row the endpoint will write once the
    kind is admitted, so the tests hold the real endpoints rather than a mock.
    """
    await route_session_to_guild(session, guild.id)

    app = GuildApp(
        **{
            "guild_id": guild.id,
            "listing_uid": listing_uid,
            "listing_version": listing_version,
            "app_kind": definition.get("app_kind", "service"),
            "name": name,
            "definition": definition,
            "created_by": creator.id,
            **overrides,
        }
    )
    session.add(app)
    await session.commit()
    await session.refresh(app)
    return app


async def create_app_service_registration(
    session: AsyncSession,
    *,
    public_id: str = "tests.app-service",
    base_url: str = "https://app.example.test",
    listing_uid: str | None = None,
    allowed_origins: list[str] | None = None,
    grants: list[str] | None = None,
    mandatory: bool = False,
    enabled: bool = True,
    status: str = "ok",
    **overrides: Any,
) -> AppServiceRegistration:
    """A deployment-level registration, written straight into ``public``.

    Deliberately not routed through :mod:`app.services.marketplace.registrations`:
    creating one there runs the handshake against a live container, which a test
    has no business standing up. The row is what everything downstream reads, so
    this is the wiring an operator would have done.

    The in-process snapshot is dropped afterwards, so the very next read sees
    this registration rather than whatever a previous test left cached.
    """
    row = AppServiceRegistration(
        **{
            "public_id": public_id,
            "listing_uid": listing_uid,
            "base_url": base_url,
            "allowed_origins": allowed_origins
            if allowed_origins is not None
            else [base_url],
            "secret_encrypted": encrypt_field("test-secret", SALT_APP_SERVICE_SECRET),
            "grants": grants or [],
            "mandatory": mandatory,
            "enabled": enabled,
            "status": status,
            **overrides,
        }
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    invalidate_registrations()
    return row


async def create_app_delegation(
    session: AsyncSession,
    app: GuildApp,
    user: User,
    *,
    can_read: bool = True,
    can_write: bool = False,
    **overrides: Any,
) -> GuildAppUserDelegation:
    """A member's standing authorization for one install to act as them.

    Written straight into the guild's schema, so a suite that is about what a
    delegated call may do does not have to walk the consent flow first.
    """
    await route_session_to_guild(session, app.guild_id)

    row = GuildAppUserDelegation(
        **{
            "guild_id": app.guild_id,
            "app_id": app.id,
            "user_id": user.id,
            "can_read": can_read,
            "can_write": can_write,
            **overrides,
        }
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


def marketplace_uid(label: str) -> str:
    """A valid catalog uid from a readable label.

    Crockford base32 leaves out I, L, O and U so a code can be transcribed by
    hand — which makes most words unusable verbatim. This drops the letters the
    alphabet does not have and pads to length, so a test can say what a listing
    is instead of carrying an opaque literal.
    """
    kept = [c for c in label.upper() if c in UID_ALPHABET]
    return "".join(kept)[:UID_LENGTH].ljust(UID_LENGTH, "0")


async def create_marketplace_listing(
    session: AsyncSession,
    *,
    uid: str = "TEST0000000001",
    public_id: str = "test.listing",
    kind: str = "dashboard",
    version: str = "1.0.0",
    definition: dict[str, Any] | None = None,
    min_app_version: str | None = None,
    available: bool = True,
    commit: bool = True,
    **overrides: Any,
) -> MarketplaceListing:
    """A catalog listing with one published version.

    Built through the real upsert, so a test listing is held to the same
    validation a shipped or downloaded one is — a definition this build cannot
    render fails here rather than in the assertion.
    """
    manifest = {
        "uid": uid,
        "public_id": public_id,
        "kind": kind,
        "name": overrides.pop("name", "Test listing"),
        # Required on every ingestion path, so a test listing carries one too.
        "publisher": overrides.pop("publisher", "Tests"),
        "description": overrides.pop("description", "A listing for tests."),
        "avatar_url": overrides.pop("avatar_url", "/marketplace/test.svg"),
        "version": version,
        "min_app_version": min_app_version,
        "definition": definition
        if definition is not None
        else {
            "widgets": [
                {
                    "id": "w1",
                    "type": "stat",
                    "binding": {"source": "task_counts"},
                }
            ]
        },
        **overrides,
    }
    listing = await marketplace_catalog.upsert_listing(
        session, manifest, source="builtin"
    )
    if not available:
        listing.available = False
        session.add(listing)
    if commit:
        await session.commit()
        await session.refresh(listing)
    return listing


async def create_dashboard(
    session: AsyncSession,
    initiative: Initiative,
    creator: User,
    *,
    name: str | None = None,
    definition: dict[str, Any] | None = None,
    commit: bool = True,
    **overrides: Any,
) -> Dashboard:
    """Create a test dashboard with sensible defaults.

    Mirrors the create endpoint's default sharing: the creator owns it and
    every initiative member can read it. ``definition`` defaults to a single
    KPI widget so the row carries a realistic, already-normalized canvas; the
    initiative is expected to be dashboards-enabled.
    """
    await route_session_to_guild(session, initiative.guild_id)

    defaults = {
        "guild_id": initiative.guild_id,
        "initiative_id": initiative.id,
        "created_by": creator.id,
        "name": name or f"Dashboard {datetime.now(timezone.utc).timestamp()}",
        "definition": definition
        if definition is not None
        else normalize_dashboard_definition(
            {
                "widgets": [
                    {
                        "id": "w1",
                        "type": "stat",
                        "binding": {"source": "counter", "counter_id": None},
                    }
                ]
            }
        ),
        "config": {"widgets": {}},
    }

    data = {**defaults, **overrides}
    dashboard = Dashboard(**data)
    session.add(dashboard)

    if commit:
        await session.commit()
        await session.refresh(dashboard)

        session.add(
            ResourceGrant(
                resource_type="dashboard",
                resource_id=dashboard.id,
                user_id=creator.id,
                level=ResourceAccessLevel.owner,
                guild_id=dashboard.guild_id,
                initiative_id=dashboard.initiative_id,
            )
        )
        session.add(
            ResourceGrant(
                resource_type="dashboard",
                resource_id=dashboard.id,
                all_initiative_members=True,
                level=ResourceAccessLevel.read,
                guild_id=dashboard.guild_id,
                initiative_id=dashboard.initiative_id,
            )
        )
        await session.commit()

    return dashboard


async def create_calendar_event(
    session: AsyncSession,
    calendar: Calendar,
    creator: User,
    *,
    title: str | None = None,
    commit: bool = True,
    **overrides: Any,
) -> CalendarEvent:
    """Create a test calendar event with sensible defaults.

    Defaults to a one-hour event starting "now"; callers that care about
    the timing should override ``start_at`` / ``end_at``. Events carry no
    grants of their own — access derives from the parent ``calendar``.
    """
    await route_session_to_guild(session, calendar.guild_id)

    now = datetime.now(timezone.utc)
    defaults = {
        "guild_id": calendar.guild_id,
        "calendar_id": calendar.id,
        "created_by": creator.id,
        "title": title or f"Event {now.timestamp()}",
        "start_at": now,
        "end_at": now + timedelta(hours=1),
        "all_day": False,
    }

    data = {**defaults, **overrides}
    event = CalendarEvent(**data)
    session.add(event)

    if commit:
        await session.commit()
        await session.refresh(event)

    return event


async def create_calendar_event_property_value(
    session: AsyncSession,
    event: CalendarEvent,
    definition: PropertyDefinition,
    *,
    commit: bool = True,
    **value_kwargs: Any,
) -> CalendarEventPropertyValue:
    """Attach a typed property value to a calendar event.

    Mirrors :func:`create_document_property_value` /
    :func:`create_task_property_value` for the event value table.
    """
    await route_session_to_guild(session, event.guild_id)

    row = CalendarEventPropertyValue(
        event_id=event.id,
        property_id=definition.id,
        **value_kwargs,
    )
    session.add(row)

    if commit:
        await session.commit()

    return row


async def create_document(
    session: AsyncSession,
    initiative: Initiative,
    creator: User,
    *,
    title: str | None = None,
    commit: bool = True,
    **overrides: Any,
) -> Document:
    """Create a test document with sensible defaults.

    Defaults to a ``native`` (editor) document with empty content and an
    owner grant for ``creator``, mirroring the create endpoint's DAC setup.
    """
    await route_session_to_guild(session, initiative.guild_id)

    defaults = {
        "guild_id": initiative.guild_id,
        "initiative_id": initiative.id,
        "title": title or f"Test Document {datetime.now(timezone.utc).timestamp()}",
        "document_type": DocumentType.native,
        "created_by": creator.id,
    }
    document = Document(**{**defaults, **overrides})
    session.add(document)

    # The owner grant is part of the factory's contract in BOTH modes; with
    # commit=False it is flushed (id available) but left uncommitted with the
    # rest of the caller's transaction.
    await (session.commit() if commit else session.flush())
    if commit:
        await session.refresh(document)
    session.add(
        ResourceGrant(
            resource_type="document",
            resource_id=document.id,
            user_id=creator.id,
            level=ResourceAccessLevel.owner,
            guild_id=document.guild_id,
            initiative_id=document.initiative_id,
        )
    )
    if commit:
        await session.commit()

    return document


async def create_comment(
    session: AsyncSession,
    author: User,
    *,
    task: Task | None = None,
    document: Document | None = None,
    content: str = "A test comment",
    commit: bool = True,
    **overrides: Any,
) -> Comment:
    """Create a comment on exactly one of ``task`` or ``document``."""
    if (task is None) == (document is None):
        raise ValueError("pass exactly one of task= or document=")
    parent = task if task is not None else document
    await route_session_to_guild(session, parent.guild_id)

    defaults = {
        "guild_id": parent.guild_id,
        "content": content,
        "created_by": author.id,
        "task_id": task.id if task else None,
        "document_id": document.id if document else None,
    }
    comment = Comment(**{**defaults, **overrides})
    session.add(comment)

    if commit:
        await session.commit()
        await session.refresh(comment)

    return comment


async def create_tag(
    session: AsyncSession,
    guild: Guild,
    *,
    name: str | None = None,
    commit: bool = True,
    **overrides: Any,
) -> Tag:
    """Create a guild-scoped tag."""
    await route_session_to_guild(session, guild.id)

    defaults = {
        "guild_id": guild.id,
        "name": name or f"tag-{datetime.now(timezone.utc).timestamp()}",
    }
    tag = Tag(**{**defaults, **overrides})
    session.add(tag)

    if commit:
        await session.commit()
        await session.refresh(tag)

    return tag


async def create_subtask(
    session: AsyncSession,
    task: Task,
    *,
    content: str = "A test subtask",
    commit: bool = True,
    **overrides: Any,
) -> Subtask:
    """Create a subtask under ``task``."""
    await route_session_to_guild(session, task.guild_id)

    defaults = {
        "guild_id": task.guild_id,
        "task_id": task.id,
        "content": content,
    }
    subtask = Subtask(**{**defaults, **overrides})
    session.add(subtask)

    if commit:
        await session.commit()
        await session.refresh(subtask)

    return subtask


async def create_task_status(
    session: AsyncSession,
    project: Project,
    *,
    name: str | None = None,
    category: TaskStatusCategory = TaskStatusCategory.todo,
    commit: bool = True,
    **overrides: Any,
) -> TaskStatus:
    """Create a task status for ``project`` (does not deduplicate; use
    ``create_task`` when you just need a task in a given category)."""
    await route_session_to_guild(session, project.guild_id)

    defaults = {
        "guild_id": project.guild_id,
        "project_id": project.id,
        "name": name or category.value.replace("_", " ").title(),
        "category": category,
        "position": 0,
    }
    status = TaskStatus(**{**defaults, **overrides})
    session.add(status)

    if commit:
        await session.commit()
        await session.refresh(status)

    return status


async def create_counter_group(
    session: AsyncSession,
    initiative: Initiative,
    creator: User,
    *,
    name: str | None = None,
    commit: bool = True,
    **overrides: Any,
) -> CounterGroup:
    """Create a counter group with an owner grant for ``creator``."""
    await route_session_to_guild(session, initiative.guild_id)

    defaults = {
        "guild_id": initiative.guild_id,
        "initiative_id": initiative.id,
        "name": name or f"Test Counters {datetime.now(timezone.utc).timestamp()}",
        "created_by": creator.id,
    }
    group = CounterGroup(**{**defaults, **overrides})
    session.add(group)

    if commit:
        await session.commit()
        await session.refresh(group)

        session.add(
            ResourceGrant(
                resource_type="counter_group",
                resource_id=group.id,
                user_id=creator.id,
                level=ResourceAccessLevel.owner,
                guild_id=group.guild_id,
                initiative_id=group.initiative_id,
            )
        )
        await session.commit()

    return group


async def create_counter(
    session: AsyncSession,
    group: CounterGroup,
    *,
    name: str | None = None,
    commit: bool = True,
    **overrides: Any,
) -> Counter:
    """Create a counter inside ``group``."""
    await route_session_to_guild(session, group.guild_id)

    defaults = {
        "guild_id": group.guild_id,
        "counter_group_id": group.id,
        "name": name or f"Counter {datetime.now(timezone.utc).timestamp()}",
    }
    counter = Counter(**{**defaults, **overrides})
    session.add(counter)

    if commit:
        await session.commit()
        await session.refresh(counter)

    return counter


async def create_upload(
    session: AsyncSession,
    guild: Guild,
    uploader: User,
    *,
    filename: str | None = None,
    commit: bool = True,
    **overrides: Any,
) -> Upload:
    """Create an upload row (metadata only; writes no file to disk)."""
    await route_session_to_guild(session, guild.id)

    defaults = {
        "guild_id": guild.id,
        "created_by": uploader.id,
        "filename": filename or f"file-{datetime.now(timezone.utc).timestamp()}.txt",
        "size_bytes": 1,
    }
    upload = Upload(**{**defaults, **overrides})
    session.add(upload)

    if commit:
        await session.commit()
        await session.refresh(upload)

    return upload


def set_auth_scope(scope: str = "guild") -> None:
    """Set the deploy-time login posture (``settings.AUTH_SCOPE``) for the
    current test; defaults to per-guild, the posture the guild auth surface
    requires. The ``_reset_auth_scope`` autouse fixture (conftest) restores the
    default after each test."""
    from app.core.config import AuthScope, settings

    settings.AUTH_SCOPE = AuthScope(scope)


async def create_auth_provider(
    session: AsyncSession,
    commit: bool = True,
    **overrides: Any,
) -> AuthProvider:
    """Create an operator-global auth provider registry row.

    Defaults to a login-ready OIDC row pointing at the test IdP constants
    (``app.testing.oidc``), so a fake-IdP flow verifies against it as-is.
    """
    from app.testing.oidc import CLIENT_ID as _TEST_CLIENT_ID, ISSUER as _TEST_ISSUER

    defaults = {
        "slug": "corp",
        "display_name": "Corp SSO",
        "kind": AuthProviderKind.oidc.value,
        "enabled": True,
        "guild_id": None,
        "issuer": _TEST_ISSUER,
        "client_id": _TEST_CLIENT_ID,
        "scopes": "openid email",
        "allow_jit": True,
    }
    provider = AuthProvider(**{**defaults, **overrides})
    session.add(provider)

    if commit:
        await session.commit()
        await session.refresh(provider)

    return provider


async def create_federated_identity(
    session: AsyncSession,
    user: User,
    *,
    subject: str | None = None,
    provider: "AuthProvider | None" = None,
    commit: bool = True,
    **overrides: Any,
) -> FederatedIdentity:
    """Link ``user`` to an auth provider (the platform row by default).

    Gets-or-creates the operator-global platform provider so tests can mark a
    user as SSO-linked without configuring OIDC.
    """
    if provider is None:
        provider = (
            await session.exec(
                select(AuthProvider).where(
                    AuthProvider.slug == PLATFORM_OIDC_SLUG,
                    AuthProvider.guild_id.is_(None),
                )
            )
        ).one_or_none()
        if provider is None:
            provider = AuthProvider(
                slug=PLATFORM_OIDC_SLUG,
                display_name="Test SSO",
                kind=AuthProviderKind.oidc.value,
                enabled=True,
                issuer="https://idp.test.example",
                client_id="test-client",
                allow_jit=True,
            )
            session.add(provider)
            await session.flush()

    defaults = {
        "user_id": user.id,
        "provider_id": provider.id,
        "subject": subject or f"test-sub-{user.id}",
        "email_verified": True,
    }
    identity = FederatedIdentity(**{**defaults, **overrides})
    session.add(identity)

    if commit:
        await session.commit()
        await session.refresh(identity)

    return identity


# --- generic tool construction ---------------------------------------------
#
# One arm per Tool, so a test that needs "an instance of every tool" derives it
# from the enum instead of restating the list. The completeness check runs at
# import time: a new Tool member fails here once, with a message naming it,
# rather than in each test that happens to enumerate tools.

TOOL_FACTORIES: dict[Tool, Any] = {
    Tool.project: create_project,
    Tool.document: create_document,
    Tool.queue: create_queue,
    Tool.counter_group: create_counter_group,
    Tool.calendar: create_calendar,
    Tool.dashboard: create_dashboard,
}

if set(TOOL_FACTORIES) != set(Tool):
    missing = set(Tool) - set(TOOL_FACTORIES)
    extra = set(TOOL_FACTORIES) - set(Tool)
    raise RuntimeError(
        f"TOOL_FACTORIES must cover the Tool enum exactly "
        f"(missing: {sorted(t.value for t in missing)}, "
        f"unknown: {sorted(getattr(t, 'value', t) for t in extra)})"
    )


async def create_tool_entity(
    session: AsyncSession,
    tool: Tool,
    initiative: Initiative,
    creator: User,
    **overrides: Any,
) -> Any:
    """Create one instance of ``tool``'s content, whichever tool it is."""
    return await TOOL_FACTORIES[tool](session, initiative, creator, **overrides)


async def enable_all_tools(session: AsyncSession, initiative: Initiative) -> Initiative:
    """Flip on every toggleable tool's master switch, derived from the enum so a
    new tool is enabled here without an edit."""
    await route_session_to_guild(session, initiative.guild_id)
    fresh = await session.get(Initiative, initiative.id)
    assert fresh is not None
    for tool in TOGGLEABLE_TOOLS:
        setattr(fresh, tool.view_permission, True)
    session.add(fresh)
    await session.commit()
    await session.refresh(fresh)
    return fresh
