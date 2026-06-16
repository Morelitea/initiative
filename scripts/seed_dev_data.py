"""TTRPG-themed dev data seeder for Initiative.

Usage:
    python seed_dev_data.py          # Create test data
    python seed_dev_data.py --clean  # Remove seeded test data

Designed to run from the backend/ directory (CWD) so app imports resolve.
Saves created IDs to .vscode/.dev_seed_ids.json for cleanup.

Creates 3 guilds with multiple users, initiatives, projects, tasks, documents,
tags, and comments to exercise all features of the app.
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

# ---------------------------------------------------------------------------
# Bootstrap: add backend/ to sys.path so `app.*` imports work when invoked
# as `python ../scripts/seed_dev_data.py` from the backend/ directory.
# ---------------------------------------------------------------------------
BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from sqlmodel import select  # noqa: E402
from sqlmodel.ext.asyncio.session import AsyncSession  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.encryption import encrypt_field, hash_email, SALT_EMAIL  # noqa: E402
from app.core.security import get_password_hash  # noqa: E402
from app.db.schema_provisioning import provision_guild  # noqa: E402
from app.db.session import AdminSessionLocal, set_rls_context  # noqa: E402
from app.db.tenancy import GUILD_SCOPED_TABLES  # noqa: E402
from app.models.calendar_event import (  # noqa: E402
    CalendarEvent,
    CalendarEventAttendee,
    CalendarEventDocument,
    CalendarEventTag,
    RSVPStatus,
)
from app.models.comment import Comment  # noqa: E402
from app.models.counter import (  # noqa: E402
    Counter,
    CounterGroup,
    CounterGroupPermission,
    CounterGroupRolePermission,
    CounterPermissionLevel,
    CounterViewMode,
)
from app.models.document import (  # noqa: E402
    Document,
    DocumentLink,
    DocumentPermission,
    DocumentPermissionLevel,
    ProjectDocument,
)
from app.models.guild import Guild, GuildMembership, GuildRole  # noqa: E402
from app.models.queue import (  # noqa: E402
    Queue,
    QueueItem,
    QueueItemTag,
    QueuePermission,
    QueuePermissionLevel,
)
from app.models.guild_setting import GuildSetting  # noqa: E402
from app.models.initiative import (  # noqa: E402
    Initiative,
    InitiativeMember,
    InitiativeRoleModel,
    InitiativeRolePermission,
)
from app.models.project import (  # noqa: E402
    Project,
    ProjectPermission,
    ProjectPermissionLevel,
)
from app.models.project_activity import ProjectFavorite  # noqa: E402
from app.models.property import (  # noqa: E402
    CalendarEventPropertyValue,
    DocumentPropertyValue,
    PropertyDefinition,
    PropertyType,
    TaskPropertyValue,
)
from app.models.recent_view import RecentView  # noqa: E402
from app.models.tag import DocumentTag, ProjectTag, Tag, TaskTag  # noqa: E402
from app.models.task import (  # noqa: E402
    Subtask,
    Task,
    TaskAssignee,
    TaskPriority,
    TaskStatus,
    TaskStatusCategory,
)
from app.models.user import User, UserRole  # noqa: E402
from app.services.app_settings import get_or_create_guild_settings  # noqa: E402
from app.services.guilds import get_primary_guild  # noqa: E402
from app.services.initiatives import (  # noqa: E402
    create_builtin_roles,
    ensure_default_initiative,
)
from app.services.task_statuses import ensure_default_statuses  # noqa: E402

STATE_FILE = Path(__file__).resolve().parent.parent / ".vscode" / ".dev_seed_ids.json"

# Consistent "now" for seeding
NOW = datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Lexical document content helper
# ---------------------------------------------------------------------------

def _doc(paragraphs: list[str]) -> dict:
    """Build a minimal Lexical editor JSON structure from plain text paragraphs."""
    children = []
    for text in paragraphs:
        children.append({
            "children": [{"text": text, "type": "text"}],
            "type": "paragraph",
        })
    return {"root": {"children": children, "type": "root"}}


# ---------------------------------------------------------------------------
# Mega-dungeon task generator (10 000 tasks for virtualization testing)
# ---------------------------------------------------------------------------

_DUNGEON_AREAS = [
    "Entrance Hall", "Crypt of Whispers", "The Bone Gallery", "Flooded Caverns",
    "Shadow Forge", "Hall of Mirrors", "Spider Nest", "Collapsed Library",
    "Throne of Ashes", "Ritual Chamber", "Fungal Grotto", "Iron Cage Arena",
    "Ember Vaults", "Wailing Cells", "Clockwork Passage", "Dread Pantry",
    "Ossuary", "Sunken Chapel", "Alchemist Lab", "Guard Barracks",
]

_DUNGEON_VERBS = [
    "Clear", "Explore", "Map", "Loot", "Secure", "Investigate",
    "Disarm traps in", "Search for secrets in", "Barricade", "Purify",
]

_DUNGEON_USERS = [
    "Dungeon Master", "Thorn Ironforge", "Elara Moonwhisper",
    "Vex Shadowstep", "Admin User",
]


def _generate_mega_dungeon_tasks(project_id: int) -> list[dict]:
    """Generate 1 000 TTRPG-themed task defs for the mega dungeon project."""
    import random as _rng
    _rng.seed(42)  # deterministic for reproducible seeds

    priorities = [TaskPriority.low, TaskPriority.medium, TaskPriority.high, TaskPriority.urgent]
    categories = [
        TaskStatusCategory.backlog, TaskStatusCategory.todo,
        TaskStatusCategory.in_progress, TaskStatusCategory.done,
    ]

    _adjectives = [
        "Cursed", "Hidden", "Burning", "Frozen", "Ancient", "Ruined",
        "Enchanted", "Haunted", "Gilded", "Shattered", "Verdant", "Infernal",
    ]

    tasks: list[dict] = []
    for i in range(1, 1_001):
        area = _DUNGEON_AREAS[i % len(_DUNGEON_AREAS)]
        verb = _DUNGEON_VERBS[i % len(_DUNGEON_VERBS)]
        adj = _adjectives[i % len(_adjectives)]
        floor = (i - 1) // 20 + 1
        room = (i - 1) % 20 + 1

        td: dict = {
            "project_id": project_id,
            "title": f"Floor {floor}, Room {room}: {verb} the {adj} {area}",
            "description": f"Level {floor} exploration — {verb.lower()} the {adj.lower()} {area} "
                           f"and report findings to the party.",
            "priority": _rng.choice(priorities),
            "category": _rng.choice(categories),
        }

        # ~20% of tasks have assignees (reduced from 40% for speed)
        if _rng.random() < 0.2:
            td["assignees"] = _rng.sample(_DUNGEON_USERS, k=_rng.randint(1, 2))

        # ~10% have due dates
        if _rng.random() < 0.1:
            td["due_days"] = _rng.randint(-5, 30)

        # ~8% have start dates
        if _rng.random() < 0.08:
            td["start_days"] = _rng.randint(-10, 5)

        # ~5% have subtasks
        if _rng.random() < 0.05:
            td["subtasks"] = [
                f"Check {area} entrance",
                f"Search {area} for treasure",
                f"Neutralize {area} hazards",
            ]

        tasks.append(td)

    return tasks


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))
    print(f"  State saved to {STATE_FILE}")


def _load_state() -> dict | None:
    if not STATE_FILE.exists():
        return None
    return json.loads(STATE_FILE.read_text())


async def _find_superuser(session: AsyncSession) -> User:
    """Find the superuser created by init_db."""
    email = settings.FIRST_SUPERUSER_EMAIL
    if not email:
        print("ERROR: FIRST_SUPERUSER_EMAIL is not set in .env or environment.")
        sys.exit(1)
    result = await session.exec(select(User).where(User.email_hash == hash_email(email)))
    user = result.one_or_none()
    if user is None:
        print(f"ERROR: Superuser {email} not found.")
        print("  Make sure init_db has run (dev:migrate task).")
        sys.exit(1)
    return user


# ---------------------------------------------------------------------------
# ID tracker — collects all created IDs for cleanup
# ---------------------------------------------------------------------------

class IDTracker:
    def __init__(self) -> None:
        self.data: dict[str, list] = {
            "users": [],
            "user_settings_modified": [],
            "guilds": [],
            "guild_memberships": [],
            "guild_settings": [],
            "initiatives": [],
            "initiative_roles": [],
            "initiative_role_permissions": [],
            "initiative_members": [],
            "projects": [],
            "project_permissions": [],
            "project_favorites": [],
            "recent_views": [],
            "task_statuses": [],
            "tasks": [],
            "subtasks": [],
            "task_assignees": [],
            "documents": [],
            "document_permissions": [],
            "document_links": [],
            "document_tags": [],
            "project_documents": [],
            "tags": [],
            "task_tags": [],
            "project_tags": [],
            "comments": [],
            "queues": [],
            "queue_items": [],
            "queue_item_tags": [],
            "queue_permissions": [],
            "counter_groups": [],
            "counters": [],
            "counter_group_permissions": [],
            "counter_group_role_permissions": [],
            "calendar_events": [],
            "calendar_event_attendees": [],
            "calendar_event_tags": [],
            "calendar_event_documents": [],
            "property_definitions": [],
            "task_property_values": [],
            "document_property_values": [],
            "calendar_event_property_values": [],
        }

    def add(self, key: str, value) -> None:
        self.data[key].append(value)


# ---------------------------------------------------------------------------
# Guild seeder helpers
# ---------------------------------------------------------------------------

async def _create_users(
    session: AsyncSession,
    ids: IDTracker,
    user_defs: list[dict],
) -> dict[str, User]:
    """Create users and return a name->User mapping.

    Each user_def can include optional settings overrides:
    timezone, locale, color_theme, week_starts_on, and notification booleans.
    """
    users: dict[str, User] = {}
    for ud in user_defs:
        user = User(
            email_hash=hash_email(ud["email"]),
            email_encrypted=encrypt_field(ud["email"], SALT_EMAIL),
            full_name=ud["full_name"],
            hashed_password=get_password_hash("changeme"),
            role=UserRole.member,
            is_active=True,
            timezone=ud.get("timezone", "UTC"),
            locale=ud.get("locale", "en"),
            color_theme=ud.get("color_theme", "kobold"),
            week_starts_on=ud.get("week_starts_on", 0),
            email_task_assignment=ud.get("email_task_assignment", True),
            email_overdue_tasks=ud.get("email_overdue_tasks", True),
            push_task_assignment=ud.get("push_task_assignment", True),
            push_overdue_tasks=ud.get("push_overdue_tasks", True),
        )
        session.add(user)
        await session.flush()
        ids.add("users", user.id)
        users[ud["full_name"]] = user
    return users


def _expunge_guild_scoped(session: AsyncSession) -> None:
    """Drop guild-scoped objects from the session's identity map between guilds.

    Under schema-per-guild, ids restart per schema (every guild has Initiative
    id=1, Project id=1, ...). Reusing one session across guilds collides those
    ids in the identity map (the noisy SAWarnings). Shared rows (users, guilds)
    have global ids and are left attached — only guild-scoped objects are dropped.
    """
    sync = session.sync_session
    for obj in list(sync.identity_map.values()):
        # expunge cascades along relationships, so a guild-scoped object from the
        # snapshot may already be detached (e.g. an Initiative's members went with
        # it) — skip anything no longer in the session.
        if obj in sync and getattr(obj, "__tablename__", None) in GUILD_SCOPED_TABLES:
            sync.expunge(obj)


async def _create_guild(
    session: AsyncSession,
    ids: IDTracker,
    *,
    name: str,
    description: str,
    creator: User,
) -> Guild:
    """Create a guild and admin membership for the creator."""
    guild = Guild(
        name=name,
        description=description,
        created_by_user_id=creator.id,
    )
    session.add(guild)
    await session.flush()
    ids.add("guilds", guild.id)

    membership = GuildMembership(
        guild_id=guild.id,
        user_id=creator.id,
        role=GuildRole.admin,
    )
    session.add(membership)
    ids.add("guild_memberships", {"guild_id": guild.id, "user_id": creator.id})
    await session.flush()
    return guild


async def _add_guild_members(
    session: AsyncSession,
    ids: IDTracker,
    guild: Guild,
    users: list[User],
    *,
    admin_users: list[User] | None = None,
) -> None:
    """Add users to a guild as members (or admins if specified)."""
    admin_ids = {u.id for u in (admin_users or [])}
    for user in users:
        role = GuildRole.admin if user.id in admin_ids else GuildRole.member
        membership = GuildMembership(
            guild_id=guild.id,
            user_id=user.id,
            role=role,
        )
        session.add(membership)
        ids.add("guild_memberships", {"guild_id": guild.id, "user_id": user.id})
    await session.flush()


async def _create_initiative(
    session: AsyncSession,
    ids: IDTracker,
    *,
    guild: Guild,
    name: str,
    description: str,
    color: str,
    pm_user: User,
    member_users: list[User] | None = None,
    queues_enabled: bool = False,
    counters_enabled: bool = False,
    events_enabled: bool = False,
) -> tuple[Initiative, InitiativeRoleModel, InitiativeRoleModel]:
    """Create an initiative with roles and members."""
    initiative = Initiative(
        guild_id=guild.id,
        name=name,
        description=description,
        color=color,
        queues_enabled=queues_enabled,
        counters_enabled=counters_enabled,
        events_enabled=events_enabled,
    )
    session.add(initiative)
    await session.flush()
    ids.add("initiatives", initiative.id)

    pm_role, member_role = await create_builtin_roles(session, initiative_id=initiative.id)
    ids.add("initiative_roles", pm_role.id)
    ids.add("initiative_roles", member_role.id)

    # Track role permissions
    for role in [pm_role, member_role]:
        result = await session.exec(
            select(InitiativeRolePermission).where(
                InitiativeRolePermission.initiative_role_id == role.id
            )
        )
        for perm in result.all():
            ids.add("initiative_role_permissions", {
                "initiative_role_id": perm.initiative_role_id,
                "permission_key": perm.permission_key,
            })

    # Add PM
    pm_member = InitiativeMember(
        initiative_id=initiative.id,
        user_id=pm_user.id,
        guild_id=guild.id,
        role_id=pm_role.id,
    )
    session.add(pm_member)
    ids.add("initiative_members", {"initiative_id": initiative.id, "user_id": pm_user.id})

    # Add members
    for user in (member_users or []):
        m = InitiativeMember(
            initiative_id=initiative.id,
            user_id=user.id,
            guild_id=guild.id,
            role_id=member_role.id,
        )
        session.add(m)
        ids.add("initiative_members", {"initiative_id": initiative.id, "user_id": user.id})

    await session.flush()
    return initiative, pm_role, member_role


async def _create_project(
    session: AsyncSession,
    ids: IDTracker,
    *,
    guild: Guild,
    initiative: Initiative,
    name: str,
    icon: str,
    description: str,
    owner: User,
    write_users: list[User] | None = None,
    read_users: list[User] | None = None,
) -> Project:
    """Create a project with permissions and default task statuses."""
    project = Project(
        guild_id=guild.id,
        name=name,
        icon=icon,
        description=description,
        owner_id=owner.id,
        initiative_id=initiative.id,
    )
    session.add(project)
    await session.flush()
    ids.add("projects", project.id)

    # Owner permission
    perm = ProjectPermission(
        project_id=project.id,
        user_id=owner.id,
        guild_id=guild.id,
        level=ProjectPermissionLevel.owner,
    )
    session.add(perm)
    ids.add("project_permissions", {"project_id": project.id, "user_id": owner.id})

    for user in (write_users or []):
        p = ProjectPermission(
            project_id=project.id,
            user_id=user.id,
            guild_id=guild.id,
            level=ProjectPermissionLevel.write,
        )
        session.add(p)
        ids.add("project_permissions", {"project_id": project.id, "user_id": user.id})

    for user in (read_users or []):
        p = ProjectPermission(
            project_id=project.id,
            user_id=user.id,
            guild_id=guild.id,
            level=ProjectPermissionLevel.read,
        )
        session.add(p)
        ids.add("project_permissions", {"project_id": project.id, "user_id": user.id})

    await session.flush()
    return project


async def _create_tasks(
    session: AsyncSession,
    ids: IDTracker,
    *,
    guild: Guild,
    status_map: dict[str, TaskStatus],
    task_defs: list[dict],
    all_users: dict[str, User],
) -> dict[str, Task]:
    """Create tasks, subtasks, and assignees from definitions."""
    created: dict[str, Task] = {}
    for i, td in enumerate(task_defs):
        status = status_map[td["category"]]
        due = td.get("due_days")
        start = td.get("start_days")
        task = Task(
            guild_id=guild.id,
            project_id=td["project_id"],
            task_status_id=status.id,
            title=td["title"],
            description=td.get("description"),
            priority=td["priority"],
            sort_order=float(i),
            due_date=(NOW + timedelta(days=due)) if due is not None else None,
            start_date=(NOW + timedelta(days=start)) if start is not None else None,
            is_archived=td.get("archived", False),
        )
        session.add(task)
        await session.flush()
        ids.add("tasks", task.id)
        created[td["title"]] = task

        for pos, content in enumerate(td.get("subtasks", [])):
            sub = Subtask(
                guild_id=guild.id,
                task_id=task.id,
                content=content,
                position=pos,
                is_completed=td.get("subtasks_done", False),
            )
            session.add(sub)
            await session.flush()
            ids.add("subtasks", sub.id)

        for assignee_name in td.get("assignees", []):
            user = all_users.get(assignee_name)
            if user:
                a = TaskAssignee(task_id=task.id, user_id=user.id, guild_id=guild.id)
                session.add(a)
                ids.add("task_assignees", {"task_id": task.id, "user_id": user.id})

    await session.flush()
    return created


async def _create_tags(
    session: AsyncSession,
    ids: IDTracker,
    guild: Guild,
    tag_defs: list[tuple[str, str]],
) -> dict[str, Tag]:
    """Create tags for a guild."""
    tags: dict[str, Tag] = {}
    for name, color in tag_defs:
        tag = Tag(guild_id=guild.id, name=name, color=color)
        session.add(tag)
        await session.flush()
        tags[name] = tag
        ids.add("tags", tag.id)
    return tags


async def _link_task_tags(
    session: AsyncSession,
    ids: IDTracker,
    tasks: dict[str, Task],
    tags: dict[str, Tag],
    links: list[tuple[str, list[str]]],
) -> None:
    for task_title, tag_names in links:
        task = tasks.get(task_title)
        if not task:
            continue
        for tn in tag_names:
            tag = tags.get(tn)
            if not tag:
                continue
            tt = TaskTag(task_id=task.id, tag_id=tag.id)
            session.add(tt)
            ids.add("task_tags", {"task_id": task.id, "tag_id": tag.id})
    await session.flush()


async def _link_project_tags(
    session: AsyncSession,
    ids: IDTracker,
    tags: dict[str, Tag],
    links: list[tuple[int, list[str]]],
) -> None:
    for proj_id, tag_names in links:
        for tn in tag_names:
            tag = tags.get(tn)
            if not tag:
                continue
            pt = ProjectTag(project_id=proj_id, tag_id=tag.id)
            session.add(pt)
            ids.add("project_tags", {"project_id": proj_id, "tag_id": tag.id})
    await session.flush()


async def _create_documents(
    session: AsyncSession,
    ids: IDTracker,
    *,
    guild: Guild,
    doc_defs: list[dict],
    all_users: dict[str, User],
) -> dict[str, Document]:
    """Create documents with permissions."""
    docs: dict[str, Document] = {}
    for dd in doc_defs:
        creator = all_users[dd["creator"]]
        doc = Document(
            guild_id=guild.id,
            initiative_id=dd["initiative_id"],
            title=dd["title"],
            content=_doc(dd["paragraphs"]),
            created_by_id=creator.id,
            updated_by_id=creator.id,
        )
        session.add(doc)
        await session.flush()
        ids.add("documents", doc.id)
        docs[dd["title"]] = doc

        # Owner permission for creator
        dperm = DocumentPermission(
            document_id=doc.id,
            user_id=creator.id,
            guild_id=guild.id,
            level=DocumentPermissionLevel.owner,
        )
        session.add(dperm)
        ids.add("document_permissions", {"document_id": doc.id, "user_id": creator.id})

        # Additional read/write permissions
        for writer_name in dd.get("writers", []):
            w = all_users.get(writer_name)
            if w:
                dp = DocumentPermission(
                    document_id=doc.id,
                    user_id=w.id,
                    guild_id=guild.id,
                    level=DocumentPermissionLevel.write,
                )
                session.add(dp)
                ids.add("document_permissions", {"document_id": doc.id, "user_id": w.id})

        for reader_name in dd.get("readers", []):
            r = all_users.get(reader_name)
            if r:
                dp = DocumentPermission(
                    document_id=doc.id,
                    user_id=r.id,
                    guild_id=guild.id,
                    level=DocumentPermissionLevel.read,
                )
                session.add(dp)
                ids.add("document_permissions", {"document_id": doc.id, "user_id": r.id})

    await session.flush()
    return docs


async def _link_doc_projects(
    session: AsyncSession,
    ids: IDTracker,
    guild: Guild,
    links: list[tuple[int, int, User]],
) -> None:
    for proj_id, doc_id, user in links:
        pd = ProjectDocument(
            project_id=proj_id,
            document_id=doc_id,
            guild_id=guild.id,
            attached_by_id=user.id,
        )
        session.add(pd)
        ids.add("project_documents", {"project_id": proj_id, "document_id": doc_id})
    await session.flush()


async def _link_doc_tags(
    session: AsyncSession,
    ids: IDTracker,
    docs: dict[str, Document],
    tags: dict[str, Tag],
    links: list[tuple[str, list[str]]],
) -> None:
    for doc_title, tag_names in links:
        doc = docs.get(doc_title)
        if not doc:
            continue
        for tn in tag_names:
            tag = tags.get(tn)
            if not tag:
                continue
            dt = DocumentTag(document_id=doc.id, tag_id=tag.id)
            session.add(dt)
            ids.add("document_tags", {"document_id": doc.id, "tag_id": tag.id})
    await session.flush()


async def _create_comments(
    session: AsyncSession,
    ids: IDTracker,
    guild: Guild,
    comment_defs: list[dict],
    tasks: dict[str, Task],
    docs: dict[str, Document],
    all_users: dict[str, User],
) -> None:
    for cd in comment_defs:
        author = all_users[cd["author"]]
        task = tasks.get(cd.get("task_title", ""))
        doc = docs.get(cd.get("doc_title", ""))
        comment = Comment(
            guild_id=guild.id,
            content=cd["content"],
            author_id=author.id,
            task_id=task.id if task else None,
            document_id=doc.id if doc else None,
        )
        session.add(comment)
        await session.flush()
        ids.add("comments", comment.id)


async def _create_favorites(
    session: AsyncSession,
    ids: IDTracker,
    guild: Guild,
    favorites: list[tuple[User, Project]],
) -> None:
    """Mark projects as favorites for users."""
    for user, project in favorites:
        fav = ProjectFavorite(
            user_id=user.id,
            project_id=project.id,
            guild_id=guild.id,
        )
        session.add(fav)
        ids.add("project_favorites", {"user_id": user.id, "project_id": project.id})
    await session.flush()


async def _create_recent_views(
    session: AsyncSession,
    ids: IDTracker,
    guild: Guild,
    views: list[tuple[User, Project]],
) -> None:
    """Record recent project views for users."""
    for user, project in views:
        view = RecentView(
            user_id=user.id,
            entity_type="project",
            entity_id=project.id,
            guild_id=guild.id,
        )
        session.add(view)
        ids.add(
            "recent_views",
            {
                "user_id": user.id,
                "entity_type": "project",
                "entity_id": project.id,
            },
        )
    await session.flush()


async def _create_document_links(
    session: AsyncSession,
    ids: IDTracker,
    guild: Guild,
    docs: dict[str, Document],
    links: list[tuple[str, str]],
) -> None:
    """Create wikilinks between documents (source -> target)."""
    for source_title, target_title in links:
        source = docs.get(source_title)
        target = docs.get(target_title)
        if not source or not target:
            continue
        dl = DocumentLink(
            source_document_id=source.id,
            target_document_id=target.id,
            guild_id=guild.id,
        )
        session.add(dl)
        ids.add("document_links", {
            "source_document_id": source.id,
            "target_document_id": target.id,
        })
    await session.flush()


async def _create_guild_settings(
    session: AsyncSession,
    ids: IDTracker,
    guild: Guild,
    **kwargs,
) -> GuildSetting:
    """Create or update guild settings."""
    gs = GuildSetting(guild_id=guild.id, **kwargs)
    session.add(gs)
    await session.flush()
    ids.add("guild_settings", gs.id)
    return gs


async def _apply_user_settings(
    session: AsyncSession,
    ids: IDTracker,
    admin_user: User,
    **overrides,
) -> None:
    """Modify the superuser's settings (tracked for cleanup reset)."""
    original = {
        "timezone": admin_user.timezone,
        "locale": admin_user.locale,
        "color_theme": admin_user.color_theme,
        "week_starts_on": admin_user.week_starts_on,
    }
    for key, value in overrides.items():
        setattr(admin_user, key, value)
    session.add(admin_user)
    await session.flush()
    ids.add("user_settings_modified", {"user_id": admin_user.id, "original": original})


