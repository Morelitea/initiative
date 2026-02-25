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
from app.db.session import AdminSessionLocal  # noqa: E402
from app.models.comment import Comment  # noqa: E402
from app.models.document import (  # noqa: E402
    Document,
    DocumentLink,
    DocumentPermission,
    DocumentPermissionLevel,
    ProjectDocument,
)
from app.models.guild import Guild, GuildMembership, GuildRole  # noqa: E402
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
from app.models.project_activity import ProjectFavorite, RecentProjectView  # noqa: E402
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
    """Generate 10 000 TTRPG-themed task defs for the mega dungeon project."""
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
    for i in range(1, 10_001):
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
            "recent_project_views": [],
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
) -> tuple[Initiative, InitiativeRoleModel, InitiativeRoleModel]:
    """Create an initiative with roles and members."""
    initiative = Initiative(
        guild_id=guild.id,
        name=name,
        description=description,
        color=color,
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
        view = RecentProjectView(
            user_id=user.id,
            project_id=project.id,
            guild_id=guild.id,
        )
        session.add(view)
        ids.add("recent_project_views", {"user_id": user.id, "project_id": project.id})
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
        async with session.begin():
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

            # Add members to primary guild
            await _add_guild_members(
                session, ids, g1,
                [dm, thorn, elara, vex, sera],
                admin_users=[dm],
            )

            # Find default initiative
            result = await session.exec(
                select(Initiative).where(
                    Initiative.guild_id == g1_id,
                    Initiative.is_default == True,  # noqa: E712
                )
            )
            g1_default_init = result.one()

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
            )

            g2_side, g2_side_pm, g2_side_mem = await _create_initiative(
                session, ids,
                guild=g2,
                name="Side Missions: Fringe Space",
                description="One-shots and side adventures in the frontier sectors",
                color="#F59E0B",
                pm_user=finley,
                member_users=[kael, aurelia, vex],
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
            )

            g3_navy, g3_navy_pm, g3_navy_mem = await _create_initiative(
                session, ids,
                guild=g3,
                name="Royal Navy Conflicts",
                description="Encounters and battles with the Imperial Navy",
                color="#1E40AF",
                pm_user=dm,
                member_users=[finley, thorn, kael],
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

        # Transaction committed by context manager

    _save_state(ids.data)

    total_tasks = len(ids.data["tasks"])
    total_docs = len(ids.data["documents"])
    total_users = len(ids.data["users"])
    total_projects = len(ids.data["projects"])

    print(f"\nDone! Dev data seeded successfully.")
    print(f"  {total_users} users (password: changeme)")
    print(f"  3 guilds, {len(ids.data['initiatives'])} initiatives")
    print(f"  {total_projects} projects, {total_tasks} tasks")
    print(f"  {total_docs} documents, {len(ids.data['tags'])} tags")
    print(f"  {len(ids.data['comments'])} comments")
    print(f"  {len(ids.data['project_favorites'])} favorites, {len(ids.data['document_links'])} doc links")
    print(f"\n  Superuser login: {settings.FIRST_SUPERUSER_EMAIL} / {settings.FIRST_SUPERUSER_PASSWORD}")
    print(f"  All other users: user1@example.com .. user8@example.com / changeme")


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------

async def clean() -> None:
    state = _load_state()
    if state is None:
        print("No seed state file found. Nothing to clean.")
        return

    print("Cleaning up seeded dev data...")

    async with AdminSessionLocal() as session:
        async with session.begin():
            # Delete in reverse dependency order.
            # flush() between groups ensures SQL executes in the right order
            # so FK constraints are satisfied.

            # Comments
            for cid in state.get("comments", []):
                obj = await session.get(Comment, cid)
                if obj:
                    await session.delete(obj)
            await session.flush()
            print("  Removed comments")

            # Document links (composite key)
            for dl in state.get("document_links", []):
                obj = await session.get(
                    DocumentLink,
                    (dl["source_document_id"], dl["target_document_id"]),
                )
                if obj:
                    await session.delete(obj)
            await session.flush()
            print("  Removed document links")

            # Document tags (composite key)
            for dt in state.get("document_tags", []):
                obj = await session.get(DocumentTag, (dt["document_id"], dt["tag_id"]))
                if obj:
                    await session.delete(obj)
            await session.flush()
            print("  Removed document tags")

            # Subtasks
            for sid in state.get("subtasks", []):
                obj = await session.get(Subtask, sid)
                if obj:
                    await session.delete(obj)
            await session.flush()
            print("  Removed subtasks")

            # Task assignees (composite key)
            for ta in state.get("task_assignees", []):
                obj = await session.get(TaskAssignee, (ta["task_id"], ta["user_id"]))
                if obj:
                    await session.delete(obj)
            await session.flush()
            print("  Removed task assignees")

            # Task tags (composite key)
            for tt in state.get("task_tags", []):
                obj = await session.get(TaskTag, (tt["task_id"], tt["tag_id"]))
                if obj:
                    await session.delete(obj)
            await session.flush()
            print("  Removed task tags")

            # Project tags (composite key)
            for pt in state.get("project_tags", []):
                obj = await session.get(ProjectTag, (pt["project_id"], pt["tag_id"]))
                if obj:
                    await session.delete(obj)
            await session.flush()
            print("  Removed project tags")

            # Tasks
            for tid in state.get("tasks", []):
                obj = await session.get(Task, tid)
                if obj:
                    await session.delete(obj)
            await session.flush()
            print("  Removed tasks")

            # Task statuses
            for sid in state.get("task_statuses", []):
                obj = await session.get(TaskStatus, sid)
                if obj:
                    await session.delete(obj)
            await session.flush()
            print("  Removed task statuses")

            # Project favorites (composite key)
            for pf in state.get("project_favorites", []):
                obj = await session.get(
                    ProjectFavorite, (pf["user_id"], pf["project_id"])
                )
                if obj:
                    await session.delete(obj)
            await session.flush()
            print("  Removed project favorites")

            # Recent project views (composite key)
            for rv in state.get("recent_project_views", []):
                obj = await session.get(
                    RecentProjectView, (rv["user_id"], rv["project_id"])
                )
                if obj:
                    await session.delete(obj)
            await session.flush()
            print("  Removed recent project views")

            # Project documents (composite key)
            for pd in state.get("project_documents", []):
                obj = await session.get(
                    ProjectDocument, (pd["project_id"], pd["document_id"])
                )
                if obj:
                    await session.delete(obj)
            await session.flush()
            print("  Removed project documents")

            # Document permissions (composite key)
            for dp in state.get("document_permissions", []):
                obj = await session.get(
                    DocumentPermission, (dp["document_id"], dp["user_id"])
                )
                if obj:
                    await session.delete(obj)
            await session.flush()
            print("  Removed document permissions")

            # Documents
            for did in state.get("documents", []):
                obj = await session.get(Document, did)
                if obj:
                    await session.delete(obj)
            await session.flush()
            print("  Removed documents")

            # Project permissions (composite key)
            for pp in state.get("project_permissions", []):
                obj = await session.get(
                    ProjectPermission, (pp["project_id"], pp["user_id"])
                )
                if obj:
                    await session.delete(obj)
            await session.flush()
            print("  Removed project permissions")

            # Projects
            for pid in state.get("projects", []):
                obj = await session.get(Project, pid)
                if obj:
                    await session.delete(obj)
            await session.flush()
            print("  Removed projects")

            # Initiative members (composite key)
            for im in state.get("initiative_members", []):
                obj = await session.get(
                    InitiativeMember, (im["initiative_id"], im["user_id"])
                )
                if obj:
                    await session.delete(obj)
            await session.flush()
            print("  Removed initiative members")

            # Initiative role permissions (composite key)
            for irp in state.get("initiative_role_permissions", []):
                obj = await session.get(
                    InitiativeRolePermission,
                    (irp["initiative_role_id"], irp["permission_key"]),
                )
                if obj:
                    await session.delete(obj)
            await session.flush()
            print("  Removed initiative role permissions")

            # Initiative roles
            for rid in state.get("initiative_roles", []):
                obj = await session.get(InitiativeRoleModel, rid)
                if obj:
                    await session.delete(obj)
            await session.flush()
            print("  Removed initiative roles")

            # Initiatives
            for iid in state.get("initiatives", []):
                obj = await session.get(Initiative, iid)
                if obj:
                    await session.delete(obj)
            await session.flush()
            print("  Removed initiatives")

            # Tags
            for tid in state.get("tags", []):
                obj = await session.get(Tag, tid)
                if obj:
                    await session.delete(obj)
            await session.flush()
            print("  Removed tags")

            # Guild settings
            for gs_id in state.get("guild_settings", []):
                obj = await session.get(GuildSetting, gs_id)
                if obj:
                    await session.delete(obj)
            await session.flush()
            print("  Removed guild settings")

            # Guild memberships (composite key)
            for gm in state.get("guild_memberships", []):
                obj = await session.get(
                    GuildMembership, (gm["guild_id"], gm["user_id"])
                )
                if obj:
                    await session.delete(obj)
            await session.flush()
            print("  Removed guild memberships")

            # Guilds — must be flushed before users (guilds.created_by_user_id FK)
            for gid in state.get("guilds", []):
                obj = await session.get(Guild, gid)
                if obj:
                    await session.delete(obj)
            await session.flush()
            print("  Removed guilds")

            # Restore modified user settings before deletion
            for us in state.get("user_settings_modified", []):
                user = await session.get(User, us["user_id"])
                if user:
                    for key, value in us["original"].items():
                        setattr(user, key, value)
                    session.add(user)
            await session.flush()
            print("  Restored user settings")

            # Users
            for uid in state.get("users", []):
                obj = await session.get(User, uid)
                if obj:
                    await session.delete(obj)
            await session.flush()
            print("  Removed users")

        # Transaction committed

    STATE_FILE.unlink(missing_ok=True)
    print("Done! All seeded data removed.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if "--clean" in sys.argv:
        asyncio.run(clean())
    else:
        asyncio.run(seed())