# ---------------------------------------------------------------------------
# Queue permission helper
# ---------------------------------------------------------------------------

async def _enable_queue_permissions(
    session: AsyncSession,
    member_roles: list[InitiativeRoleModel],
) -> None:
    """Enable queues_enabled on member roles so all members can see queues."""
    for role in member_roles:
        result = await session.exec(
            select(InitiativeRolePermission).where(
                InitiativeRolePermission.initiative_role_id == role.id,
                InitiativeRolePermission.permission_key == "queues_enabled",
            )
        )
        perm = result.one_or_none()
        if perm:
            perm.enabled = True
            session.add(perm)
    await session.flush()


# ---------------------------------------------------------------------------
# Queue seeder helpers
# ---------------------------------------------------------------------------

async def _create_queues(
    session: AsyncSession,
    ids: IDTracker,
    guild: Guild,
    all_users: dict[str, User],
    tags: dict[str, Tag],
    queue_defs: list[dict],
) -> dict[str, Queue]:
    """Create queues with items, item tags, and permissions.

    Each queue_def has:
        initiative_id, name, description, created_by (user name),
        is_active (bool), current_round (int),
        write_users (list of names for write permission),
        items: list of dicts with label, position, user (name or None),
            color, notes, is_visible, tags (list of tag names)
        active_item_label (str, optional) — label of the currently active item
    """
    queues: dict[str, Queue] = {}
    for qd in queue_defs:
        creator = all_users[qd["created_by"]]
        queue = Queue(
            guild_id=guild.id,
            initiative_id=qd["initiative_id"],
            name=qd["name"],
            description=qd.get("description"),
            created_by_id=creator.id,
            is_active=qd.get("is_active", False),
            current_round=qd.get("current_round", 1),
        )
        session.add(queue)
        await session.flush()
        ids.add("queues", queue.id)

        # Owner permission for creator
        owner_perm = QueuePermission(
            queue_id=queue.id,
            user_id=creator.id,
            guild_id=guild.id,
            level=QueuePermissionLevel.owner,
        )
        session.add(owner_perm)
        ids.add("queue_permissions", {
            "queue_id": queue.id, "user_id": creator.id,
        })

        # Write permissions
        for uname in qd.get("write_users", []):
            user = all_users.get(uname)
            if user and user.id != creator.id:
                wp = QueuePermission(
                    queue_id=queue.id,
                    user_id=user.id,
                    guild_id=guild.id,
                    level=QueuePermissionLevel.write,
                )
                session.add(wp)
                ids.add("queue_permissions", {
                    "queue_id": queue.id, "user_id": user.id,
                })
        await session.flush()

        # Items
        active_label = qd.get("active_item_label")
        items_by_label: dict[str, QueueItem] = {}
        for item_def in qd.get("items", []):
            user_id = None
            if item_def.get("user"):
                linked_user = all_users.get(item_def["user"])
                if linked_user:
                    user_id = linked_user.id
            qi = QueueItem(
                guild_id=guild.id,
                queue_id=queue.id,
                label=item_def["label"],
                position=item_def.get("position", 0),
                user_id=user_id,
                color=item_def.get("color"),
                notes=item_def.get("notes"),
                is_visible=item_def.get("is_visible", True),
            )
            session.add(qi)
            await session.flush()
            ids.add("queue_items", qi.id)
            items_by_label[qi.label] = qi

            # Item tags
            for tag_name in item_def.get("tags", []):
                tag = tags.get(tag_name)
                if tag:
                    qit = QueueItemTag(
                        queue_item_id=qi.id,
                        tag_id=tag.id,
                    )
                    session.add(qit)
                    ids.add("queue_item_tags", {
                        "queue_item_id": qi.id, "tag_id": tag.id,
                    })
            await session.flush()

        # Set active item
        if active_label and active_label in items_by_label:
            queue.current_item_id = items_by_label[active_label].id
            session.add(queue)
            await session.flush()

        queues[qd["name"]] = queue

    return queues


# ---------------------------------------------------------------------------
# Counter / calendar event / property seeder helpers
# ---------------------------------------------------------------------------

async def _enable_role_feature(
    session: AsyncSession,
    member_roles: list[InitiativeRoleModel],
    permission_key: str,
) -> None:
    """Flip a feature-visibility permission ON for a set of member roles.

    Parallel to :func:`_enable_queue_permissions` but generalized for the
    counters / events keys. ``create_builtin_roles`` seeds member roles
    with the view-feature keys disabled by default; flipping them on
    lets non-PM members see the seeded content.
    """
    for role in member_roles:
        result = await session.exec(
            select(InitiativeRolePermission).where(
                InitiativeRolePermission.initiative_role_id == role.id,
                InitiativeRolePermission.permission_key == permission_key,
            )
        )
        perm = result.one_or_none()
        if perm:
            perm.enabled = True
            session.add(perm)
    await session.flush()


async def _create_counter_groups(
    session: AsyncSession,
    ids: IDTracker,
    guild: Guild,
    all_users: dict[str, User],
    group_defs: list[dict],
) -> dict[str, CounterGroup]:
    """Create counter groups with their child counters and permissions.

    Each ``group_def`` has:
        initiative_id, name, description, created_by (user name),
        role_grants: list of {role_id, level},
        user_grants: list of {user (name), level},
        counters: list of dicts with name, color, count, min, max, step,
            initial_count, view_mode, position.
    """
    groups: dict[str, CounterGroup] = {}
    for gd in group_defs:
        creator = all_users[gd["created_by"]]
        group = CounterGroup(
            guild_id=guild.id,
            initiative_id=gd["initiative_id"],
            name=gd["name"],
            description=gd.get("description"),
            created_by_id=creator.id,
        )
        session.add(group)
        await session.flush()
        ids.add("counter_groups", group.id)

        # Owner permission for creator
        owner_perm = CounterGroupPermission(
            counter_group_id=group.id,
            user_id=creator.id,
            guild_id=guild.id,
            level=CounterPermissionLevel.owner,
        )
        session.add(owner_perm)
        ids.add("counter_group_permissions", {
            "counter_group_id": group.id, "user_id": creator.id,
        })

        # Extra user grants
        for grant in gd.get("user_grants", []):
            user = all_users.get(grant["user"])
            if user and user.id != creator.id:
                up = CounterGroupPermission(
                    counter_group_id=group.id,
                    user_id=user.id,
                    guild_id=guild.id,
                    level=grant.get("level", CounterPermissionLevel.write),
                )
                session.add(up)
                ids.add("counter_group_permissions", {
                    "counter_group_id": group.id, "user_id": user.id,
                })

        # Role grants
        for grant in gd.get("role_grants", []):
            rp = CounterGroupRolePermission(
                counter_group_id=group.id,
                initiative_role_id=grant["role_id"],
                guild_id=guild.id,
                level=grant.get("level", CounterPermissionLevel.read),
            )
            session.add(rp)
            ids.add("counter_group_role_permissions", {
                "counter_group_id": group.id,
                "initiative_role_id": grant["role_id"],
            })
        await session.flush()

        # Counters
        for cd in gd.get("counters", []):
            counter = Counter(
                guild_id=guild.id,
                counter_group_id=group.id,
                name=cd["name"],
                color=cd.get("color"),
                count=Decimal(str(cd.get("count", 0))),
                min=Decimal(str(cd["min"])) if cd.get("min") is not None else None,
                max=Decimal(str(cd["max"])) if cd.get("max") is not None else None,
                step=Decimal(str(cd.get("step", 1))),
                initial_count=Decimal(str(cd.get("initial_count", 0))),
                view_mode=cd.get("view_mode", CounterViewMode.number),
                position=Decimal(str(cd.get("position", 0))),
            )
            session.add(counter)
            await session.flush()
            ids.add("counters", counter.id)

        groups[gd["name"]] = group

    return groups


async def _create_calendar_events(
    session: AsyncSession,
    ids: IDTracker,
    guild: Guild,
    all_users: dict[str, User],
    tags: dict[str, Tag],
    documents: dict[str, Document],
    event_defs: list[dict],
) -> dict[str, CalendarEvent]:
    """Create calendar events with attendees, tag links, and document links.

    Each ``event_def`` has:
        initiative_id, title, description, location, start_at, end_at,
        all_day, color, recurrence (dict; JSON-encoded into the column),
        created_by (user name),
        attendees: list of {user (name), rsvp_status (optional)},
        tags: list of tag names,
        documents: list of document titles (must exist in ``documents``).
    """
    events: dict[str, CalendarEvent] = {}
    for ed in event_defs:
        creator = all_users[ed["created_by"]]
        recurrence_raw = ed.get("recurrence")
        event = CalendarEvent(
            guild_id=guild.id,
            initiative_id=ed["initiative_id"],
            title=ed["title"],
            description=ed.get("description"),
            location=ed.get("location"),
            start_at=ed["start_at"],
            end_at=ed["end_at"],
            all_day=ed.get("all_day", False),
            color=ed.get("color"),
            recurrence=json.dumps(recurrence_raw) if recurrence_raw else None,
            created_by_id=creator.id,
        )
        session.add(event)
        await session.flush()
        ids.add("calendar_events", event.id)

        # Attendees
        for att in ed.get("attendees", []):
            user = all_users.get(att["user"])
            if user is None:
                continue
            attendee = CalendarEventAttendee(
                calendar_event_id=event.id,
                user_id=user.id,
                guild_id=guild.id,
                rsvp_status=att.get("rsvp_status", RSVPStatus.pending),
            )
            session.add(attendee)
            ids.add("calendar_event_attendees", {
                "calendar_event_id": event.id, "user_id": user.id,
            })

        # Tag links
        for tag_name in ed.get("tags", []):
            tag = tags.get(tag_name)
            if tag is None:
                continue
            link = CalendarEventTag(
                calendar_event_id=event.id,
                tag_id=tag.id,
            )
            session.add(link)
            ids.add("calendar_event_tags", {
                "calendar_event_id": event.id, "tag_id": tag.id,
            })

        # Document links
        for doc_title in ed.get("documents", []):
            doc = documents.get(doc_title)
            if doc is None:
                continue
            link = CalendarEventDocument(
                calendar_event_id=event.id,
                document_id=doc.id,
                guild_id=guild.id,
                attached_by_id=creator.id,
            )
            session.add(link)
            ids.add("calendar_event_documents", {
                "calendar_event_id": event.id, "document_id": doc.id,
            })

        await session.flush()
        events[ed["title"]] = event

    return events


async def _create_property_definitions(
    session: AsyncSession,
    ids: IDTracker,
    initiative: Initiative,
    defn_defs: list[dict],
) -> dict[str, PropertyDefinition]:
    """Create property definitions on an initiative.

    Each ``defn_def`` has: name, type (PropertyType), position, color,
    options (list of {value, label, color}; required for select / multi_select).
    """
    defns: dict[str, PropertyDefinition] = {}
    for dd in defn_defs:
        defn = PropertyDefinition(
            initiative_id=initiative.id,
            name=dd["name"],
            type=dd["type"],
            position=float(dd.get("position", 0.0)),
            color=dd.get("color"),
            options=dd.get("options"),
        )
        session.add(defn)
        await session.flush()
        ids.add("property_definitions", defn.id)
        defns[dd["name"]] = defn
    return defns


# Mapping from PropertyType to the Value-model column that stores it.
# ``url`` / ``select`` reuse ``value_text`` because their wire format is a
# string; ``multi_select`` is stored as a JSON array in ``value_json``.
_PROPERTY_TYPE_TO_COLUMN = {
    PropertyType.text: "value_text",
    PropertyType.url: "value_text",
    PropertyType.select: "value_text",
    PropertyType.number: "value_number",
    PropertyType.checkbox: "value_boolean",
    PropertyType.date: "value_date",
    PropertyType.datetime: "value_datetime",
    PropertyType.user_reference: "value_user_id",
    PropertyType.multi_select: "value_json",
}


async def _attach_property_values(
    session: AsyncSession,
    ids: IDTracker,
    definition: PropertyDefinition,
    attachments: list[tuple[str, int, object]],
) -> None:
    """Attach typed values for one property definition across entities.

    ``attachments`` items are ``(entity_kind, entity_id, raw_value)`` where
    ``entity_kind`` is one of ``"task"``, ``"document"``, ``"event"``.
    The helper picks the right value model + typed column based on the
    definition's type. ``raw_value`` should already be in its native
    Python type (``str``, ``Decimal``, ``bool``, ``date``, ``datetime``,
    ``int`` for user_reference, ``list[str]`` for multi_select).
    """
    column_name = _PROPERTY_TYPE_TO_COLUMN[definition.type]
    for entity_kind, entity_id, raw_value in attachments:
        if entity_kind == "task":
            row = TaskPropertyValue(
                task_id=entity_id,
                property_id=definition.id,
            )
            id_bucket = "task_property_values"
            id_key = {"task_id": entity_id, "property_id": definition.id}
        elif entity_kind == "document":
            row = DocumentPropertyValue(
                document_id=entity_id,
                property_id=definition.id,
            )
            id_bucket = "document_property_values"
            id_key = {"document_id": entity_id, "property_id": definition.id}
        elif entity_kind == "event":
            row = CalendarEventPropertyValue(
                event_id=entity_id,
                property_id=definition.id,
            )
            id_bucket = "calendar_event_property_values"
            id_key = {"event_id": entity_id, "property_id": definition.id}
        else:
            raise ValueError(f"Unknown entity_kind {entity_kind!r}")
        setattr(row, column_name, raw_value)
        session.add(row)
        ids.add(id_bucket, id_key)
    await session.flush()


# ---------------------------------------------------------------------------
# Seed
# ---------------------------------------------------------------------------

async def seed() -> None:
    if _load_state() is not None:
        print("Seed data already exists (.vscode/.dev_seed_ids.json found).")
        print("  Run with --clean first to remove existing data.")
        return

    print("Seeding dev data (3 guilds, multiple users)...")
    ids = IDTracker()

    async with AdminSessionLocal() as session:
        # -- Discover existing entities --
        admin_user = await _find_superuser(session)
        primary_guild = await get_primary_guild(session)

        # ==============================================================
        # Users (all password: "changeme")
        # ==============================================================
        print("  Creating users...")
        new_users = await _create_users(session, ids, [
            {"email": "user1@example.com", "full_name": "Dungeon Master",
             "timezone": "America/New_York", "color_theme": "strahd", "week_starts_on": 1},
            {"email": "user2@example.com", "full_name": "Thorn Ironforge",
             "timezone": "America/Chicago", "color_theme": "kobold"},
            {"email": "user3@example.com", "full_name": "Elara Moonwhisper",
             "timezone": "Europe/London", "color_theme": "displacer", "week_starts_on": 1,
             "email_overdue_tasks": False, "push_overdue_tasks": False},
            {"email": "user4@example.com", "full_name": "Vex Shadowstep",
             "timezone": "America/Los_Angeles", "color_theme": "strahd",
             "email_task_assignment": False},
            {"email": "user5@example.com", "full_name": "Seraphina Dawnlight",
             "timezone": "Europe/Berlin", "color_theme": "kobold", "week_starts_on": 1},
            {"email": "user6@example.com", "full_name": "Finley Goldtongue",
             "timezone": "Asia/Tokyo", "color_theme": "displacer"},
            {"email": "user7@example.com", "full_name": "Kael Windrunner",
             "timezone": "Australia/Sydney", "color_theme": "kobold",
             "push_task_assignment": False, "push_overdue_tasks": False},
            {"email": "user8@example.com", "full_name": "Aurelia Brightshield",
             "timezone": "America/Denver", "color_theme": "strahd", "week_starts_on": 1},
        ])

        # Apply settings to the superuser too
        await _apply_user_settings(
            session, ids, admin_user,
            timezone="America/Los_Angeles",
            color_theme="kobold",
            week_starts_on=0,
        )

        # Make the admin user available by name too
        all_users: dict[str, User] = {"Admin User": admin_user, **new_users}

        dm = new_users["Dungeon Master"]
        thorn = new_users["Thorn Ironforge"]
        elara = new_users["Elara Moonwhisper"]
        vex = new_users["Vex Shadowstep"]
        sera = new_users["Seraphina Dawnlight"]
        finley = new_users["Finley Goldtongue"]
        kael = new_users["Kael Windrunner"]
        aurelia = new_users["Aurelia Brightshield"]

        # ==============================================================
        # GUILD 1: Primary guild — "Curse of Strahd" TTRPG campaign
        # (The primary guild already exists from init_db)
        # ==============================================================
        print("\n  --- Guild 1: Primary Guild (TTRPG Campaign) ---")
        g1 = primary_guild
        g1_id = g1.id

        # Commit the shared rows (users) so far, then route into the primary
        # guild's schema (search_path + SET ROLE) so all of its guild-scoped data
        # — initiatives, projects, tasks, ... — is created there, not in public.
        await session.commit()
        await set_rls_context(
            session, user_id=admin_user.id, guild_id=g1_id, guild_role="admin", is_superadmin=True
        )

        # Add members to primary guild
        await _add_guild_members(
            session, ids, g1,
            [dm, thorn, elara, vex, sera],
            admin_users=[dm],
        )

        # Look up the primary guild's "Default Initiative", creating it if it
        # doesn't exist (same approach as the guild 2/3 sections below).
        #
        # Why it can be missing: a dev database can end up with a
        # "Primary Guild" row in public.guilds but NO matching guild_1
        # schema (for example, the row was created before per-guild schemas
        # existed, or a cleanup was interrupted partway). On the next backend
        # startup, backfill_guild_schemas() creates the missing guild_1
        # schema — but it only creates the empty tables, it never inserts
        # rows. The result: guild_1.initiatives exists with zero rows, and
        # the previous code here (a SELECT followed by .one()) crashed with
        # NoResultFound.
        g1_default_init = await ensure_default_initiative(
            session, admin_user, guild_id=g1_id
        )
        # guild_1.guild_settings has the same gap: normally one row is
        # inserted when a guild is created, but a startup back-fill leaves
        # the table empty — create the row if it isn't there.
        await get_or_create_guild_settings(session, g1_id)

        # Add admin + DM as PM to default initiative
        for user in [dm]:
            result = await session.exec(
                select(InitiativeRoleModel).where(
                    InitiativeRoleModel.initiative_id == g1_default_init.id,
                    InitiativeRoleModel.name == "project_manager",
                )
            )
            pm_role = result.one()
            m = InitiativeMember(
                initiative_id=g1_default_init.id,
                user_id=user.id,
                guild_id=g1_id,
                role_id=pm_role.id,
            )
            session.add(m)
            ids.add("initiative_members", {
                "initiative_id": g1_default_init.id, "user_id": user.id,
            })
        await session.flush()

        # --- Initiative: Curse of Strahd ---
        g1_strahd, g1_strahd_pm, g1_strahd_mem = await _create_initiative(
            session, ids,
            guild=g1,
            name="Campaign: Curse of Strahd",
            description="A gothic horror adventure in the demiplane of Barovia",
            color="#7C3AED",
            pm_user=dm,
            member_users=[thorn, elara, vex, sera],
            queues_enabled=True,
            counters_enabled=True,
            events_enabled=True,
        )

        # --- Initiative: Lost Mine of Phandelver ---
        g1_lmop, g1_lmop_pm, g1_lmop_mem = await _create_initiative(
            session, ids,
            guild=g1,
            name="Campaign: Lost Mine of Phandelver",
            description="A classic introductory adventure in the Sword Coast",
            color="#059669",
            pm_user=admin_user,
            member_users=[dm, thorn, elara],
            queues_enabled=True,
            counters_enabled=True,
            events_enabled=True,
        )

        # -- Projects --
        print("  Creating Guild 1 projects...")

        g1_barovia = await _create_project(
            session, ids,
            guild=g1, initiative=g1_strahd,
            name="Barovia Arc",
            icon="\U0001F9DB",
            description="The main horror campaign storyline through Castle Ravenloft",
            owner=dm,
            write_users=[thorn, elara],
            read_users=[vex, sera],
        )

        g1_ravenloft = await _create_project(
            session, ids,
            guild=g1, initiative=g1_strahd,
            name="Castle Ravenloft",
            icon="\U0001F3F0",
            description="The final dungeon — Strahd's fortress atop the Pillarstone",
            owner=dm,
            write_users=[thorn],
        )

        g1_phandalin = await _create_project(
            session, ids,
            guild=g1, initiative=g1_lmop,
            name="Phandalin Adventures",
            icon="\u2694\uFE0F",
            description="Classic starter campaign in the Sword Coast region",
            owner=admin_user,
            write_users=[dm, thorn, elara],
        )

        g1_wave_echo = await _create_project(
            session, ids,
            guild=g1, initiative=g1_lmop,
            name="Wave Echo Cave",
            icon="\U0001F48E",
            description="The lost mine of Phandelver and the Forge of Spells",
            owner=admin_user,
            write_users=[dm],
            read_users=[thorn, elara],
        )

        g1_session_zero = await _create_project(
            session, ids,
            guild=g1, initiative=g1_default_init,
            name="Session Zero & Planning",
            icon="\U0001F4CB",
            description="Meta-campaign logistics and session planning",
            owner=dm,
            write_users=[admin_user],
        )

        g1_homebrew = await _create_project(
            session, ids,
            guild=g1, initiative=g1_default_init,
            name="Homebrew Rules",
            icon="\U0001F4DC",
            description="Custom house rules, variant options, and homebrew content",
            owner=dm,
            write_users=[admin_user, thorn],
        )

        g1_mega_dungeon = await _create_project(
            session, ids,
            guild=g1, initiative=g1_strahd,
            name="Mega Dungeon: Halls of the Dread Lord",
            icon="\U0001F3F0",
            description="A sprawling 200-room dungeon crawl beneath Castle Ravenloft. "
                        "Used to stress-test large task lists.",
            owner=dm,
            write_users=[admin_user, thorn, elara],
            read_users=[vex, sera],
        )

        # Task statuses
        print("  Creating Guild 1 task statuses...")
        g1_projects = [g1_barovia, g1_ravenloft, g1_phandalin, g1_wave_echo, g1_session_zero, g1_homebrew, g1_mega_dungeon]
        g1_status_maps: dict[int, dict[str, TaskStatus]] = {}
        for proj in g1_projects:
            statuses = await ensure_default_statuses(session, proj.id)
            cat_map = {}
            for s in statuses:
                cat_map[s.category] = s
                ids.add("task_statuses", s.id)
            g1_status_maps[proj.id] = cat_map
        await session.flush()

        # -- Tasks --
        print("  Creating Guild 1 tasks...")
        g1_task_defs = [
            # Barovia Arc
            {"project_id": g1_barovia.id, "title": "Defeat Strahd von Zarovich",
             "description": "The vampire lord must be destroyed to free Barovia from his curse.",
             "priority": TaskPriority.urgent, "category": TaskStatusCategory.backlog,
             "assignees": ["Thorn Ironforge", "Elara Moonwhisper"], "due_days": 30},
            {"project_id": g1_barovia.id, "title": "Survive the Death House",
             "description": "Navigate the haunted mansion on the outskirts of the Village of Barovia.",
             "priority": TaskPriority.high, "category": TaskStatusCategory.in_progress,
             "assignees": ["Dungeon Master"],
             "subtasks": ["Explore the basement", "Find the hidden altar", "Escape before the house collapses"]},
            {"project_id": g1_barovia.id, "title": "Find the Sunsword in the Amber Temple",
             "description": "The legendary weapon is key to defeating the Dark Lord.",
             "priority": TaskPriority.high, "category": TaskStatusCategory.todo, "due_days": 14,
             "assignees": ["Thorn Ironforge"]},
            {"project_id": g1_barovia.id, "title": "Negotiate with the Vistani caravan",
             "description": "The Vistani hold secrets about Strahd and safe passage through the mists.",
             "priority": TaskPriority.medium, "category": TaskStatusCategory.done,
             "assignees": ["Vex Shadowstep"]},
            {"project_id": g1_barovia.id, "title": "Retrieve the Tome of Strahd",
             "description": "The tome reveals Strahd's history and weaknesses.",
             "priority": TaskPriority.high, "category": TaskStatusCategory.todo,
             "assignees": ["Elara Moonwhisper"], "due_days": 7},
            {"project_id": g1_barovia.id, "title": "Ally with the werewolf pack",
             "description": "The werewolves of Barovia could be powerful allies against Strahd if convinced.",
             "priority": TaskPriority.low, "category": TaskStatusCategory.backlog},
            {"project_id": g1_barovia.id, "title": "Escort Ireena to Vallaki",
             "description": "Protect Ireena Kolyana from Strahd's minions on the road to Vallaki.",
             "priority": TaskPriority.urgent, "category": TaskStatusCategory.done,
             "assignees": ["Seraphina Dawnlight", "Thorn Ironforge"],
             "subtasks": ["Pack supplies for the journey", "Guard Ireena through the Svalich Woods",
                          "Arrive at Vallaki gates"]},
            # Castle Ravenloft
            {"project_id": g1_ravenloft.id, "title": "Map Castle Ravenloft's layout",
             "description": "Sketch out known rooms and passages for the final assault.",
             "priority": TaskPriority.high, "category": TaskStatusCategory.in_progress,
             "assignees": ["Dungeon Master"],
             "subtasks": ["Map the main floor", "Map the crypts", "Map the towers", "Map Strahd's tomb"]},
            {"project_id": g1_ravenloft.id, "title": "Disable the castle traps",
             "description": "Ravenloft is full of deadly traps protecting the vampire lord.",
             "priority": TaskPriority.medium, "category": TaskStatusCategory.todo,
             "assignees": ["Vex Shadowstep"]},
            {"project_id": g1_ravenloft.id, "title": "Find the Heart of Sorrow",
             "description": "The crystal heart protects Strahd and must be destroyed first.",
             "priority": TaskPriority.urgent, "category": TaskStatusCategory.backlog,
             "due_days": 21},
            # Phandalin Adventures
            {"project_id": g1_phandalin.id, "title": "Rescue Gundren Rockseeker",
             "description": "The dwarf was kidnapped on the road to Phandalin. Find him!",
             "priority": TaskPriority.urgent, "category": TaskStatusCategory.in_progress,
             "assignees": ["Admin User", "Thorn Ironforge"], "due_days": 3},
            {"project_id": g1_phandalin.id, "title": "Clear the Redbrand Hideout",
             "description": "The Redbrand ruffians terrorize Phandalin from their base under Tresendar Manor.",
             "priority": TaskPriority.high, "category": TaskStatusCategory.done,
             "assignees": ["Thorn Ironforge", "Elara Moonwhisper"]},
            {"project_id": g1_phandalin.id, "title": "Escort merchant supplies to Phandalin",
             "description": "Deliver the wagon of supplies safely along the Triboar Trail.",
             "priority": TaskPriority.medium, "category": TaskStatusCategory.done},
            {"project_id": g1_phandalin.id, "title": "Investigate the Cragmaw goblins",
             "description": "A tribe of goblins ambushed the party. Their hideout must be cleared.",
             "priority": TaskPriority.medium, "category": TaskStatusCategory.done,
             "subtasks": ["Find the Cragmaw Hideout", "Defeat Klarg the bugbear", "Free Sildar Hallwinter"],
             "subtasks_done": True},
            {"project_id": g1_phandalin.id, "title": "Talk to Halia Thornton at the Miner's Exchange",
             "description": "She may have intel about the Redbrands and the Black Spider.",
             "priority": TaskPriority.low, "category": TaskStatusCategory.todo,
             "assignees": ["Elara Moonwhisper"]},
            {"project_id": g1_phandalin.id, "title": "Visit Old Owl Well",
             "description": "Reports of undead activity near the old watchtower ruins.",
             "priority": TaskPriority.low, "category": TaskStatusCategory.backlog},
            # Wave Echo Cave
            {"project_id": g1_wave_echo.id, "title": "Defeat the Black Spider in Wave Echo Cave",
             "description": "Nezznar the Black Spider seeks the Forge of Spells.",
             "priority": TaskPriority.high, "category": TaskStatusCategory.backlog,
             "subtasks": ["Find the entrance to Wave Echo Cave", "Navigate the mine tunnels", "Confront Nezznar"],
             "due_days": 10},
            {"project_id": g1_wave_echo.id, "title": "Activate the Forge of Spells",
             "description": "The ancient dwarven forge could create powerful magic items.",
             "priority": TaskPriority.medium, "category": TaskStatusCategory.backlog,
             "assignees": ["Elara Moonwhisper"]},
            {"project_id": g1_wave_echo.id, "title": "Clear the undead miners",
             "description": "Ghosts and skeletons of the original miners still haunt the tunnels.",
             "priority": TaskPriority.medium, "category": TaskStatusCategory.todo,
             "assignees": ["Seraphina Dawnlight"]},
            # Session Zero & Planning
            {"project_id": g1_session_zero.id, "title": "Finalize character backstories",
             "description": "All players need to submit their character backstories before Session 1.",
             "priority": TaskPriority.medium, "category": TaskStatusCategory.done},
            {"project_id": g1_session_zero.id, "title": "Schedule Session 4",
             "description": "Find a date that works for all five players.",
             "priority": TaskPriority.low, "category": TaskStatusCategory.todo, "due_days": 5,
             "assignees": ["Dungeon Master"]},
            {"project_id": g1_session_zero.id, "title": "Review leveling rules for Tier 2",
             "description": "Characters approaching level 5 — review multiclassing and feat rules.",
             "priority": TaskPriority.low, "category": TaskStatusCategory.backlog},
            {"project_id": g1_session_zero.id, "title": "Prepare battle maps for next session",
             "description": "Print or prepare VTT maps for the upcoming dungeon crawl.",
             "priority": TaskPriority.medium, "category": TaskStatusCategory.in_progress,
             "assignees": ["Dungeon Master"], "due_days": 2},
            {"project_id": g1_session_zero.id, "title": "Order new dice set for the table",
             "description": "The group agreed to get matching dice for the campaign.",
             "priority": TaskPriority.low, "category": TaskStatusCategory.done},
            # Homebrew Rules
            {"project_id": g1_homebrew.id, "title": "Write critical hit tables",
             "description": "Custom critical hit effects for each damage type.",
             "priority": TaskPriority.medium, "category": TaskStatusCategory.in_progress,
             "assignees": ["Dungeon Master"],
             "subtasks": ["Slashing crits", "Piercing crits", "Bludgeoning crits",
                          "Fire crits", "Cold crits", "Lightning crits"]},
            {"project_id": g1_homebrew.id, "title": "Balance the Gunslinger subclass",
             "description": "Homebrew fighter subclass needs playtesting feedback.",
             "priority": TaskPriority.low, "category": TaskStatusCategory.todo,
             "assignees": ["Thorn Ironforge"]},
            {"project_id": g1_homebrew.id, "title": "Revise potion crafting rules",
             "description": "Current rules are too restrictive — allow crafting during short rests.",
             "priority": TaskPriority.medium, "category": TaskStatusCategory.done,
             "assignees": ["Admin User"]},
            # Mega Dungeon — 200 rooms generated programmatically
            *_generate_mega_dungeon_tasks(g1_mega_dungeon.id),
        ]

        g1_tasks: dict[str, Task] = {}
        for proj in g1_projects:
            proj_tasks = [td for td in g1_task_defs if td["project_id"] == proj.id]
            tasks = await _create_tasks(
                session, ids,
                guild=g1,
                status_map=g1_status_maps[proj.id],
                task_defs=proj_tasks,
                all_users=all_users,
            )
            g1_tasks.update(tasks)

        # -- Tags --
        print("  Creating Guild 1 tags...")
        g1_tags = await _create_tags(session, ids, g1, [
            ("quest", "#EF4444"),
            ("NPC", "#8B5CF6"),
            ("lore", "#F59E0B"),
            ("combat", "#DC2626"),
            ("roleplay", "#3B82F6"),
            ("exploration", "#10B981"),
            ("puzzle", "#F97316"),
            ("boss fight", "#991B1B"),
            ("side quest", "#6366F1"),
            ("items/loot", "#D97706"),
        ])

        await _link_task_tags(session, ids, g1_tasks, g1_tags, [
            ("Defeat Strahd von Zarovich", ["quest", "combat", "boss fight"]),
            ("Survive the Death House", ["quest", "combat", "exploration"]),
            ("Find the Sunsword in the Amber Temple", ["quest", "lore", "items/loot"]),
            ("Negotiate with the Vistani caravan", ["NPC", "roleplay"]),
            ("Retrieve the Tome of Strahd", ["quest", "lore", "items/loot"]),
            ("Escort Ireena to Vallaki", ["quest", "NPC", "roleplay"]),
            ("Map Castle Ravenloft's layout", ["exploration", "puzzle"]),
            ("Find the Heart of Sorrow", ["quest", "boss fight"]),
            ("Rescue Gundren Rockseeker", ["quest", "NPC"]),
            ("Clear the Redbrand Hideout", ["quest", "combat"]),
            ("Investigate the Cragmaw goblins", ["quest", "combat", "exploration"]),
            ("Defeat the Black Spider in Wave Echo Cave", ["quest", "combat", "boss fight"]),
            ("Activate the Forge of Spells", ["lore", "items/loot", "puzzle"]),
            ("Write critical hit tables", ["combat"]),
            ("Balance the Gunslinger subclass", ["combat"]),
        ])

        await _link_project_tags(session, ids, g1_tags, [
            (g1_barovia.id, ["combat", "lore", "quest"]),
            (g1_ravenloft.id, ["combat", "exploration", "boss fight"]),
            (g1_phandalin.id, ["quest", "NPC"]),
            (g1_wave_echo.id, ["quest", "exploration", "items/loot"]),
            (g1_session_zero.id, ["roleplay"]),
            (g1_homebrew.id, ["combat", "items/loot"]),
        ])

        # -- Documents --
        print("  Creating Guild 1 documents...")
        g1_docs = await _create_documents(session, ids, guild=g1, all_users=all_users, doc_defs=[
            {
                "initiative_id": g1_strahd.id,
                "title": "Campaign Setting: The Land of Barovia",
                "creator": "Dungeon Master",
                "writers": ["Admin User"],
                "readers": ["Thorn Ironforge", "Elara Moonwhisper"],
                "paragraphs": [
                    "Barovia is a demiplane of dread, shrouded in perpetual mist. "
                    "The land is ruled by Count Strahd von Zarovich, a vampire lord "
                    "who has cursed this realm for centuries.",
                    "No one enters or leaves without Strahd's permission. The sun never "
                    "truly shines here, and the people live in constant fear of the "
                    "creatures that stalk the night.",
                    "Key locations: Village of Barovia, Vallaki, Krezk, the Amber Temple, "
                    "Castle Ravenloft, Old Bonegrinder, Argynvostholt, and Yester Hill.",
                ],
            },
            {
                "initiative_id": g1_strahd.id,
                "title": "NPC Roster: Curse of Strahd",
                "creator": "Dungeon Master",
                "paragraphs": [
                    "Strahd von Zarovich — The vampire lord of Barovia. Ancient, cunning, and tragically cursed.",
                    "Ireena Kolyana — Adopted daughter of the burgomaster. Strahd believes she is Tatyana reborn.",
                    "Ismark the Lesser — Ireena's brother, desperate to protect her.",
                    "Madam Eva — Vistani seer who reads the party's fortune with the Tarokka deck.",
                    "Kasimir Velikov — Dusk elf mage who seeks to resurrect his sister from the Amber Temple.",
                    "Ezmerelda d'Avenir — Monster hunter and Van Richten's former protege.",
                ],
            },
            {
                "initiative_id": g1_lmop.id,
                "title": "NPC Compendium: Phandelver",
                "creator": "Admin User",
                "writers": ["Dungeon Master"],
                "paragraphs": [
                    "Key NPCs: Gundren Rockseeker (quest giver), Sildar Hallwinter (Lords' Alliance agent), "
                    "Sister Garaele (Harper contact in Phandalin), Nezznar the Black Spider (main antagonist), "
                    "Glasstaff/Iarno Albrek (Redbrand leader).",
                    "Phandalin Townfolk: Toblen Stonehill (innkeeper), Elmar Barthen (merchant), "
                    "Linene Graywind (Lionshield Coster), Harbin Wester (cowardly townmaster).",
                ],
            },
            {
                "initiative_id": g1_default_init.id,
                "title": "Session 1 Recap: Into the Mists",
                "creator": "Dungeon Master",
                "readers": ["Thorn Ironforge", "Elara Moonwhisper", "Vex Shadowstep", "Seraphina Dawnlight"],
                "paragraphs": [
                    "The party received a mysterious letter and traveled to the village of Barovia. "
                    "After surviving the Death House, they met Ismark and Ireena.",
                    "The session ended with the party heading toward the church in the village center. "
                    "Next session: travel to Vallaki.",
                ],
            },
            {
                "initiative_id": g1_default_init.id,
                "title": "Session 2 Recap: The Road to Vallaki",
                "creator": "Dungeon Master",
                "paragraphs": [
                    "The party escorted Ireena through the Svalich Woods, fighting off dire wolves. "
                    "They discovered the windmill at Old Bonegrinder was inhabited by night hags.",
                    "Arrived at Vallaki and met Baron Vargas Vallakovich, who insists that 'All Will Be Well.'",
                ],
            },
            {
                "initiative_id": g1_default_init.id,
                "title": "Session 3 Recap: Festival of the Blazing Sun",
                "creator": "Dungeon Master",
                "paragraphs": [
                    "The Baron's festival went horribly wrong. The wicker sun failed to light, and the "
                    "crowd nearly rioted. The party intervened to prevent bloodshed.",
                    "Vex discovered a secret stash of bones beneath St. Andral's church. "
                    "A vampire spawn attacked during the night.",
                ],
            },
            {
                "initiative_id": g1_strahd.id,
                "title": "Tarokka Card Reading Results",
                "creator": "Dungeon Master",
                "paragraphs": [
                    "The Tome of Strahd: Look for a wizard's tower on a lake (Van Richten's Tower).",
                    "The Holy Symbol of Ravenkind: In a castle of bones (Argynvostholt).",
                    "The Sunsword: A fallen temple of amber (Amber Temple).",
                    "Strahd's Enemy: A young woman who has lost her family (Ezmerelda).",
                    "Strahd's Location: The heart of his castle — the throne room.",
                ],
            },
            {
                "initiative_id": g1_default_init.id,
                "title": "House Rules v2",
                "creator": "Dungeon Master",
                "writers": ["Admin User"],
                "paragraphs": [
                    "1. Critical hits: Roll damage dice twice plus modifiers (no doubling modifiers).",
                    "2. Potions: Drinking a potion is a bonus action. Feeding one to another is an action.",
                    "3. Inspiration: Can be given to other players. Max 1 at a time.",
                    "4. Death saves: Hidden from other players unless Medicine check DC 10.",
                    "5. Flanking: +2 bonus instead of advantage.",
                ],
            },
        ])

        await _link_doc_projects(session, ids, g1, [
            (g1_barovia.id, g1_docs["Campaign Setting: The Land of Barovia"].id, dm),
            (g1_barovia.id, g1_docs["NPC Roster: Curse of Strahd"].id, dm),
            (g1_barovia.id, g1_docs["Tarokka Card Reading Results"].id, dm),
            (g1_phandalin.id, g1_docs["NPC Compendium: Phandelver"].id, admin_user),
            (g1_session_zero.id, g1_docs["Session 1 Recap: Into the Mists"].id, dm),
            (g1_session_zero.id, g1_docs["Session 2 Recap: The Road to Vallaki"].id, dm),
            (g1_session_zero.id, g1_docs["Session 3 Recap: Festival of the Blazing Sun"].id, dm),
            (g1_homebrew.id, g1_docs["House Rules v2"].id, dm),
        ])

        await _link_doc_tags(session, ids, g1_docs, g1_tags, [
            ("Campaign Setting: The Land of Barovia", ["lore"]),
            ("NPC Roster: Curse of Strahd", ["NPC", "lore"]),
            ("NPC Compendium: Phandelver", ["NPC"]),
            ("Tarokka Card Reading Results", ["lore", "items/loot"]),
            ("House Rules v2", ["combat"]),
        ])

        # -- Comments --
        print("  Creating Guild 1 comments...")
        await _create_comments(session, ids, g1, [
            {"author": "Thorn Ironforge", "task_title": "Defeat Strahd von Zarovich",
             "content": "We need the Sunsword AND the Holy Symbol before attempting this."},
            {"author": "Elara Moonwhisper", "task_title": "Defeat Strahd von Zarovich",
             "content": "I can prepare Daylight and Greater Restoration. We should also stock up on holy water."},
            {"author": "Dungeon Master", "task_title": "Defeat Strahd von Zarovich",
             "content": "Remember: Strahd can retreat to his coffin. You need to find it first."},
            {"author": "Admin User", "task_title": "Rescue Gundren Rockseeker",
             "content": "Last seen heading to Cragmaw Castle with the map."},
            {"author": "Thorn Ironforge", "task_title": "Clear the Redbrand Hideout",
             "content": "Completed! The party found Glasstaff's letters from the Black Spider."},
            {"author": "Vex Shadowstep", "task_title": "Disable the castle traps",
             "content": "I'll need thieves' tools and a lot of patience. DC 15+ on most of these."},
            {"author": "Seraphina Dawnlight", "task_title": "Find the Heart of Sorrow",
             "content": "The crystal heart is somewhere high in the castle towers. I can sense its dark energy."},
            {"author": "Dungeon Master", "task_title": "Write critical hit tables",
             "content": "Playtest feedback from session 2: slashing crits feel too strong at low levels."},
            {"author": "Dungeon Master", "doc_title": "Campaign Setting: The Land of Barovia",
             "content": "Don't forget \u2014 Barovia is a demiplane, no escape without defeating Strahd."},
            {"author": "Elara Moonwhisper", "doc_title": "Tarokka Card Reading Results",
             "content": "We should head to the Amber Temple first. The Sunsword is our highest priority."},
        ], g1_tasks, g1_docs, all_users)

        # -- Favorites & Recent Views --
        print("  Creating Guild 1 favorites & views...")
        await _create_favorites(session, ids, g1, [
            (dm, g1_barovia), (dm, g1_ravenloft), (dm, g1_session_zero),
            (thorn, g1_barovia), (thorn, g1_phandalin),
            (elara, g1_barovia), (elara, g1_wave_echo),
            (vex, g1_ravenloft),
            (sera, g1_barovia),
            (admin_user, g1_phandalin), (admin_user, g1_wave_echo),
        ])
        await _create_recent_views(session, ids, g1, [
            (dm, g1_barovia), (dm, g1_ravenloft), (dm, g1_session_zero),
            (dm, g1_homebrew),
            (thorn, g1_barovia), (thorn, g1_phandalin),
            (elara, g1_barovia), (elara, g1_wave_echo),
            (admin_user, g1_phandalin), (admin_user, g1_session_zero),
        ])

        # -- Document Links (wikilinks) --
        print("  Creating Guild 1 document links...")
        await _create_document_links(session, ids, g1, g1_docs, [
            ("Session 1 Recap: Into the Mists", "Campaign Setting: The Land of Barovia"),
            ("Session 1 Recap: Into the Mists", "NPC Roster: Curse of Strahd"),
            ("Session 2 Recap: The Road to Vallaki", "Campaign Setting: The Land of Barovia"),
            ("Session 2 Recap: The Road to Vallaki", "NPC Roster: Curse of Strahd"),
            ("Session 3 Recap: Festival of the Blazing Sun", "NPC Roster: Curse of Strahd"),
            ("Tarokka Card Reading Results", "Campaign Setting: The Land of Barovia"),
            ("NPC Roster: Curse of Strahd", "Campaign Setting: The Land of Barovia"),
            ("House Rules v2", "Session 1 Recap: Into the Mists"),
        ])

        # -- Queues --
        print("  Creating Guild 1 queues...")
        await _create_queues(session, ids, g1, all_users, g1_tags, [
            {
                "initiative_id": g1_strahd.id,
                "name": "Death House Encounter",
                "description": "Combat encounter in the haunted Death House basement",
                "created_by": "Dungeon Master",
                "is_active": True,
                "current_round": 3,
                "write_users": ["Thorn Ironforge", "Elara Moonwhisper"],
                "active_item_label": "Thorn Ironforge",
                "items": [
                    {"label": "Thorn Ironforge", "position": 22, "user": "Thorn Ironforge",
                     "color": "#DC2626", "notes": "Raging — advantage on Str checks",
                     "tags": ["combat"]},
                    {"label": "Elara Moonwhisper", "position": 19, "user": "Elara Moonwhisper",
                     "color": "#3B82F6", "notes": "Concentration: Spirit Guardians",
                     "tags": ["combat"]},
                    {"label": "Shambling Mound", "position": 17,
                     "color": "#10B981", "notes": "HP: 136/136",
                     "tags": ["combat", "boss fight"]},
                    {"label": "Vex Shadowstep", "position": 16, "user": "Vex Shadowstep",
                     "color": "#8B5CF6", "notes": "Hidden — bonus action stealth",
                     "tags": ["combat"]},
                    {"label": "Seraphina Dawnlight", "position": 12, "user": "Seraphina Dawnlight",
                     "color": "#F59E0B", "tags": ["combat"]},
                    {"label": "Shadow #1", "position": 9, "color": "#374151",
                     "notes": "HP: 16/16"},
                    {"label": "Shadow #2", "position": 5, "color": "#374151",
                     "notes": "HP: 16/16"},
                    {"label": "Shadow #3", "position": 3, "color": "#374151",
                     "is_visible": False, "notes": "Surprise round — not yet revealed"},
                ],
            },
            {
                "initiative_id": g1_strahd.id,
                "name": "Vallaki Town Square Ambush",
                "description": "Strahd's wolves attack during the Festival of the Blazing Sun",
                "created_by": "Dungeon Master",
                "is_active": False,
                "current_round": 1,
                "write_users": ["Thorn Ironforge"],
                "items": [
                    {"label": "Dire Wolf Alpha", "position": 20,
                     "color": "#6B7280", "notes": "Pack leader — AC 14, HP: 37",
                     "tags": ["combat"]},
                    {"label": "Thorn Ironforge", "position": 18, "user": "Thorn Ironforge",
                     "color": "#DC2626"},
                    {"label": "Elara Moonwhisper", "position": 15, "user": "Elara Moonwhisper",
                     "color": "#3B82F6"},
                    {"label": "Wolf Pack (x4)", "position": 13,
                     "color": "#9CA3AF", "notes": "HP: 11 each"},
                    {"label": "Vex Shadowstep", "position": 11, "user": "Vex Shadowstep",
                     "color": "#8B5CF6"},
                    {"label": "Seraphina Dawnlight", "position": 8, "user": "Seraphina Dawnlight",
                     "color": "#F59E0B"},
                ],
            },
            {
                "initiative_id": g1_lmop.id,
                "name": "Cragmaw Hideout Assault",
                "description": "The party storms the goblin cave to rescue Sildar Hallwinter",
                "created_by": "Admin User",
                "is_active": False,
                "current_round": 5,
                "write_users": ["Dungeon Master", "Thorn Ironforge", "Elara Moonwhisper"],
                "items": [
                    {"label": "Admin User (Ranger)", "position": 21, "user": "Admin User",
                     "color": "#059669", "notes": "Hunter's Mark on Klarg"},
                    {"label": "Thorn Ironforge", "position": 18, "user": "Thorn Ironforge",
                     "color": "#DC2626"},
                    {"label": "Klarg the Bugbear", "position": 15,
                     "color": "#B91C1C", "notes": "HP: 27/27 — boss",
                     "tags": ["combat", "boss fight"]},
                    {"label": "Elara Moonwhisper", "position": 14, "user": "Elara Moonwhisper",
                     "color": "#3B82F6"},
                    {"label": "Goblin Archer #1", "position": 10,
                     "color": "#65A30D", "notes": "HP: 7/7"},
                    {"label": "Goblin Archer #2", "position": 7,
                     "color": "#65A30D", "notes": "HP: 7/7"},
                    {"label": "Ripper (Wolf)", "position": 4,
                     "color": "#78716C", "notes": "HP: 11/11 — Klarg's pet"},
                ],
            },
        ])

        # Enable queue visibility for members in initiatives that have queues
        await _enable_queue_permissions(
            session, [g1_strahd_mem, g1_lmop_mem],
        )

        # -- Counters --
        print("  Creating Guild 1 counter groups...")
        await _create_counter_groups(session, ids, g1, all_users, [
            {
                "initiative_id": g1_strahd.id,
                "name": "Party Vitals (Strahd)",
                "description": "Combat-relevant counters for the Curse of Strahd party.",
                "created_by": "Dungeon Master",
                "role_grants": [{"role_id": g1_strahd_mem.id, "level": CounterPermissionLevel.write}],
                "counters": [
                    {"name": "Thorn HP", "color": "#DC2626", "count": 38, "min": 0, "max": 42,
                     "step": 1, "initial_count": 42, "view_mode": CounterViewMode.progress_bar, "position": 1},
                    {"name": "Elara HP", "color": "#3B82F6", "count": 24, "min": 0, "max": 28,
                     "step": 1, "initial_count": 28, "view_mode": CounterViewMode.progress_bar, "position": 2},
                    {"name": "Inspiration Pool", "color": "#F59E0B", "count": 2, "min": 0, "max": 5,
                     "step": 1, "initial_count": 0, "view_mode": CounterViewMode.number, "position": 3},
                    {"name": "Long Rest Clock", "color": "#7C3AED", "count": 3, "min": 0, "max": 8,
                     "step": 1, "initial_count": 0, "view_mode": CounterViewMode.segmented_clock, "position": 4},
                ],
            },
            {
                "initiative_id": g1_strahd.id,
                "name": "Castle Ravenloft Doom Clock",
                "description": "Strahd's awareness of the party. At 8 he comes for them.",
                "created_by": "Dungeon Master",
                "counters": [
                    {"name": "Strahd's Awareness", "color": "#991B1B", "count": 4, "min": 0, "max": 8,
                     "step": 1, "initial_count": 0, "view_mode": CounterViewMode.segmented_clock, "position": 1},
                    {"name": "Holy Symbols Found", "color": "#FBBF24", "count": 2, "min": 0, "max": 3,
                     "step": 1, "initial_count": 0, "view_mode": CounterViewMode.number, "position": 2},
                    {"name": "Tarokka Cards Drawn", "color": "#A855F7", "count": 3, "min": 0, "max": 5,
                     "step": 1, "initial_count": 0, "view_mode": CounterViewMode.number, "position": 3},
                ],
            },
            {
                "initiative_id": g1_lmop.id,
                "name": "Phandelver Reputation",
                "description": "Faction standing for the Lost Mine of Phandelver party.",
                "created_by": "Admin User",
                "counters": [
                    {"name": "Phandalin Reputation", "color": "#10B981", "count": 3, "min": -5, "max": 10,
                     "step": 1, "initial_count": 0, "view_mode": CounterViewMode.number, "position": 1},
                    {"name": "Redbrand Hideout Cleared", "color": "#DC2626", "count": 4, "min": 0, "max": 6,
                     "step": 1, "initial_count": 0, "view_mode": CounterViewMode.progress_bar, "position": 2},
                ],
            },
        ])
        await _enable_role_feature(session, [g1_strahd_mem, g1_lmop_mem], "counters_enabled")

        # -- Calendar events --
        print("  Creating Guild 1 calendar events...")
        g1_events = await _create_calendar_events(session, ids, g1, all_users, g1_tags, g1_docs, [
            {
                "initiative_id": g1_strahd.id,
                "title": "Session 12: Into the Amber Temple",
                "description": "The party finally reaches the Amber Temple to bargain with the Dark Powers.",
                "location": "Tabletop @ DM's house",
                "start_at": NOW + timedelta(days=2, hours=2),
                "end_at": NOW + timedelta(days=2, hours=6),
                "color": "#7C3AED",
                "created_by": "Dungeon Master",
                "attendees": [
                    {"user": "Dungeon Master", "rsvp_status": RSVPStatus.accepted},
                    {"user": "Thorn Ironforge", "rsvp_status": RSVPStatus.accepted},
                    {"user": "Elara Moonwhisper", "rsvp_status": RSVPStatus.accepted},
                    {"user": "Vex Shadowstep", "rsvp_status": RSVPStatus.tentative},
                    {"user": "Seraphina Dawnlight", "rsvp_status": RSVPStatus.pending},
                ],
                "tags": ["quest", "lore"],
                "documents": ["NPC Roster: Curse of Strahd"],
            },
            {
                "initiative_id": g1_strahd.id,
                "title": "Weekly Strahd Session",
                "description": "Standing campaign night.",
                "location": "Roll20",
                "start_at": NOW + timedelta(days=7, hours=1),
                "end_at": NOW + timedelta(days=7, hours=5),
                "color": "#7C3AED",
                "created_by": "Dungeon Master",
                "recurrence": {
                    "frequency": "weekly", "interval": 1,
                    "weekdays": ["fr"], "ends": "after_occurrences",
                    "end_after_occurrences": 12,
                },
                "attendees": [
                    {"user": "Dungeon Master", "rsvp_status": RSVPStatus.accepted},
                    {"user": "Thorn Ironforge", "rsvp_status": RSVPStatus.accepted},
                    {"user": "Elara Moonwhisper", "rsvp_status": RSVPStatus.accepted},
                ],
            },
            {
                "initiative_id": g1_strahd.id,
                "title": "Player Off-Site Retrospective",
                "description": "All-day session: replay session 8-11 with snacks.",
                "location": "Cabin in the woods",
                "start_at": NOW + timedelta(days=14),
                "end_at": NOW + timedelta(days=14),
                "all_day": True,
                "color": "#059669",
                "created_by": "Dungeon Master",
                "tags": ["roleplay"],
            },
            {
                "initiative_id": g1_strahd.id,
                "title": "Session 11: Vallaki Festival",
                "description": "Wrapped up: the Festival of the Blazing Sun.",
                "location": "Tabletop @ DM's house",
                "start_at": NOW - timedelta(days=5, hours=22),
                "end_at": NOW - timedelta(days=5, hours=18),
                "color": "#7C3AED",
                "created_by": "Dungeon Master",
                "attendees": [
                    {"user": "Dungeon Master", "rsvp_status": RSVPStatus.accepted},
                    {"user": "Thorn Ironforge", "rsvp_status": RSVPStatus.accepted},
                ],
            },
            {
                "initiative_id": g1_lmop.id,
                "title": "Session: Cragmaw Hideout",
                "description": "Rescue Gundren Rockseeker from the goblins.",
                "location": "Roll20",
                "start_at": NOW + timedelta(days=4, hours=3),
                "end_at": NOW + timedelta(days=4, hours=7),
                "color": "#059669",
                "created_by": "Admin User",
                "attendees": [
                    {"user": "Admin User", "rsvp_status": RSVPStatus.accepted},
                    {"user": "Dungeon Master", "rsvp_status": RSVPStatus.tentative},
                ],
                "tags": ["combat", "quest"],
            },
            {
                "initiative_id": g1_lmop.id,
                "title": "Prep: Wave Echo Cave maps",
                "description": "DM-only prep slot for the finale dungeon.",
                "start_at": NOW + timedelta(days=10, hours=20),
                "end_at": NOW + timedelta(days=10, hours=22),
                "color": "#6B7280",
                "created_by": "Admin User",
            },
        ])
        await _enable_role_feature(session, [g1_strahd_mem, g1_lmop_mem], "events_enabled")

        # -- Custom properties --
        print("  Creating Guild 1 property definitions + values...")
        g1_strahd_props = await _create_property_definitions(session, ids, g1_strahd, [
            {"name": "Difficulty", "type": PropertyType.select, "position": 1.0, "color": "#DC2626",
             "options": [
                 {"value": "trivial", "label": "Trivial", "color": "#10B981"},
                 {"value": "moderate", "label": "Moderate", "color": "#F59E0B"},
                 {"value": "hard", "label": "Hard", "color": "#DC2626"},
                 {"value": "deadly", "label": "Deadly", "color": "#7F1D1D"},
             ]},
            {"name": "XP Reward", "type": PropertyType.number, "position": 2.0, "color": "#F59E0B"},
            {"name": "Prep Notes", "type": PropertyType.text, "position": 3.0},
            {"name": "Themes", "type": PropertyType.multi_select, "position": 4.0,
             "options": [
                 {"value": "horror", "label": "Horror", "color": "#7F1D1D"},
                 {"value": "investigation", "label": "Investigation", "color": "#3B82F6"},
                 {"value": "social", "label": "Social", "color": "#10B981"},
                 {"value": "combat", "label": "Combat", "color": "#DC2626"},
             ]},
            {"name": "Deadline", "type": PropertyType.date, "position": 5.0},
            {"name": "Owner", "type": PropertyType.user_reference, "position": 6.0, "color": "#8B5CF6"},
            {"name": "Public Knowledge", "type": PropertyType.checkbox, "position": 7.0},
        ])

        # Property values on a handful of known-titled tasks / docs.
        t_defeat_id = g1_tasks["Defeat Strahd von Zarovich"].id
        t_death_id = g1_tasks["Survive the Death House"].id
        doc_setting_id = g1_docs["Campaign Setting: The Land of Barovia"].id
        doc_npcs_id = g1_docs["NPC Roster: Curse of Strahd"].id

        await _attach_property_values(session, ids, g1_strahd_props["Difficulty"], [
            ("task", t_defeat_id, "deadly"),
            ("task", t_death_id, "hard"),
        ])
        await _attach_property_values(session, ids, g1_strahd_props["XP Reward"], [
            ("task", t_defeat_id, Decimal("50000")),
            ("task", t_death_id, Decimal("4500")),
        ])
        await _attach_property_values(session, ids, g1_strahd_props["Themes"], [
            ("task", t_defeat_id, ["horror", "combat"]),
            ("task", t_death_id, ["horror", "investigation"]),
        ])
        await _attach_property_values(session, ids, g1_strahd_props["Public Knowledge"], [
            ("document", doc_setting_id, True),
            ("document", doc_npcs_id, False),
        ])
        await _attach_property_values(session, ids, g1_strahd_props["Owner"], [
            ("task", t_defeat_id, dm.id),
        ])
        await _attach_property_values(session, ids, g1_strahd_props["Deadline"], [
            ("task", t_defeat_id, (NOW + timedelta(days=30)).date()),
        ])
        # Calendar event values — exercise the third value table.
        await _attach_property_values(session, ids, g1_strahd_props["Difficulty"], [
            ("event", g1_events["Session 12: Into the Amber Temple"].id, "deadly"),
            ("event", g1_events["Session 11: Vallaki Festival"].id, "moderate"),
        ])
        await _attach_property_values(session, ids, g1_strahd_props["Themes"], [
            ("event", g1_events["Session 12: Into the Amber Temple"].id,
             ["horror", "investigation"]),
        ])
        await _attach_property_values(session, ids, g1_strahd_props["Owner"], [
            ("event", g1_events["Weekly Strahd Session"].id, dm.id),
        ])

        g1_lmop_props = await _create_property_definitions(session, ids, g1_lmop, [
            {"name": "Hook", "type": PropertyType.text, "position": 1.0},
            {"name": "Quest Giver", "type": PropertyType.user_reference, "position": 2.0},
            {"name": "Map Link", "type": PropertyType.url, "position": 3.0, "color": "#3B82F6"},
        ])
        await _attach_property_values(session, ids, g1_lmop_props["Map Link"], [
            ("document", g1_docs["NPC Compendium: Phandelver"].id,
             "https://example.com/maps/lmop-overview"),
        ])

        # ==============================================================
        # GUILD 2: "Starforge Collective" — Sci-Fi Campaign
        # ==============================================================
        print("\n  --- Guild 2: Starforge Collective (Sci-Fi) ---")

        g2 = await _create_guild(
            session, ids,
            name="Starforge Collective",
            description="A science fiction tabletop campaign set in the far reaches of the galaxy",
            creator=admin_user,
        )
        g2_id = g2.id

        # Commit the new guild's shared rows (also flushes guild 1's data), then
        # provision its schema and route into it before creating its content.
        await session.commit()
        _expunge_guild_scoped(session)  # clear guild 1's per-schema ids from the identity map
        await provision_guild(g2_id)
        await set_rls_context(
            session, user_id=admin_user.id, guild_id=g2_id, guild_role="admin", is_superadmin=True
        )

        await _add_guild_members(
            session, ids, g2,
            [finley, kael, aurelia, vex, elara],
            admin_users=[finley],
        )

        # Default initiative for g2
        g2_default_init = await ensure_default_initiative(session, admin_user, guild_id=g2_id)
        # Track the roles and members that ensure_default_initiative created
        result = await session.exec(
            select(InitiativeRoleModel).where(
                InitiativeRoleModel.initiative_id == g2_default_init.id,
            )
        )
        for role in result.all():
            ids.add("initiative_roles", role.id)
            perms_result = await session.exec(
                select(InitiativeRolePermission).where(
                    InitiativeRolePermission.initiative_role_id == role.id
                )
            )
            for perm in perms_result.all():
                ids.add("initiative_role_permissions", {
                    "initiative_role_id": perm.initiative_role_id,
                    "permission_key": perm.permission_key,
                })

        ids.add("initiatives", g2_default_init.id)

        # Add members to default initiative
        result = await session.exec(
            select(InitiativeRoleModel).where(
                InitiativeRoleModel.initiative_id == g2_default_init.id,
                InitiativeRoleModel.name == "member",
            )
        )
        g2_def_member_role = result.one()
        for user in [finley, kael]:
            m = InitiativeMember(
                initiative_id=g2_default_init.id,
                user_id=user.id,
                guild_id=g2_id,
                role_id=g2_def_member_role.id,
            )
            session.add(m)
            ids.add("initiative_members", {
                "initiative_id": g2_default_init.id, "user_id": user.id,
            })
        await session.flush()

        g2_main, g2_main_pm, g2_main_mem = await _create_initiative(
            session, ids,
            guild=g2,
            name="Starfall: The Exodus Protocol",
            description="Humanity's last fleet searches for a new homeworld after Earth's collapse",
            color="#0EA5E9",
            pm_user=admin_user,
            member_users=[finley, kael, aurelia, vex, elara],
            queues_enabled=True,
            counters_enabled=True,
            events_enabled=True,
        )

        g2_side, g2_side_pm, g2_side_mem = await _create_initiative(
            session, ids,
            guild=g2,
            name="Side Missions: Fringe Space",
            description="One-shots and side adventures in the frontier sectors",
            color="#F59E0B",
            pm_user=finley,
            member_users=[kael, aurelia, vex],
            queues_enabled=True,
            counters_enabled=True,
            events_enabled=True,
        )

        # Projects
        print("  Creating Guild 2 projects...")
        g2_exodus = await _create_project(
            session, ids,
            guild=g2, initiative=g2_main,
            name="The Exodus Fleet",
            icon="\U0001F680",
            description="Managing the fleet's journey across the void between stars",
            owner=admin_user,
            write_users=[finley, kael],
            read_users=[aurelia, vex, elara],
        )

        g2_colony = await _create_project(
            session, ids,
            guild=g2, initiative=g2_main,
            name="Colony Alpha",
            icon="\U0001F30D",
            description="Establishing the first settlement on the candidate planet",
            owner=admin_user,
            write_users=[finley, aurelia],
        )

        g2_fringe = await _create_project(
            session, ids,
            guild=g2, initiative=g2_side,
            name="Smuggler's Run",
            icon="\U0001F4B0",
            description="A one-shot heist adventure on a derelict space station",
            owner=finley,
            write_users=[kael, vex],
        )

        g2_engineering = await _create_project(
            session, ids,
            guild=g2, initiative=g2_main,
            name="Engineering Bay",
            icon="\U0001F527",
            description="Ship upgrades, tech research, and equipment management",
            owner=kael,
            write_users=[admin_user, elara],
        )

        g2_planning = await _create_project(
            session, ids,
            guild=g2, initiative=g2_default_init,
            name="Campaign Planning",
            icon="\U0001F4C5",
            description="Session scheduling and campaign logistics",
            owner=admin_user,
            write_users=[finley],
        )

        # Task statuses
        g2_projects = [g2_exodus, g2_colony, g2_fringe, g2_engineering, g2_planning]
        g2_status_maps: dict[int, dict[str, TaskStatus]] = {}
        for proj in g2_projects:
            statuses = await ensure_default_statuses(session, proj.id)
            cat_map = {}
            for s in statuses:
                cat_map[s.category] = s
                ids.add("task_statuses", s.id)
            g2_status_maps[proj.id] = cat_map
        await session.flush()

        # Tasks
        print("  Creating Guild 2 tasks...")
        g2_task_defs = [
            # Exodus Fleet
            {"project_id": g2_exodus.id, "title": "Repair the FTL drive core",
             "description": "The main drive is failing. Without repairs, the fleet is stranded.",
             "priority": TaskPriority.urgent, "category": TaskStatusCategory.in_progress,
             "assignees": ["Kael Windrunner"],
             "subtasks": ["Diagnose the plasma leak", "Source replacement crystals", "Recalibrate the nav array"],
             "due_days": 2},
            {"project_id": g2_exodus.id, "title": "Investigate the distress signal from Sector 7G",
             "description": "An automated distress beacon is broadcasting from an uncharted system.",
             "priority": TaskPriority.high, "category": TaskStatusCategory.todo,
             "assignees": ["Aurelia Brightshield", "Vex Shadowstep"], "due_days": 7},
            {"project_id": g2_exodus.id, "title": "Negotiate passage through Krellix space",
             "description": "The Krellix Dominion controls the only safe corridor to the target system.",
             "priority": TaskPriority.high, "category": TaskStatusCategory.backlog,
             "assignees": ["Finley Goldtongue"]},
            {"project_id": g2_exodus.id, "title": "Quell the mutiny on Deck 7",
             "description": "A group of colonists is threatening to take a shuttle and break from the fleet.",
             "priority": TaskPriority.urgent, "category": TaskStatusCategory.done,
             "assignees": ["Admin User", "Aurelia Brightshield"]},
            {"project_id": g2_exodus.id, "title": "Map the nebula passage",
             "description": "Chart a safe course through the Verdant Nebula to save 3 months of travel.",
             "priority": TaskPriority.medium, "category": TaskStatusCategory.todo,
             "assignees": ["Elara Moonwhisper"]},
            {"project_id": g2_exodus.id, "title": "Decommission the Icarus VII",
             "description": "The oldest ship in the fleet is no longer spaceworthy. Salvage what we can.",
             "priority": TaskPriority.low, "category": TaskStatusCategory.backlog},
            # Colony Alpha
            {"project_id": g2_colony.id, "title": "Survey landing sites on Kepler-442b",
             "description": "Send probes to evaluate three candidate sites for the colony.",
             "priority": TaskPriority.high, "category": TaskStatusCategory.in_progress,
             "assignees": ["Admin User"],
             "subtasks": ["Deploy orbital probes", "Analyze atmospheric data", "Check for hostile fauna"],
             "due_days": 14},
            {"project_id": g2_colony.id, "title": "Design the colony habitat modules",
             "description": "Prefab habitats need to support 500 colonists in the first wave.",
             "priority": TaskPriority.medium, "category": TaskStatusCategory.todo,
             "assignees": ["Kael Windrunner"]},
            {"project_id": g2_colony.id, "title": "Establish a perimeter defense grid",
             "description": "Unknown life forms detected. We need automated defenses.",
             "priority": TaskPriority.high, "category": TaskStatusCategory.backlog,
             "assignees": ["Aurelia Brightshield"]},
            {"project_id": g2_colony.id, "title": "Set up the hydroponics bay",
             "description": "Food production must begin within 48 hours of landing.",
             "priority": TaskPriority.urgent, "category": TaskStatusCategory.todo,
             "due_days": 3},
            # Smuggler's Run
            {"project_id": g2_fringe.id, "title": "Infiltrate Station Omega",
             "description": "The heist begins: get past security and reach the vault level.",
             "priority": TaskPriority.high, "category": TaskStatusCategory.in_progress,
             "assignees": ["Vex Shadowstep", "Finley Goldtongue"],
             "subtasks": ["Forge ID badges", "Disable security cameras on Level 3", "Create a distraction"]},
            {"project_id": g2_fringe.id, "title": "Crack the vault encryption",
             "description": "The vault uses quantum encryption. We need a specialist AI.",
             "priority": TaskPriority.urgent, "category": TaskStatusCategory.todo,
             "assignees": ["Kael Windrunner"]},
            {"project_id": g2_fringe.id, "title": "Escape before station self-destructs",
             "description": "Once the vault opens, the station's failsafe triggers. 10 minutes to escape.",
             "priority": TaskPriority.urgent, "category": TaskStatusCategory.backlog},
            # Engineering Bay
            {"project_id": g2_engineering.id, "title": "Upgrade shield generators to Mark IV",
             "description": "Current shields can't handle Krellix plasma weapons.",
             "priority": TaskPriority.high, "category": TaskStatusCategory.in_progress,
             "assignees": ["Kael Windrunner", "Elara Moonwhisper"]},
            {"project_id": g2_engineering.id, "title": "Research cloaking technology",
             "description": "Salvaged alien tech might allow partial cloaking of smaller vessels.",
             "priority": TaskPriority.medium, "category": TaskStatusCategory.backlog,
             "assignees": ["Elara Moonwhisper"]},
            {"project_id": g2_engineering.id, "title": "Fabricate replacement hull plating",
             "description": "Asteroid impacts have weakened the port side. Fabricate and install repairs.",
             "priority": TaskPriority.medium, "category": TaskStatusCategory.done,
             "assignees": ["Kael Windrunner"]},
            # Planning
            {"project_id": g2_planning.id, "title": "Schedule Session 5: Colony Landfall",
             "description": "The big session where the fleet arrives at Kepler-442b.",
             "priority": TaskPriority.medium, "category": TaskStatusCategory.todo,
             "assignees": ["Admin User"], "due_days": 10},
            {"project_id": g2_planning.id, "title": "Prep NPC stat blocks for Krellix diplomats",
             "description": "Need stats for 3 Krellix NPCs with unique abilities.",
             "priority": TaskPriority.low, "category": TaskStatusCategory.in_progress,
             "assignees": ["Admin User"]},
        ]

        g2_tasks: dict[str, Task] = {}
        for proj in g2_projects:
            proj_tasks = [td for td in g2_task_defs if td["project_id"] == proj.id]
            tasks = await _create_tasks(
                session, ids,
                guild=g2,
                status_map=g2_status_maps[proj.id],
                task_defs=proj_tasks,
                all_users=all_users,
            )
            g2_tasks.update(tasks)

        # Tags
        print("  Creating Guild 2 tags...")
        g2_tags = await _create_tags(session, ids, g2, [
            ("main quest", "#EF4444"),
            ("side quest", "#6366F1"),
            ("engineering", "#0EA5E9"),
            ("diplomacy", "#10B981"),
            ("combat", "#DC2626"),
            ("exploration", "#8B5CF6"),
            ("NPC", "#F59E0B"),
            ("loot", "#D97706"),
            ("survival", "#059669"),
            ("stealth", "#475569"),
        ])

        await _link_task_tags(session, ids, g2_tasks, g2_tags, [
            ("Repair the FTL drive core", ["main quest", "engineering"]),
            ("Investigate the distress signal from Sector 7G", ["exploration", "side quest"]),
            ("Negotiate passage through Krellix space", ["diplomacy", "main quest"]),
            ("Quell the mutiny on Deck 7", ["main quest", "NPC"]),
            ("Infiltrate Station Omega", ["stealth", "side quest"]),
            ("Crack the vault encryption", ["stealth", "engineering"]),
            ("Upgrade shield generators to Mark IV", ["engineering"]),
            ("Survey landing sites on Kepler-442b", ["exploration", "main quest"]),
            ("Establish a perimeter defense grid", ["combat", "survival"]),
            ("Set up the hydroponics bay", ["survival"]),
        ])

        await _link_project_tags(session, ids, g2_tags, [
            (g2_exodus.id, ["main quest", "exploration"]),
            (g2_colony.id, ["main quest", "survival"]),
            (g2_fringe.id, ["side quest", "stealth", "loot"]),
            (g2_engineering.id, ["engineering"]),
        ])

        # Documents
        print("  Creating Guild 2 documents...")
        g2_docs = await _create_documents(session, ids, guild=g2, all_users=all_users, doc_defs=[
            {
                "initiative_id": g2_main.id,
                "title": "Setting Bible: The Exodus Protocol",
                "creator": "Admin User",
                "writers": ["Finley Goldtongue"],
                "readers": ["Kael Windrunner", "Aurelia Brightshield"],
                "paragraphs": [
                    "The year is 2487. Earth was rendered uninhabitable by the Cascade Event — a catastrophic "
                    "chain reaction in the planet's magnetic field. The last 50,000 humans fled aboard "
                    "the Exodus Fleet: 12 ships of varying size and capability.",
                    "The fleet has been traveling for 73 years. Most colonists are in cryosleep, rotated "
                    "in shifts. The active crew numbers about 2,000 at any given time.",
                    "FTL travel exists but is expensive and unreliable. The fleet's main FTL drive "
                    "can make one jump per month. Smaller scout ships have limited-range jump drives.",
                ],
            },
            {
                "initiative_id": g2_main.id,
                "title": "Faction Guide: Krellix Dominion",
                "creator": "Admin User",
                "paragraphs": [
                    "The Krellix are a territorial insectoid species that controls a swathe of space "
                    "between the fleet and the target system. They are technologically advanced but "
                    "not inherently hostile — diplomacy is possible.",
                    "Krellix society is caste-based: Workers, Warriors, Diplomats, and the Overmind. "
                    "Trade agreements require approval from a local Diplomat caste leader.",
                ],
            },
            {
                "initiative_id": g2_side.id,
                "title": "One-Shot: Smuggler's Run Briefing",
                "creator": "Finley Goldtongue",
                "paragraphs": [
                    "Station Omega is a decommissioned military research station now operated by "
                    "the Crimson Syndicate. Inside the vault: a prototype cloaking device worth "
                    "enough credits to fund the fleet for a decade.",
                    "The station has 5 levels. Security increases with each level. The vault is "
                    "on Level 5. Self-destruct activates 10 minutes after the vault is breached.",
                ],
            },
            {
                "initiative_id": g2_default_init.id,
                "title": "Session 1 Recap: Into the Void",
                "creator": "Admin User",
                "paragraphs": [
                    "The crew awoke from cryosleep to find the fleet's AI, ORACLE, had gone silent. "
                    "Emergency protocols activated. The FTL drive was offline.",
                    "The team discovered sabotage — someone had manually overridden ORACLE's core "
                    "directives. Suspicion fell on the Deck 7 separatists.",
                ],
            },
        ])

        await _link_doc_projects(session, ids, g2, [
            (g2_exodus.id, g2_docs["Setting Bible: The Exodus Protocol"].id, admin_user),
            (g2_exodus.id, g2_docs["Faction Guide: Krellix Dominion"].id, admin_user),
            (g2_fringe.id, g2_docs["One-Shot: Smuggler's Run Briefing"].id, finley),
            (g2_planning.id, g2_docs["Session 1 Recap: Into the Void"].id, admin_user),
        ])

        await _link_doc_tags(session, ids, g2_docs, g2_tags, [
            ("Setting Bible: The Exodus Protocol", ["main quest"]),
            ("Faction Guide: Krellix Dominion", ["NPC", "diplomacy"]),
            ("One-Shot: Smuggler's Run Briefing", ["stealth", "loot"]),
        ])

        # Comments
        print("  Creating Guild 2 comments...")
        await _create_comments(session, ids, g2, [
            {"author": "Kael Windrunner", "task_title": "Repair the FTL drive core",
             "content": "The plasma leak is worse than expected. We might need to cannibalize the Icarus VII."},
            {"author": "Admin User", "task_title": "Repair the FTL drive core",
             "content": "Do it. The Icarus was going to be decommissioned anyway."},
            {"author": "Finley Goldtongue", "task_title": "Negotiate passage through Krellix space",
             "content": "I have a contact in the Diplomat caste. We'll need a gift — something they don't have."},
            {"author": "Aurelia Brightshield", "task_title": "Investigate the distress signal from Sector 7G",
             "content": "Could be a trap. The Crimson Syndicate uses fake distress beacons."},
            {"author": "Vex Shadowstep", "task_title": "Infiltrate Station Omega",
             "content": "I can forge the ID badges. Kael, can you loop the security feeds?"},
            {"author": "Kael Windrunner", "task_title": "Infiltrate Station Omega",
             "content": "Already on it. I'll need 30 minutes once we're inside."},
            {"author": "Elara Moonwhisper", "doc_title": "Setting Bible: The Exodus Protocol",
             "content": "We should add a section on the cryosleep rotation schedule — it came up last session."},
        ], g2_tasks, g2_docs, all_users)

        # -- Guild 2 Settings --
        print("  Creating Guild 2 settings...")
        await _create_guild_settings(session, ids, g2, ai_enabled=True)

        # -- Favorites & Recent Views --
        print("  Creating Guild 2 favorites & views...")
        await _create_favorites(session, ids, g2, [
            (admin_user, g2_exodus), (admin_user, g2_colony),
            (finley, g2_fringe), (finley, g2_exodus),
            (kael, g2_engineering), (kael, g2_exodus),
            (aurelia, g2_colony),
            (vex, g2_fringe),
        ])
        await _create_recent_views(session, ids, g2, [
            (admin_user, g2_exodus), (admin_user, g2_colony), (admin_user, g2_planning),
            (finley, g2_fringe), (finley, g2_exodus),
            (kael, g2_engineering), (kael, g2_exodus),
        ])

        # -- Document Links --
        print("  Creating Guild 2 document links...")
        await _create_document_links(session, ids, g2, g2_docs, [
            ("Faction Guide: Krellix Dominion", "Setting Bible: The Exodus Protocol"),
            ("Session 1 Recap: Into the Void", "Setting Bible: The Exodus Protocol"),
            ("One-Shot: Smuggler's Run Briefing", "Setting Bible: The Exodus Protocol"),
        ])

        # -- Queues --
        print("  Creating Guild 2 queues...")
        await _create_queues(session, ids, g2, all_users, g2_tags, [
            {
                "initiative_id": g2_main.id,
                "name": "Bridge Standoff: Krellix Boarding Party",
                "description": "The Krellix shock troopers have breached the main airlock",
                "created_by": "Admin User",
                "is_active": True,
                "current_round": 2,
                "write_users": ["Finley Goldtongue", "Kael Windrunner"],
                "active_item_label": "Krellix Shock Trooper #1",
                "items": [
                    {"label": "Kael Windrunner", "position": 24, "user": "Kael Windrunner",
                     "color": "#0EA5E9", "notes": "Shield generator overcharged — +2 AC"},
                    {"label": "Krellix Shock Trooper #1", "position": 21,
                     "color": "#EF4444", "notes": "HP: 45/45 — plasma rifle",
                     "tags": ["combat"]},
                    {"label": "Aurelia Brightshield", "position": 19, "user": "Aurelia Brightshield",
                     "color": "#F59E0B"},
                    {"label": "Krellix Shock Trooper #2", "position": 17,
                     "color": "#EF4444", "notes": "HP: 45/45"},
                    {"label": "Finley Goldtongue", "position": 15, "user": "Finley Goldtongue",
                     "color": "#8B5CF6", "notes": "Attempting to hack the airlock controls"},
                    {"label": "Vex Shadowstep", "position": 12, "user": "Vex Shadowstep",
                     "color": "#6366F1"},
                    {"label": "Krellix Commander", "position": 10,
                     "color": "#B91C1C", "notes": "HP: 80/80 — energy blade",
                     "tags": ["combat", "boss fight"]},
                ],
            },
        ])

        await _enable_queue_permissions(session, [g2_main_mem])

        # -- Counters --
        print("  Creating Guild 2 counter groups...")
        await _create_counter_groups(session, ids, g2, all_users, [
            {
                "initiative_id": g2_main.id,
                "name": "Fleet Status",
                "description": "Ship integrity and resource levels for The Exodus Protocol.",
                "created_by": "Admin User",
                "role_grants": [{"role_id": g2_main_mem.id, "level": CounterPermissionLevel.write}],
                "counters": [
                    {"name": "Hull Integrity", "color": "#3B82F6", "count": 78, "min": 0, "max": 100,
                     "step": 5, "initial_count": 100, "view_mode": CounterViewMode.progress_bar, "position": 1},
                    {"name": "Plasma Reserves", "color": "#F59E0B", "count": 42, "min": 0, "max": 80,
                     "step": 1, "initial_count": 80, "view_mode": CounterViewMode.progress_bar, "position": 2},
                    {"name": "Colonists in Cryo", "color": "#10B981", "count": 4870, "min": 0,
                     "step": 1, "initial_count": 5000, "view_mode": CounterViewMode.number, "position": 3},
                    {"name": "Days to Kepler-442b", "color": "#7C3AED", "count": 6, "min": 0, "max": 8,
                     "step": 1, "initial_count": 8, "view_mode": CounterViewMode.segmented_clock, "position": 4},
                ],
            },
            {
                "initiative_id": g2_main.id,
                "name": "Krellix Diplomatic Tracker",
                "description": "Relations with the Krellix Dominion.",
                "created_by": "Admin User",
                "counters": [
                    {"name": "Treaty Progress", "color": "#0EA5E9", "count": 2, "min": 0, "max": 5,
                     "step": 1, "initial_count": 0, "view_mode": CounterViewMode.segmented_clock, "position": 1},
                    {"name": "Hostility Score", "color": "#DC2626", "count": 3, "min": 0, "max": 10,
                     "step": 1, "initial_count": 0, "view_mode": CounterViewMode.number, "position": 2},
                ],
            },
            {
                "initiative_id": g2_side.id,
                "name": "Heist Crew Funds",
                "description": "Loot stash and expenses for the Smuggler's Run crew.",
                "created_by": "Finley Goldtongue",
                "counters": [
                    {"name": "Credits", "color": "#F59E0B", "count": 12500, "min": 0,
                     "step": 100, "initial_count": 8000, "view_mode": CounterViewMode.number, "position": 1},
                    {"name": "Bribes Spent", "color": "#7F1D1D", "count": 1800, "min": 0,
                     "step": 50, "initial_count": 0, "view_mode": CounterViewMode.number, "position": 2},
                ],
            },
        ])
        await _enable_role_feature(session, [g2_main_mem, g2_side_mem], "counters_enabled")

        # -- Calendar events --
        print("  Creating Guild 2 calendar events...")
        await _create_calendar_events(session, ids, g2, all_users, g2_tags, g2_docs, [
            {
                "initiative_id": g2_main.id,
                "title": "Session 5: Colony Landfall",
                "description": "The fleet arrives at Kepler-442b.",
                "location": "Discord voice",
                "start_at": NOW + timedelta(days=3, hours=1),
                "end_at": NOW + timedelta(days=3, hours=4),
                "color": "#0EA5E9",
                "created_by": "Admin User",
                "attendees": [
                    {"user": "Admin User", "rsvp_status": RSVPStatus.accepted},
                    {"user": "Finley Goldtongue", "rsvp_status": RSVPStatus.accepted},
                    {"user": "Kael Windrunner", "rsvp_status": RSVPStatus.accepted},
                    {"user": "Aurelia Brightshield", "rsvp_status": RSVPStatus.tentative},
                ],
                "tags": ["combat"] if "combat" in g2_tags else [],
                "documents": ["Setting Bible: The Exodus Protocol"],
            },
            {
                "initiative_id": g2_main.id,
                "title": "Bi-weekly Starfall Session",
                "description": "Standing campaign night.",
                "start_at": NOW + timedelta(days=10, hours=2),
                "end_at": NOW + timedelta(days=10, hours=5),
                "color": "#0EA5E9",
                "created_by": "Admin User",
                "recurrence": {
                    "frequency": "weekly", "interval": 2,
                    "weekdays": ["sa"], "ends": "after_occurrences",
                    "end_after_occurrences": 8,
                },
                "attendees": [
                    {"user": "Admin User", "rsvp_status": RSVPStatus.accepted},
                    {"user": "Kael Windrunner", "rsvp_status": RSVPStatus.accepted},
                ],
            },
            {
                "initiative_id": g2_main.id,
                "title": "Session 4: Distress Signal",
                "description": "Past session — investigated Sector 7G.",
                "start_at": NOW - timedelta(days=10, hours=23),
                "end_at": NOW - timedelta(days=10, hours=20),
                "color": "#0EA5E9",
                "created_by": "Admin User",
            },
            {
                "initiative_id": g2_main.id,
                "title": "Worldbuilding Day",
                "description": "All-day workshop with the players for the post-landfall arc.",
                "start_at": NOW + timedelta(days=21),
                "end_at": NOW + timedelta(days=21),
                "all_day": True,
                "color": "#10B981",
                "created_by": "Admin User",
                "tags": ["roleplay"] if "roleplay" in g2_tags else [],
            },
            {
                "initiative_id": g2_side.id,
                "title": "One-shot: Smuggler's Run",
                "description": "Heist night.",
                "location": "Discord voice",
                "start_at": NOW + timedelta(days=5, hours=3),
                "end_at": NOW + timedelta(days=5, hours=7),
                "color": "#F59E0B",
                "created_by": "Finley Goldtongue",
                "attendees": [
                    {"user": "Finley Goldtongue", "rsvp_status": RSVPStatus.accepted},
                    {"user": "Vex Shadowstep", "rsvp_status": RSVPStatus.accepted},
                    {"user": "Kael Windrunner", "rsvp_status": RSVPStatus.pending},
                ],
                "documents": ["One-Shot: Smuggler's Run Briefing"],
            },
        ])
        await _enable_role_feature(session, [g2_main_mem, g2_side_mem], "events_enabled")

        # -- Custom properties --
        print("  Creating Guild 2 property definitions + values...")
        g2_main_props = await _create_property_definitions(session, ids, g2_main, [
            {"name": "System", "type": PropertyType.select, "position": 1.0,
             "options": [
                 {"value": "starfinder", "label": "Starfinder", "color": "#3B82F6"},
                 {"value": "stars_without_number", "label": "Stars Without Number", "color": "#10B981"},
                 {"value": "homebrew", "label": "Homebrew", "color": "#F59E0B"},
             ]},
            {"name": "Tech Level", "type": PropertyType.number, "position": 2.0, "color": "#0EA5E9"},
            {"name": "Faction Tags", "type": PropertyType.multi_select, "position": 3.0,
             "options": [
                 {"value": "exodus_fleet", "label": "Exodus Fleet", "color": "#3B82F6"},
                 {"value": "krellix", "label": "Krellix Dominion", "color": "#DC2626"},
                 {"value": "merchant_guild", "label": "Merchant Guild", "color": "#F59E0B"},
             ]},
            {"name": "Briefing Required", "type": PropertyType.checkbox, "position": 4.0},
            {"name": "Owner", "type": PropertyType.user_reference, "position": 5.0},
        ])
        t_repair_id = g2_tasks["Repair the FTL drive core"].id
        t_negotiate_id = g2_tasks["Negotiate passage through Krellix space"].id
        t_mutiny_id = g2_tasks["Quell the mutiny on Deck 7"].id
        doc_setting_g2_id = g2_docs["Setting Bible: The Exodus Protocol"].id
        doc_krellix_id = g2_docs["Faction Guide: Krellix Dominion"].id

        await _attach_property_values(session, ids, g2_main_props["System"], [
            ("task", t_repair_id, "starfinder"),
            ("task", t_negotiate_id, "homebrew"),
        ])
        await _attach_property_values(session, ids, g2_main_props["Tech Level"], [
            ("task", t_repair_id, Decimal("9")),
            ("task", t_negotiate_id, Decimal("7")),
        ])
        await _attach_property_values(session, ids, g2_main_props["Faction Tags"], [
            ("task", t_negotiate_id, ["exodus_fleet", "krellix"]),
            ("document", doc_krellix_id, ["krellix"]),
        ])
        await _attach_property_values(session, ids, g2_main_props["Briefing Required"], [
            ("task", t_repair_id, True),
            ("task", t_mutiny_id, False),
        ])
        await _attach_property_values(session, ids, g2_main_props["Owner"], [
            ("task", t_repair_id, kael.id),
            ("task", t_negotiate_id, finley.id),
            ("document", doc_setting_g2_id, admin_user.id),
        ])

        g2_side_props = await _create_property_definitions(session, ids, g2_side, [
            {"name": "Mission Status", "type": PropertyType.select, "position": 1.0,
             "options": [
                 {"value": "scoping", "label": "Scoping"},
                 {"value": "active", "label": "Active", "color": "#10B981"},
                 {"value": "complete", "label": "Complete", "color": "#6B7280"},
             ]},
            {"name": "Payout (credits)", "type": PropertyType.number, "position": 2.0},
            {"name": "Map Link", "type": PropertyType.url, "position": 3.0},
        ])
        t_infiltrate_id = g2_tasks["Infiltrate Station Omega"].id
        t_crack_id = g2_tasks["Crack the vault encryption"].id
        await _attach_property_values(session, ids, g2_side_props["Mission Status"], [
            ("task", t_infiltrate_id, "active"),
            ("task", t_crack_id, "scoping"),
        ])
        await _attach_property_values(session, ids, g2_side_props["Payout (credits)"], [
            ("task", t_infiltrate_id, Decimal("75000")),
        ])

        # ==============================================================
        # GUILD 3: "Realm of Tides" — Pirate/Nautical Campaign
        # ==============================================================
        print("\n  --- Guild 3: Realm of Tides (Pirate Campaign) ---")

        g3 = await _create_guild(
            session, ids,
            name="Realm of Tides",
            description="A nautical fantasy campaign across the Shattered Seas",
            creator=finley,
        )
        g3_id = g3.id

        # Commit guild 2's data + guild 3's shared rows, then provision + route.
        await session.commit()
        _expunge_guild_scoped(session)  # clear guild 2's per-schema ids from the identity map
        await provision_guild(g3_id)
        await set_rls_context(
            session, user_id=admin_user.id, guild_id=g3_id, guild_role="admin", is_superadmin=True
        )

        await _add_guild_members(
            session, ids, g3,
            [admin_user, dm, thorn, kael, aurelia, sera],
            admin_users=[admin_user],
        )

        # Default initiative
        g3_default_init = await ensure_default_initiative(session, finley, guild_id=g3_id)
        result = await session.exec(
            select(InitiativeRoleModel).where(
                InitiativeRoleModel.initiative_id == g3_default_init.id,
            )
        )
        for role in result.all():
            ids.add("initiative_roles", role.id)
            perms_result = await session.exec(
                select(InitiativeRolePermission).where(
                    InitiativeRolePermission.initiative_role_id == role.id
                )
            )
            for perm in perms_result.all():
                ids.add("initiative_role_permissions", {
                    "initiative_role_id": perm.initiative_role_id,
                    "permission_key": perm.permission_key,
                })
        ids.add("initiatives", g3_default_init.id)

        # Add some members to default initiative
        result = await session.exec(
            select(InitiativeRoleModel).where(
                InitiativeRoleModel.initiative_id == g3_default_init.id,
                InitiativeRoleModel.name == "member",
            )
        )
        g3_def_member_role = result.one()
        for user in [admin_user, dm]:
            m = InitiativeMember(
                initiative_id=g3_default_init.id,
                user_id=user.id,
                guild_id=g3_id,
                role_id=g3_def_member_role.id,
            )
            session.add(m)
            ids.add("initiative_members", {
                "initiative_id": g3_default_init.id, "user_id": user.id,
            })
        await session.flush()

        g3_main, g3_main_pm, g3_main_mem = await _create_initiative(
            session, ids,
            guild=g3,
            name="The Crimson Tide Campaign",
            description="A pirate crew sails the Shattered Seas in search of the Leviathan's Heart",
            color="#DC2626",
            pm_user=finley,
            member_users=[admin_user, dm, thorn, kael, aurelia, sera],
            queues_enabled=True,
            counters_enabled=True,
            events_enabled=True,
        )

        g3_navy, g3_navy_pm, g3_navy_mem = await _create_initiative(
            session, ids,
            guild=g3,
            name="Royal Navy Conflicts",
            description="Encounters and battles with the Imperial Navy",
            color="#1E40AF",
            pm_user=dm,
            member_users=[finley, thorn, kael],
            queues_enabled=True,
            counters_enabled=True,
            events_enabled=True,
        )

        # Projects
        print("  Creating Guild 3 projects...")
        g3_ship = await _create_project(
            session, ids,
            guild=g3, initiative=g3_main,
            name="The Crimson Maiden",
            icon="\u2693",
            description="Managing the party's ship, crew, and upgrades",
            owner=finley,
            write_users=[admin_user, thorn],
            read_users=[kael, aurelia, sera],
        )

        g3_treasure = await _create_project(
            session, ids,
            guild=g3, initiative=g3_main,
            name="Treasure of the Leviathan",
            icon="\U0001F4B0",
            description="The legendary hoard guarded by the sea beast",
            owner=finley,
            write_users=[admin_user, dm],
        )

        g3_islands = await _create_project(
            session, ids,
            guild=g3, initiative=g3_main,
            name="Island Exploration",
            icon="\U0001F3DD\uFE0F",
            description="Uncharted islands and their mysteries",
            owner=dm,
            write_users=[finley, kael],
            read_users=[aurelia],
        )

        g3_navy_proj = await _create_project(
            session, ids,
            guild=g3, initiative=g3_navy,
            name="Admiral Blackwood's Fleet",
            icon="\u2694\uFE0F",
            description="Tracking the movements and strength of the Imperial Navy",
            owner=dm,
            write_users=[finley, thorn],
        )

        g3_planning = await _create_project(
            session, ids,
            guild=g3, initiative=g3_default_init,
            name="Campaign Notes",
            icon="\U0001F4DD",
            description="Session recaps and campaign logistics",
            owner=finley,
            write_users=[admin_user, dm],
        )

        # Task statuses
        g3_projects = [g3_ship, g3_treasure, g3_islands, g3_navy_proj, g3_planning]
        g3_status_maps: dict[int, dict[str, TaskStatus]] = {}
        for proj in g3_projects:
            statuses = await ensure_default_statuses(session, proj.id)
            cat_map = {}
            for s in statuses:
                cat_map[s.category] = s
                ids.add("task_statuses", s.id)
            g3_status_maps[proj.id] = cat_map
        await session.flush()

        # Tasks
        print("  Creating Guild 3 tasks...")
        g3_task_defs = [
            # The Crimson Maiden
            {"project_id": g3_ship.id, "title": "Recruit a new helmsman",
             "description": "Old Barnaby fell overboard. We need someone who can navigate the Shattered Reefs.",
             "priority": TaskPriority.high, "category": TaskStatusCategory.todo,
             "assignees": ["Finley Goldtongue"], "due_days": 5},
            {"project_id": g3_ship.id, "title": "Repair the hull after the kraken attack",
             "description": "Three breaches below the waterline. She's taking on water.",
             "priority": TaskPriority.urgent, "category": TaskStatusCategory.in_progress,
             "assignees": ["Thorn Ironforge", "Kael Windrunner"],
             "subtasks": ["Patch the port breach", "Reinforce the keel", "Replace the damaged mast"]},
            {"project_id": g3_ship.id, "title": "Upgrade cannons to dragon-fire shot",
             "description": "Alchemical ammunition from the black market in Port Havoc.",
             "priority": TaskPriority.medium, "category": TaskStatusCategory.backlog,
             "assignees": ["Thorn Ironforge"]},
            {"project_id": g3_ship.id, "title": "Restock provisions at Port Havoc",
             "description": "Fresh water, hardtack, rum, and gunpowder. The essentials.",
             "priority": TaskPriority.medium, "category": TaskStatusCategory.done},
            {"project_id": g3_ship.id, "title": "Install the enchanted compass",
             "description": "The compass from the Sea Witch should point to the Leviathan's lair.",
             "priority": TaskPriority.high, "category": TaskStatusCategory.todo,
             "assignees": ["Aurelia Brightshield"]},
            # Treasure of the Leviathan
            {"project_id": g3_treasure.id, "title": "Decipher the Leviathan Map",
             "description": "The map is written in Old Merfolk. Find someone who can read it.",
             "priority": TaskPriority.urgent, "category": TaskStatusCategory.in_progress,
             "assignees": ["Finley Goldtongue", "Admin User"],
             "subtasks": ["Find a translator in Port Havoc", "Cross-reference with known charts",
                          "Identify the three key landmarks"]},
            {"project_id": g3_treasure.id, "title": "Collect the three Tidestones",
             "description": "Legend says three enchanted stones unlock the Leviathan's vault.",
             "priority": TaskPriority.high, "category": TaskStatusCategory.backlog,
             "subtasks": ["Tidestone of Storms (Tempest Isle)", "Tidestone of Depths (Abyssal Trench)",
                          "Tidestone of Calm (Sanctuary Reef)"]},
            {"project_id": g3_treasure.id, "title": "Defeat the Leviathan guardian",
             "description": "An ancient sea serpent guards the entrance to the vault. This won't be easy.",
             "priority": TaskPriority.urgent, "category": TaskStatusCategory.backlog,
             "due_days": 45},
            {"project_id": g3_treasure.id, "title": "Research the Leviathan's weakness",
             "description": "The old legends mention a weakness. Check the library at Coral Keep.",
             "priority": TaskPriority.medium, "category": TaskStatusCategory.todo,
             "assignees": ["Admin User"]},
            # Island Exploration
            {"project_id": g3_islands.id, "title": "Explore Skull Cove",
             "description": "A hidden cove on the south side of Dagger Isle. Rumored to hold pirate treasure.",
             "priority": TaskPriority.medium, "category": TaskStatusCategory.done,
             "assignees": ["Kael Windrunner", "Finley Goldtongue"]},
            {"project_id": g3_islands.id, "title": "Map the Whispering Jungle",
             "description": "The interior of Tempest Isle is unmapped. Strange sounds at night.",
             "priority": TaskPriority.medium, "category": TaskStatusCategory.in_progress,
             "assignees": ["Kael Windrunner"],
             "subtasks": ["Chart the coastline", "Find the source of the whispers",
                          "Locate the ruined temple"]},
            {"project_id": g3_islands.id, "title": "Negotiate with the Coral Elves",
             "description": "The Coral Elves of Sanctuary Reef may know where a Tidestone is hidden.",
             "priority": TaskPriority.high, "category": TaskStatusCategory.todo,
             "assignees": ["Finley Goldtongue", "Aurelia Brightshield"]},
            {"project_id": g3_islands.id, "title": "Investigate the ghost ship sightings",
             "description": "Multiple ships report a phantom vessel near the Abyssal Trench.",
             "priority": TaskPriority.low, "category": TaskStatusCategory.backlog},
            # Admiral Blackwood
            {"project_id": g3_navy_proj.id, "title": "Evade the HMS Vengeance",
             "description": "Blackwood's flagship is patrolling the straits. We need an alternate route.",
             "priority": TaskPriority.urgent, "category": TaskStatusCategory.in_progress,
             "assignees": ["Dungeon Master", "Finley Goldtongue"]},
            {"project_id": g3_navy_proj.id, "title": "Raid the supply convoy near Coral Keep",
             "description": "Three merchant ships carrying weapons and gold, lightly guarded.",
             "priority": TaskPriority.high, "category": TaskStatusCategory.todo,
             "assignees": ["Thorn Ironforge"], "due_days": 7},
            {"project_id": g3_navy_proj.id, "title": "Forge letters of marque",
             "description": "If we can forge royal papers, we can pass as privateers instead of pirates.",
             "priority": TaskPriority.medium, "category": TaskStatusCategory.todo,
             "assignees": ["Finley Goldtongue"]},
            {"project_id": g3_navy_proj.id, "title": "Sink the HMS Ironclad",
             "description": "Blackwood's second-in-command's ship. Remove it and weaken the fleet.",
             "priority": TaskPriority.high, "category": TaskStatusCategory.done,
             "assignees": ["Thorn Ironforge", "Kael Windrunner"]},
            # Campaign Notes
            {"project_id": g3_planning.id, "title": "Write session 6 recap",
             "description": "The kraken fight and arrival at Port Havoc.",
             "priority": TaskPriority.low, "category": TaskStatusCategory.todo,
             "assignees": ["Admin User"]},
            {"project_id": g3_planning.id, "title": "Schedule next session",
             "description": "Probably the weekend after next. Check with everyone.",
             "priority": TaskPriority.medium, "category": TaskStatusCategory.in_progress,
             "assignees": ["Finley Goldtongue"], "due_days": 4},
        ]

        g3_tasks: dict[str, Task] = {}
        for proj in g3_projects:
            proj_tasks = [td for td in g3_task_defs if td["project_id"] == proj.id]
            tasks = await _create_tasks(
                session, ids,
                guild=g3,
                status_map=g3_status_maps[proj.id],
                task_defs=proj_tasks,
                all_users=all_users,
            )
            g3_tasks.update(tasks)

        # Tags
        print("  Creating Guild 3 tags...")
        g3_tags = await _create_tags(session, ids, g3, [
            ("main quest", "#EF4444"),
            ("side quest", "#6366F1"),
            ("naval combat", "#0EA5E9"),
            ("NPC", "#F59E0B"),
            ("exploration", "#10B981"),
            ("loot", "#D97706"),
            ("ship upgrades", "#8B5CF6"),
            ("stealth", "#475569"),
            ("boss fight", "#991B1B"),
            ("diplomacy", "#059669"),
        ])

        await _link_task_tags(session, ids, g3_tasks, g3_tags, [
            ("Repair the hull after the kraken attack", ["ship upgrades"]),
            ("Upgrade cannons to dragon-fire shot", ["ship upgrades", "loot"]),
            ("Install the enchanted compass", ["ship upgrades", "loot"]),
            ("Decipher the Leviathan Map", ["main quest", "exploration"]),
            ("Collect the three Tidestones", ["main quest", "exploration"]),
            ("Defeat the Leviathan guardian", ["main quest", "boss fight"]),
            ("Explore Skull Cove", ["exploration", "loot"]),
            ("Map the Whispering Jungle", ["exploration"]),
            ("Negotiate with the Coral Elves", ["diplomacy", "NPC"]),
            ("Investigate the ghost ship sightings", ["exploration", "side quest"]),
            ("Evade the HMS Vengeance", ["naval combat", "stealth"]),
            ("Raid the supply convoy near Coral Keep", ["naval combat", "loot"]),
            ("Forge letters of marque", ["stealth", "diplomacy"]),
            ("Sink the HMS Ironclad", ["naval combat", "boss fight"]),
            ("Recruit a new helmsman", ["NPC"]),
        ])

        await _link_project_tags(session, ids, g3_tags, [
            (g3_ship.id, ["ship upgrades"]),
            (g3_treasure.id, ["main quest", "exploration", "boss fight"]),
            (g3_islands.id, ["exploration", "side quest"]),
            (g3_navy_proj.id, ["naval combat", "stealth"]),
        ])

        # Documents
        print("  Creating Guild 3 documents...")
        g3_docs = await _create_documents(session, ids, guild=g3, all_users=all_users, doc_defs=[
            {
                "initiative_id": g3_main.id,
                "title": "The Shattered Seas: World Guide",
                "creator": "Finley Goldtongue",
                "writers": ["Dungeon Master"],
                "readers": ["Admin User", "Thorn Ironforge"],
                "paragraphs": [
                    "The Shattered Seas are a vast archipelago formed when the old continent sank "
                    "a thousand years ago. Hundreds of islands dot the warm waters, from volcanic "
                    "peaks to coral atolls.",
                    "Major factions: The Imperial Navy (law and order), the Pirate Lords (freedom and chaos), "
                    "the Coral Elves (ancient guardians), and the Deep Ones (mysterious undersea dwellers).",
                    "Currency: Gold doubloons, silver pieces, and trade goods. A good ship is worth "
                    "more than gold — it's your life.",
                ],
            },
            {
                "initiative_id": g3_main.id,
                "title": "Crew Manifest: The Crimson Maiden",
                "creator": "Finley Goldtongue",
                "paragraphs": [
                    "Captain: Finley 'Goldtongue' Ashford — Bard/Swashbuckler. Charisma is the real weapon.",
                    "First Mate: Thorn Ironforge — Fighter/Battlemaster. Handles boarding actions.",
                    "Navigator: Kael Windrunner — Ranger/Horizon Walker. Reads the stars and tides.",
                    "Quartermaster: Aurelia Brightshield — Paladin of the Sea. Keeps the crew honest.",
                    "Ship's Chaplain: Seraphina Dawnlight — Cleric of the Tide Mother.",
                    "Crew complement: 47 sailors, 12 marines, 3 officers.",
                ],
            },
            {
                "initiative_id": g3_navy.id,
                "title": "Intelligence Report: Admiral Blackwood",
                "creator": "Dungeon Master",
                "readers": ["Finley Goldtongue", "Thorn Ironforge"],
                "paragraphs": [
                    "Admiral Helena Blackwood commands the 3rd Imperial Fleet from her flagship, "
                    "the HMS Vengeance (a 74-gun ship of the line). She is ruthless, brilliant, "
                    "and has a personal vendetta against Captain Ashford.",
                    "Known ships: HMS Vengeance (flagship), HMS Ironclad (sunk by party), "
                    "HMS Stormbreak, HMS Resolute, plus 8 frigates and 12 sloops.",
                    "Weakness: Blackwood's supply lines are stretched thin. Hit the convoys.",
                ],
            },
            {
                "initiative_id": g3_default_init.id,
                "title": "Session 5 Recap: The Kraken's Fury",
                "creator": "Finley Goldtongue",
                "paragraphs": [
                    "The Crimson Maiden was ambushed by a kraken near the Abyssal Trench. "
                    "The battle was fierce — we lost 6 crew and the mainmast before driving "
                    "the beast off with alchemist's fire.",
                    "Limped into Port Havoc for repairs. Made contact with a fence who claims "
                    "to know a translator for the Leviathan Map.",
                ],
            },
            {
                "initiative_id": g3_default_init.id,
                "title": "Session 4 Recap: The Ironclad Falls",
                "creator": "Finley Goldtongue",
                "paragraphs": [
                    "Ambushed the HMS Ironclad in a fog bank near Dagger Isle. Thorn led the "
                    "boarding party while Kael maneuvered us alongside. The Ironclad's captain "
                    "surrendered after we took the helm.",
                    "Salvaged: 200 gold doubloons, 50 barrels of gunpowder, a chest of maps, "
                    "and the enchanted compass (which turned out to be a Tidestone detector).",
                ],
            },
        ])

        await _link_doc_projects(session, ids, g3, [
            (g3_ship.id, g3_docs["Crew Manifest: The Crimson Maiden"].id, finley),
            (g3_treasure.id, g3_docs["The Shattered Seas: World Guide"].id, finley),
            (g3_navy_proj.id, g3_docs["Intelligence Report: Admiral Blackwood"].id, dm),
            (g3_planning.id, g3_docs["Session 5 Recap: The Kraken's Fury"].id, finley),
            (g3_planning.id, g3_docs["Session 4 Recap: The Ironclad Falls"].id, finley),
        ])

        await _link_doc_tags(session, ids, g3_docs, g3_tags, [
            ("The Shattered Seas: World Guide", ["exploration"]),
            ("Crew Manifest: The Crimson Maiden", ["NPC"]),
            ("Intelligence Report: Admiral Blackwood", ["NPC", "naval combat"]),
        ])

        # Comments
        print("  Creating Guild 3 comments...")
        await _create_comments(session, ids, g3, [
            {"author": "Thorn Ironforge", "task_title": "Repair the hull after the kraken attack",
             "content": "The port breach is the worst. We'll need to beach her to fix the keel properly."},
            {"author": "Kael Windrunner", "task_title": "Repair the hull after the kraken attack",
             "content": "I know a cove on the west side of Port Havoc. Sheltered and private."},
            {"author": "Finley Goldtongue", "task_title": "Decipher the Leviathan Map",
             "content": "The fence wants 50 doubloons for the translator. Steep but worth it."},
            {"author": "Admin User", "task_title": "Decipher the Leviathan Map",
             "content": "I can cover the cost. Let's not haggle when we're this close."},
            {"author": "Dungeon Master", "task_title": "Evade the HMS Vengeance",
             "content": "Blackwood knows you're in Port Havoc. You have maybe 3 days before she arrives."},
            {"author": "Aurelia Brightshield", "task_title": "Negotiate with the Coral Elves",
             "content": "The Coral Elves respect strength but value honor. We should approach openly, not sneak."},
            {"author": "Finley Goldtongue", "task_title": "Forge letters of marque",
             "content": "I've got the royal seal impression from when we raided the Ironclad. Just need the right paper."},
            {"author": "Seraphina Dawnlight", "task_title": "Defeat the Leviathan guardian",
             "content": "The Tide Mother has granted me a vision. The guardian is bound, not willing. Perhaps we can free it instead of fighting."},
            {"author": "Dungeon Master", "doc_title": "Intelligence Report: Admiral Blackwood",
             "content": "Updated: Ironclad confirmed sunk. Blackwood is furious. Expect retaliation."},
            {"author": "Thorn Ironforge", "doc_title": "Crew Manifest: The Crimson Maiden",
             "content": "We lost 6 crew in the kraken fight. Need to update the manifest and recruit in Port Havoc."},
        ], g3_tasks, g3_docs, all_users)

        # -- Guild 3 Settings --
        print("  Creating Guild 3 settings...")
        await _create_guild_settings(session, ids, g3, ai_enabled=False)

        # -- Favorites & Recent Views --
        print("  Creating Guild 3 favorites & views...")
        await _create_favorites(session, ids, g3, [
            (finley, g3_ship), (finley, g3_treasure),
            (admin_user, g3_treasure), (admin_user, g3_navy_proj),
            (dm, g3_navy_proj), (dm, g3_islands),
            (thorn, g3_ship), (thorn, g3_navy_proj),
            (kael, g3_islands), (kael, g3_ship),
            (aurelia, g3_ship),
        ])
        await _create_recent_views(session, ids, g3, [
            (finley, g3_ship), (finley, g3_treasure), (finley, g3_planning),
            (admin_user, g3_treasure), (admin_user, g3_navy_proj),
            (dm, g3_navy_proj), (dm, g3_islands),
            (thorn, g3_ship), (thorn, g3_navy_proj),
            (kael, g3_islands),
        ])

        # -- Document Links --
        print("  Creating Guild 3 document links...")
        await _create_document_links(session, ids, g3, g3_docs, [
            ("Crew Manifest: The Crimson Maiden", "The Shattered Seas: World Guide"),
            ("Intelligence Report: Admiral Blackwood", "The Shattered Seas: World Guide"),
            ("Session 5 Recap: The Kraken's Fury", "Crew Manifest: The Crimson Maiden"),
            ("Session 5 Recap: The Kraken's Fury", "The Shattered Seas: World Guide"),
            ("Session 4 Recap: The Ironclad Falls", "Intelligence Report: Admiral Blackwood"),
            ("Session 4 Recap: The Ironclad Falls", "Crew Manifest: The Crimson Maiden"),
        ])

        # -- Queues --
        print("  Creating Guild 3 queues...")
        await _create_queues(session, ids, g3, all_users, g3_tags, [
            {
                "initiative_id": g3_main.id,
                "name": "Kraken Attack on the Crimson Maiden",
                "description": "A massive kraken surfaces and wraps its tentacles around the ship",
                "created_by": "Finley Goldtongue",
                "is_active": True,
                "current_round": 4,
                "write_users": ["Admin User", "Dungeon Master", "Thorn Ironforge"],
                "active_item_label": "Finley Goldtongue",
                "items": [
                    {"label": "Finley Goldtongue", "position": 23, "user": "Finley Goldtongue",
                     "color": "#F59E0B", "notes": "At the helm — trying to steer free"},
                    {"label": "Kraken Tentacle (Port)", "position": 20,
                     "color": "#7C3AED", "notes": "HP: 30/30 — grappling the mast",
                     "tags": ["combat"]},
                    {"label": "Thorn Ironforge", "position": 19, "user": "Thorn Ironforge",
                     "color": "#DC2626", "notes": "Hacking at the starboard tentacle",
                     "tags": ["combat"]},
                    {"label": "Kraken Tentacle (Starboard)", "position": 18,
                     "color": "#7C3AED", "notes": "HP: 30/30",
                     "tags": ["combat"]},
                    {"label": "Kael Windrunner", "position": 16, "user": "Kael Windrunner",
                     "color": "#0EA5E9", "notes": "In the crow's nest — firing arrows"},
                    {"label": "Admin User (First Mate)", "position": 14, "user": "Admin User",
                     "color": "#059669"},
                    {"label": "Aurelia Brightshield", "position": 11, "user": "Aurelia Brightshield",
                     "color": "#EAB308", "notes": "Channeling Tide Mother's blessing"},
                    {"label": "Seraphina Dawnlight", "position": 8, "user": "Seraphina Dawnlight",
                     "color": "#EC4899"},
                    {"label": "Kraken (Body)", "position": 5,
                     "color": "#581C87", "notes": "HP: 200/200 — submerged, surfaces round 6",
                     "is_visible": False, "tags": ["combat", "boss fight"]},
                ],
            },
            {
                "initiative_id": g3_main.id,
                "name": "Port Havoc Bar Brawl",
                "description": "A tavern argument escalates into a full-blown melee",
                "created_by": "Dungeon Master",
                "is_active": False,
                "current_round": 1,
                "write_users": ["Finley Goldtongue"],
                "items": [
                    {"label": "Finley Goldtongue", "position": 19, "user": "Finley Goldtongue",
                     "color": "#F59E0B"},
                    {"label": "Thorn Ironforge", "position": 17, "user": "Thorn Ironforge",
                     "color": "#DC2626"},
                    {"label": "Rival Pirate Captain", "position": 15,
                     "color": "#B91C1C", "notes": "Dual-wielding cutlasses"},
                    {"label": "Rival Crew (x3)", "position": 12,
                     "color": "#9CA3AF", "notes": "HP: 9 each"},
                    {"label": "Kael Windrunner", "position": 10, "user": "Kael Windrunner",
                     "color": "#0EA5E9"},
                    {"label": "Barkeep (Non-combatant)", "position": 1,
                     "color": "#78716C", "notes": "Hiding behind the bar"},
                ],
            },
        ])

        await _enable_queue_permissions(session, [g3_main_mem])

        # -- Counters --
        print("  Creating Guild 3 counter groups...")
        await _create_counter_groups(session, ids, g3, all_users, [
            {
                "initiative_id": g3_main.id,
                "name": "The Crimson Maiden",
                "description": "Ship state for the pirate vessel.",
                "created_by": "Finley Goldtongue",
                "role_grants": [{"role_id": g3_main_mem.id, "level": CounterPermissionLevel.write}],
                "counters": [
                    {"name": "Hull HP", "color": "#92400E", "count": 87, "min": 0, "max": 120,
                     "step": 1, "initial_count": 120, "view_mode": CounterViewMode.progress_bar, "position": 1},
                    {"name": "Sails", "color": "#FBBF24", "count": 4, "min": 0, "max": 4,
                     "step": 1, "initial_count": 4, "view_mode": CounterViewMode.number, "position": 2},
                    {"name": "Crew Morale", "color": "#10B981", "count": 6, "min": 0, "max": 10,
                     "step": 1, "initial_count": 7, "view_mode": CounterViewMode.progress_bar, "position": 3},
                    {"name": "Rations (days)", "color": "#65A30D", "count": 18, "min": 0,
                     "step": 1, "initial_count": 30, "view_mode": CounterViewMode.number, "position": 4},
                    {"name": "Storm Brewing", "color": "#1E40AF", "count": 2, "min": 0, "max": 6,
                     "step": 1, "initial_count": 0, "view_mode": CounterViewMode.segmented_clock, "position": 5},
                ],
            },
            {
                "initiative_id": g3_main.id,
                "name": "Plunder Vault",
                "description": "Treasure recovered toward the Leviathan's Heart.",
                "created_by": "Finley Goldtongue",
                "counters": [
                    {"name": "Tidestones Recovered", "color": "#0EA5E9", "count": 1, "min": 0, "max": 3,
                     "step": 1, "initial_count": 0, "view_mode": CounterViewMode.progress_bar, "position": 1},
                    {"name": "Gold (doubloons)", "color": "#F59E0B", "count": 4200, "min": 0,
                     "step": 100, "initial_count": 0, "view_mode": CounterViewMode.number, "position": 2},
                ],
            },
            {
                "initiative_id": g3_navy.id,
                "name": "Navy Threat Tracker",
                "description": "How close the Imperial Navy is to catching us.",
                "created_by": "Dungeon Master",
                "counters": [
                    {"name": "Bounty Level", "color": "#DC2626", "count": 3, "min": 0, "max": 5,
                     "step": 1, "initial_count": 0, "view_mode": CounterViewMode.segmented_clock, "position": 1},
                    {"name": "Ships of the Line Sunk", "color": "#1E40AF", "count": 2, "min": 0,
                     "step": 1, "initial_count": 0, "view_mode": CounterViewMode.number, "position": 2},
                ],
            },
        ])
        await _enable_role_feature(session, [g3_main_mem, g3_navy_mem], "counters_enabled")

        # -- Calendar events --
        print("  Creating Guild 3 calendar events...")
        await _create_calendar_events(session, ids, g3, all_users, g3_tags, g3_docs, [
            {
                "initiative_id": g3_main.id,
                "title": "Session 7: The Leviathan's Maw",
                "description": "Descent into the underwater grotto.",
                "location": "Captain's quarters (Roll20)",
                "start_at": NOW + timedelta(days=1, hours=2),
                "end_at": NOW + timedelta(days=1, hours=6),
                "color": "#DC2626",
                "created_by": "Finley Goldtongue",
                "attendees": [
                    {"user": "Finley Goldtongue", "rsvp_status": RSVPStatus.accepted},
                    {"user": "Thorn Ironforge", "rsvp_status": RSVPStatus.accepted},
                    {"user": "Kael Windrunner", "rsvp_status": RSVPStatus.accepted},
                    {"user": "Aurelia Brightshield", "rsvp_status": RSVPStatus.accepted},
                    {"user": "Seraphina Dawnlight", "rsvp_status": RSVPStatus.tentative},
                ],
                "documents": ["The Shattered Seas: World Guide"],
            },
            {
                "initiative_id": g3_main.id,
                "title": "Sunday Pirate Night",
                "description": "Weekly campaign session.",
                "start_at": NOW + timedelta(days=6, hours=2),
                "end_at": NOW + timedelta(days=6, hours=5),
                "color": "#DC2626",
                "created_by": "Finley Goldtongue",
                "recurrence": {
                    "frequency": "weekly", "interval": 1,
                    "weekdays": ["su"], "ends": "never",
                },
                "attendees": [
                    {"user": "Finley Goldtongue", "rsvp_status": RSVPStatus.accepted},
                    {"user": "Kael Windrunner", "rsvp_status": RSVPStatus.accepted},
                ],
            },
            {
                "initiative_id": g3_main.id,
                "title": "Session 6: The Ironclad Falls",
                "description": "Past session — sank the HMS Ironclad.",
                "start_at": NOW - timedelta(days=7, hours=22),
                "end_at": NOW - timedelta(days=7, hours=19),
                "color": "#DC2626",
                "created_by": "Finley Goldtongue",
            },
            {
                "initiative_id": g3_navy.id,
                "title": "Naval Engagement: HMS Vengeance Pursuit",
                "description": "Cat-and-mouse with Admiral Blackwood's flagship.",
                "start_at": NOW + timedelta(days=4, hours=3),
                "end_at": NOW + timedelta(days=4, hours=6),
                "color": "#1E40AF",
                "created_by": "Dungeon Master",
                "attendees": [
                    {"user": "Dungeon Master", "rsvp_status": RSVPStatus.accepted},
                    {"user": "Finley Goldtongue", "rsvp_status": RSVPStatus.accepted},
                    {"user": "Thorn Ironforge", "rsvp_status": RSVPStatus.pending},
                ],
                "documents": ["Intelligence Report: Admiral Blackwood"],
            },
            {
                "initiative_id": g3_navy.id,
                "title": "Shore Leave (all-day)",
                "description": "Crew gets a day in Port Havoc.",
                "start_at": NOW + timedelta(days=12),
                "end_at": NOW + timedelta(days=12),
                "all_day": True,
                "color": "#FBBF24",
                "created_by": "Dungeon Master",
            },
        ])
        await _enable_role_feature(session, [g3_main_mem, g3_navy_mem], "events_enabled")

        # -- Custom properties --
        print("  Creating Guild 3 property definitions + values...")
        g3_main_props = await _create_property_definitions(session, ids, g3_main, [
            {"name": "Arc", "type": PropertyType.select, "position": 1.0, "color": "#DC2626",
             "options": [
                 {"value": "shattered_seas", "label": "Shattered Seas"},
                 {"value": "tidestone_hunt", "label": "Tidestone Hunt", "color": "#0EA5E9"},
                 {"value": "leviathan_finale", "label": "Leviathan Finale", "color": "#7F1D1D"},
             ]},
            {"name": "Crew Reward (gold)", "type": PropertyType.number, "position": 2.0, "color": "#F59E0B"},
            {"name": "Quest Hooks", "type": PropertyType.multi_select, "position": 3.0,
             "options": [
                 {"value": "treasure", "label": "Treasure", "color": "#F59E0B"},
                 {"value": "rescue", "label": "Rescue", "color": "#10B981"},
                 {"value": "revenge", "label": "Revenge", "color": "#DC2626"},
                 {"value": "exploration", "label": "Exploration", "color": "#0EA5E9"},
             ]},
            {"name": "Spoilers Allowed", "type": PropertyType.checkbox, "position": 4.0},
            {"name": "Quest Giver", "type": PropertyType.user_reference, "position": 5.0},
            {"name": "Map Link", "type": PropertyType.url, "position": 6.0},
        ])
        t_leviathan_id = g3_tasks["Defeat the Leviathan guardian"].id
        t_decipher_id = g3_tasks["Decipher the Leviathan Map"].id
        t_collect_id = g3_tasks["Collect the three Tidestones"].id
        doc_world_g3_id = g3_docs["The Shattered Seas: World Guide"].id
        doc_crew_g3_id = g3_docs["Crew Manifest: The Crimson Maiden"].id

        await _attach_property_values(session, ids, g3_main_props["Arc"], [
            ("task", t_leviathan_id, "leviathan_finale"),
            ("task", t_decipher_id, "tidestone_hunt"),
            ("task", t_collect_id, "tidestone_hunt"),
        ])
        await _attach_property_values(session, ids, g3_main_props["Crew Reward (gold)"], [
            ("task", t_leviathan_id, Decimal("25000")),
            ("task", t_collect_id, Decimal("9000")),
        ])
        await _attach_property_values(session, ids, g3_main_props["Quest Hooks"], [
            ("task", t_leviathan_id, ["treasure", "revenge"]),
            ("task", t_decipher_id, ["treasure", "exploration"]),
        ])
        await _attach_property_values(session, ids, g3_main_props["Spoilers Allowed"], [
            ("document", doc_world_g3_id, True),
            ("document", doc_crew_g3_id, False),
        ])
        await _attach_property_values(session, ids, g3_main_props["Quest Giver"], [
            ("task", t_decipher_id, finley.id),
        ])
        await _attach_property_values(session, ids, g3_main_props["Map Link"], [
            ("document", doc_world_g3_id, "https://example.com/maps/shattered-seas"),
        ])

        g3_navy_props = await _create_property_definitions(session, ids, g3_navy, [
            {"name": "Threat Level", "type": PropertyType.select, "position": 1.0,
             "options": [
                 {"value": "frigate", "label": "Frigate", "color": "#10B981"},
                 {"value": "ship_of_the_line", "label": "Ship of the Line", "color": "#F59E0B"},
                 {"value": "flagship", "label": "Flagship", "color": "#DC2626"},
             ]},
            {"name": "Engagement Date", "type": PropertyType.date, "position": 2.0},
        ])
        t_evade_id = g3_tasks["Evade the HMS Vengeance"].id
        await _attach_property_values(session, ids, g3_navy_props["Threat Level"], [
            ("task", t_evade_id, "flagship"),
        ])
        await _attach_property_values(session, ids, g3_navy_props["Engagement Date"], [
            ("task", t_evade_id, (NOW + timedelta(days=4)).date()),
            ])

        # Commit guild 3's data — each guild section is committed as it completes
        # (its writes are routed into that guild's schema).
        await session.commit()

    _save_state(ids.data)

    total_tasks = len(ids.data["tasks"])
    total_docs = len(ids.data["documents"])
    total_users = len(ids.data["users"])
    total_projects = len(ids.data["projects"])

    print("\nDone! Dev data seeded successfully.")
    print(f"  {total_users} users (password: changeme)")
    print(f"  3 guilds, {len(ids.data['initiatives'])} initiatives")
    print(f"  {total_projects} projects, {total_tasks} tasks")
    print(f"  {total_docs} documents, {len(ids.data['tags'])} tags")
    print(f"  {len(ids.data['queues'])} queues, {len(ids.data['queue_items'])} queue items")
    print(
        f"  {len(ids.data['counter_groups'])} counter groups, "
        f"{len(ids.data['counters'])} counters"
    )
    print(
        f"  {len(ids.data['calendar_events'])} calendar events, "
        f"{len(ids.data['calendar_event_attendees'])} attendees"
    )
    total_property_values = (
        len(ids.data["task_property_values"])
        + len(ids.data["document_property_values"])
        + len(ids.data["calendar_event_property_values"])
    )
    print(
        f"  {len(ids.data['property_definitions'])} property definitions, "
        f"{total_property_values} property values"
    )
    print(f"  {len(ids.data['comments'])} comments")
    print(f"  {len(ids.data['project_favorites'])} favorites, {len(ids.data['document_links'])} doc links")
    print(f"\n  Superuser login: {settings.FIRST_SUPERUSER_EMAIL} / {settings.FIRST_SUPERUSER_PASSWORD}")
    print("  All other users: user1@example.com .. user8@example.com / changeme")


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------

async def clean() -> None:
    """Remove all seeded dev data.

    Under schema-per-guild the guild-scoped data lives in per-guild schemas, so
    cleanup just drops every guild_<id> schema + role and wipes the shared rows
    (users, guilds) — no dependency-ordered row deletes. This also recovers a
    half-broken state. Run dev-migrate afterwards to recreate the primary guild +
    superuser.
    """
    import contextlib

    import app.db.session as db_session

    print("Cleaning up dev data (dropping guild schemas + wiping shared rows)...")
    async with db_session.provisioning_engine.begin() as conn:
        await conn.exec_driver_sql("SET lock_timeout = '10s'")
        schemas = [
            s for (s,) in (
                await conn.exec_driver_sql(
                    "SELECT nspname FROM pg_namespace WHERE nspname ~ '^guild_[0-9]+$'"
                )
            ).all()
        ]
        for schema in schemas:
            await conn.exec_driver_sql(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        roles = [
            r for (r,) in (
                await conn.exec_driver_sql(
                    "SELECT rolname FROM pg_roles WHERE rolname ~ '^guild_[0-9]+(_ro)?$'"
                )
            ).all()
        ]
        await conn.exec_driver_sql("TRUNCATE TABLE users, guilds RESTART IDENTITY CASCADE")

    # Drop guild roles best-effort, each in its own transaction: guild roles are
    # cluster-global, so one a co-located test DB also uses owns objects in *that*
    # database and can't be dropped here — that must not abort the cleanup.
    dropped = 0
    for role in roles:
        with contextlib.suppress(Exception):
            async with db_session.provisioning_engine.begin() as rconn:
                await rconn.exec_driver_sql("SET lock_timeout = '5s'")
                await rconn.exec_driver_sql(f'DROP OWNED BY "{role}"')
                await rconn.exec_driver_sql(f'DROP ROLE IF EXISTS "{role}"')
            dropped += 1
    print(f"  Dropped {len(schemas)} guild schema(s) + {dropped}/{len(roles)} role(s); wiped users + guilds")

    STATE_FILE.unlink(missing_ok=True)
    print("Done! All dev data removed. Run dev-migrate to recreate the primary guild + superuser.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if "--clean" in sys.argv:
        asyncio.run(clean())
    else:
        asyncio.run(seed())
