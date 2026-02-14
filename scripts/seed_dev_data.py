"""TTRPG-themed dev data seeder for Initiative.

Usage:
    python seed_dev_data.py          # Create test data
    python seed_dev_data.py --clean  # Remove seeded test data

Designed to run from the backend/ directory (CWD) so app imports resolve.
Saves created IDs to .vscode/.dev_seed_ids.json for cleanup.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime, timezone
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

from app.db.session import AdminSessionLocal  # noqa: E402
from app.models.comment import Comment  # noqa: E402
from app.models.document import (  # noqa: E402
    Document,
    DocumentPermission,
    DocumentPermissionLevel,
    ProjectDocument,
)
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
from app.models.tag import ProjectTag, Tag, TaskTag  # noqa: E402
from app.models.task import (  # noqa: E402
    Subtask,
    Task,
    TaskAssignee,
    TaskPriority,
    TaskStatus,
    TaskStatusCategory,
)
from app.models.user import User  # noqa: E402
from app.services.guilds import get_primary_guild  # noqa: E402
from app.services.initiatives import create_builtin_roles  # noqa: E402
from app.services.task_statuses import ensure_default_statuses  # noqa: E402

STATE_FILE = Path(__file__).resolve().parent.parent / ".vscode" / ".dev_seed_ids.json"



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
    """Find the superuser created by init_db.

    Reads FIRST_SUPERUSER_EMAIL from the environment so manual invocations
    work even when .env uses a different email than the VS Code wrapper scripts.
    """
    email = os.environ.get("FIRST_SUPERUSER_EMAIL", "user@example.com")
    result = await session.exec(
        select(User).where(User.email == email)
    )
    user = result.one_or_none()
    if user is None:
        print(f"ERROR: Superuser {email} not found.")
        print("  Make sure init_db has run (dev:migrate task).")
        print("  Or set FIRST_SUPERUSER_EMAIL to match your .env config.")
        sys.exit(1)
    return user


# ---------------------------------------------------------------------------
# Seed
# ---------------------------------------------------------------------------

async def seed() -> None:
    if _load_state() is not None:
        print("Seed data already exists (.vscode/.dev_seed_ids.json found).")
        print("  Run with --clean first to remove existing data.")
        return

    print("Seeding TTRPG dev data...")
    ids: dict[str, list] = {
        "initiatives": [],
        "initiative_roles": [],
        "initiative_role_permissions": [],
        "initiative_members": [],
        "projects": [],
        "project_permissions": [],
        "task_statuses": [],
        "tasks": [],
        "subtasks": [],
        "task_assignees": [],
        "documents": [],
        "document_permissions": [],
        "project_documents": [],
        "tags": [],
        "task_tags": [],
        "project_tags": [],
        "comments": [],
    }

    async with AdminSessionLocal() as session:
        async with session.begin():
            # -- Discover existing entities created by init_db --
            user = await _find_superuser(session)
            guild = await get_primary_guild(session)
            guild_id = guild.id
            user_id = user.id

            # Find the Default Initiative (created by init_db)
            result = await session.exec(
                select(Initiative).where(
                    Initiative.guild_id == guild_id,
                    Initiative.is_default == True,  # noqa: E712
                )
            )
            default_initiative = result.one_or_none()
            if default_initiative is None:
                print("ERROR: Default Initiative not found. Run init_db first.")
                sys.exit(1)

            # ---------------------------------------------------------------
            # Initiatives
            # ---------------------------------------------------------------
            print("  Creating initiatives...")
            strahd = Initiative(
                guild_id=guild_id,
                name="Campaign: Curse of Strahd",
                description="A gothic horror adventure in the demiplane of Barovia",
                color="#7C3AED",
            )
            session.add(strahd)
            await session.flush()
            ids["initiatives"].append(strahd.id)

            lmop = Initiative(
                guild_id=guild_id,
                name="Campaign: Lost Mine of Phandelver",
                description="A classic introductory adventure in the Sword Coast",
                color="#059669",
            )
            session.add(lmop)
            await session.flush()
            ids["initiatives"].append(lmop.id)

            # Create built-in roles for new initiatives
            strahd_pm, strahd_member = await create_builtin_roles(
                session, initiative_id=strahd.id
            )
            ids["initiative_roles"].extend([strahd_pm.id, strahd_member.id])

            lmop_pm, lmop_member = await create_builtin_roles(
                session, initiative_id=lmop.id
            )
            ids["initiative_roles"].extend([lmop_pm.id, lmop_member.id])

            # Track role permissions created by create_builtin_roles
            for role in [strahd_pm, strahd_member, lmop_pm, lmop_member]:
                result = await session.exec(
                    select(InitiativeRolePermission).where(
                        InitiativeRolePermission.initiative_role_id == role.id
                    )
                )
                for perm in result.all():
                    ids["initiative_role_permissions"].append(
                        {"initiative_role_id": perm.initiative_role_id, "permission_key": perm.permission_key}
                    )

            # Add superuser as PM in both new initiatives
            for init_obj, pm_role in [
                (strahd, strahd_pm),
                (lmop, lmop_pm),
            ]:
                member = InitiativeMember(
                    initiative_id=init_obj.id,
                    user_id=user_id,
                    guild_id=guild_id,
                    role_id=pm_role.id,
                )
                session.add(member)
                ids["initiative_members"].append(
                    {"initiative_id": init_obj.id, "user_id": user_id}
                )
            await session.flush()

            # ---------------------------------------------------------------
            # Projects
            # ---------------------------------------------------------------
            print("  Creating projects...")
            barovia = Project(
                guild_id=guild_id,
                name="Barovia Arc",
                icon="\U0001F9DB",  # vampire emoji
                description="The main horror campaign storyline through Castle Ravenloft",
                owner_id=user_id,
                initiative_id=strahd.id,
            )
            session.add(barovia)

            phandalin = Project(
                guild_id=guild_id,
                name="Phandalin Adventures",
                icon="\u2694\uFE0F",  # crossed swords
                description="Classic starter campaign in the Sword Coast region",
                owner_id=user_id,
                initiative_id=lmop.id,
            )
            session.add(phandalin)

            session_zero = Project(
                guild_id=guild_id,
                name="Session Zero & Planning",
                icon="\U0001F4CB",  # clipboard
                description="Meta-campaign logistics and session planning",
                owner_id=user_id,
                initiative_id=default_initiative.id,
            )
            session.add(session_zero)
            await session.flush()

            for proj in [barovia, phandalin, session_zero]:
                ids["projects"].append(proj.id)
                # Owner permission
                perm = ProjectPermission(
                    project_id=proj.id,
                    user_id=user_id,
                    guild_id=guild_id,
                    level=ProjectPermissionLevel.owner,
                )
                session.add(perm)
                ids["project_permissions"].append(
                    {"project_id": proj.id, "user_id": user_id}
                )
            await session.flush()

            # ---------------------------------------------------------------
            # Task Statuses (use the service to create defaults)
            # ---------------------------------------------------------------
            print("  Creating task statuses...")
            status_map: dict[int, dict[str, TaskStatus]] = {}
            for proj in [barovia, phandalin, session_zero]:
                statuses = await ensure_default_statuses(session, proj.id)
                cat_map = {}
                for s in statuses:
                    cat_map[s.category] = s
                    ids["task_statuses"].append(s.id)
                status_map[proj.id] = cat_map
            await session.flush()

            # ---------------------------------------------------------------
            # Tasks
            # ---------------------------------------------------------------
            print("  Creating tasks...")

            task_defs = [
                # Barovia Arc
                {
                    "project": barovia,
                    "title": "Defeat Strahd von Zarovich",
                    "description": "The vampire lord must be destroyed to free Barovia from his curse.",
                    "priority": TaskPriority.urgent,
                    "category": TaskStatusCategory.backlog,
                },
                {
                    "project": barovia,
                    "title": "Survive the Death House",
                    "description": "Navigate the haunted mansion on the outskirts of the Village of Barovia.",
                    "priority": TaskPriority.high,
                    "category": TaskStatusCategory.in_progress,
                    "subtasks": [
                        "Explore the basement",
                        "Find the hidden altar",
                        "Escape before the house collapses",
                    ],
                    "assign": True,
                },
                {
                    "project": barovia,
                    "title": "Find the Sunsword in the Amber Temple",
                    "description": "The legendary weapon is key to defeating the Dark Lord.",
                    "priority": TaskPriority.high,
                    "category": TaskStatusCategory.todo,
                },
                {
                    "project": barovia,
                    "title": "Negotiate with the Vistani caravan",
                    "description": "The Vistani hold secrets about Strahd and safe passage through the mists.",
                    "priority": TaskPriority.medium,
                    "category": TaskStatusCategory.done,
                },
                # Phandalin Adventures
                {
                    "project": phandalin,
                    "title": "Rescue Gundren Rockseeker",
                    "description": "The dwarf was kidnapped on the road to Phandalin. Find him!",
                    "priority": TaskPriority.urgent,
                    "category": TaskStatusCategory.in_progress,
                    "assign": True,
                },
                {
                    "project": phandalin,
                    "title": "Clear the Redbrand Hideout",
                    "description": "The Redbrand ruffians terrorize Phandalin from their base under Tresendar Manor.",
                    "priority": TaskPriority.high,
                    "category": TaskStatusCategory.done,
                },
                {
                    "project": phandalin,
                    "title": "Defeat the Black Spider in Wave Echo Cave",
                    "description": "Nezznar the Black Spider seeks the Forge of Spells.",
                    "priority": TaskPriority.high,
                    "category": TaskStatusCategory.backlog,
                    "subtasks": [
                        "Find the entrance to Wave Echo Cave",
                        "Navigate the mine tunnels",
                        "Confront Nezznar",
                    ],
                },
                {
                    "project": phandalin,
                    "title": "Escort merchant supplies to Phandalin",
                    "description": "Deliver the wagon of supplies safely along the Triboar Trail.",
                    "priority": TaskPriority.medium,
                    "category": TaskStatusCategory.todo,
                },
                # Session Zero & Planning
                {
                    "project": session_zero,
                    "title": "Finalize character backstories",
                    "description": "All players need to submit their character backstories before Session 1.",
                    "priority": TaskPriority.medium,
                    "category": TaskStatusCategory.done,
                },
                {
                    "project": session_zero,
                    "title": "Schedule Session 4",
                    "description": "Find a date that works for all five players.",
                    "priority": TaskPriority.low,
                    "category": TaskStatusCategory.todo,
                },
                {
                    "project": session_zero,
                    "title": "Review leveling rules for Tier 2",
                    "description": "Characters approaching level 5 — review multiclassing and feat rules.",
                    "priority": TaskPriority.low,
                    "category": TaskStatusCategory.backlog,
                },
                {
                    "project": session_zero,
                    "title": "Prepare battle maps for next session",
                    "description": "Print or prepare VTT maps for the upcoming dungeon crawl.",
                    "priority": TaskPriority.medium,
                    "category": TaskStatusCategory.in_progress,
                    "assign": True,
                },
            ]

            created_tasks: dict[str, Task] = {}
            for i, td in enumerate(task_defs):
                proj = td["project"]
                status = status_map[proj.id][td["category"]]
                task = Task(
                    guild_id=guild_id,
                    project_id=proj.id,
                    task_status_id=status.id,
                    title=td["title"],
                    description=td.get("description"),
                    priority=td["priority"],
                    sort_order=float(i),
                )
                session.add(task)
                await session.flush()
                ids["tasks"].append(task.id)
                created_tasks[td["title"]] = task

                # Subtasks
                for pos, content in enumerate(td.get("subtasks", [])):
                    sub = Subtask(
                        guild_id=guild_id,
                        task_id=task.id,
                        content=content,
                        position=pos,
                    )
                    session.add(sub)
                    await session.flush()
                    ids["subtasks"].append(sub.id)

                # Assignee
                if td.get("assign"):
                    assignee = TaskAssignee(
                        task_id=task.id,
                        user_id=user_id,
                        guild_id=guild_id,
                    )
                    session.add(assignee)
                    ids["task_assignees"].append(
                        {"task_id": task.id, "user_id": user_id}
                    )

            await session.flush()

            # ---------------------------------------------------------------
            # Documents
            # ---------------------------------------------------------------
            print("  Creating documents...")

            doc_barovia = Document(
                guild_id=guild_id,
                initiative_id=strahd.id,
                title="Campaign Setting: The Land of Barovia",
                content={
                    "root": {
                        "children": [
                            {
                                "children": [
                                    {
                                        "text": "Barovia is a demiplane of dread, shrouded in perpetual mist. "
                                        "The land is ruled by Count Strahd von Zarovich, a vampire lord "
                                        "who has cursed this realm for centuries. No one enters or leaves "
                                        "without Strahd's permission. The sun never truly shines here, and "
                                        "the people live in constant fear of the creatures that stalk the night.",
                                        "type": "text",
                                    }
                                ],
                                "type": "paragraph",
                            }
                        ],
                        "type": "root",
                    }
                },
                created_by_id=user_id,
                updated_by_id=user_id,
            )
            session.add(doc_barovia)

            doc_npcs = Document(
                guild_id=guild_id,
                initiative_id=lmop.id,
                title="NPC Compendium",
                content={
                    "root": {
                        "children": [
                            {
                                "children": [
                                    {
                                        "text": "Key NPCs: Gundren Rockseeker (quest giver), "
                                        "Sildar Hallwinter (Lords' Alliance agent), "
                                        "Sister Garaele (Harper contact in Phandalin), "
                                        "Nezznar the Black Spider (main antagonist), "
                                        "Glasstaff/Iarno Albrek (Redbrand leader).",
                                        "type": "text",
                                    }
                                ],
                                "type": "paragraph",
                            }
                        ],
                        "type": "root",
                    }
                },
                created_by_id=user_id,
                updated_by_id=user_id,
            )
            session.add(doc_npcs)

            doc_recap = Document(
                guild_id=guild_id,
                initiative_id=default_initiative.id,
                title="Session 1 Recap: Into the Mists",
                content={
                    "root": {
                        "children": [
                            {
                                "children": [
                                    {
                                        "text": "The party received a mysterious letter and traveled to the "
                                        "village of Barovia. After surviving the Death House, they met "
                                        "Ismark and Ireena, and learned of Strahd's obsession. The session "
                                        "ended with the party heading toward the church in the village center.",
                                        "type": "text",
                                    }
                                ],
                                "type": "paragraph",
                            }
                        ],
                        "type": "root",
                    }
                },
                created_by_id=user_id,
                updated_by_id=user_id,
            )
            session.add(doc_recap)
            await session.flush()

            for doc in [doc_barovia, doc_npcs, doc_recap]:
                ids["documents"].append(doc.id)
                # Owner permission
                dperm = DocumentPermission(
                    document_id=doc.id,
                    user_id=user_id,
                    guild_id=guild_id,
                    level=DocumentPermissionLevel.owner,
                )
                session.add(dperm)
                ids["document_permissions"].append(
                    {"document_id": doc.id, "user_id": user_id}
                )

            # Link documents to projects
            project_doc_links = [
                (barovia.id, doc_barovia.id),
                (phandalin.id, doc_npcs.id),
                (session_zero.id, doc_recap.id),
            ]
            for proj_id, doc_id in project_doc_links:
                pd = ProjectDocument(
                    project_id=proj_id,
                    document_id=doc_id,
                    guild_id=guild_id,
                    attached_by_id=user_id,
                )
                session.add(pd)
                ids["project_documents"].append(
                    {"project_id": proj_id, "document_id": doc_id}
                )
            await session.flush()

            # ---------------------------------------------------------------
            # Tags
            # ---------------------------------------------------------------
            print("  Creating tags...")

            tag_defs = [
                ("quest", "#EF4444"),
                ("NPC", "#8B5CF6"),
                ("lore", "#F59E0B"),
                ("combat", "#DC2626"),
                ("roleplay", "#3B82F6"),
            ]
            tags: dict[str, Tag] = {}
            for name, color in tag_defs:
                tag = Tag(guild_id=guild_id, name=name, color=color)
                session.add(tag)
                await session.flush()
                tags[name] = tag
                ids["tags"].append(tag.id)

            # Link tags to tasks
            task_tag_links = [
                ("Defeat Strahd von Zarovich", ["quest", "combat"]),
                ("Survive the Death House", ["quest", "combat"]),
                ("Find the Sunsword in the Amber Temple", ["quest", "lore"]),
                ("Negotiate with the Vistani caravan", ["NPC", "roleplay"]),
                ("Rescue Gundren Rockseeker", ["quest", "NPC"]),
                ("Clear the Redbrand Hideout", ["quest", "combat"]),
                ("Defeat the Black Spider in Wave Echo Cave", ["quest", "combat"]),
                ("Escort merchant supplies to Phandalin", ["quest", "roleplay"]),
            ]
            for task_title, tag_names in task_tag_links:
                task = created_tasks.get(task_title)
                if task is None:
                    continue
                for tn in tag_names:
                    tt = TaskTag(task_id=task.id, tag_id=tags[tn].id)
                    session.add(tt)
                    ids["task_tags"].append(
                        {"task_id": task.id, "tag_id": tags[tn].id}
                    )

            # Link tags to projects
            project_tag_links = [
                (barovia.id, ["combat", "lore"]),
                (phandalin.id, ["quest", "NPC"]),
                (session_zero.id, ["roleplay"]),
            ]
            for proj_id, tag_names in project_tag_links:
                for tn in tag_names:
                    pt = ProjectTag(project_id=proj_id, tag_id=tags[tn].id)
                    session.add(pt)
                    ids["project_tags"].append(
                        {"project_id": proj_id, "tag_id": tags[tn].id}
                    )
            await session.flush()

            # ---------------------------------------------------------------
            # Comments
            # ---------------------------------------------------------------
            print("  Creating comments...")

            comment_defs = [
                {
                    "task_title": "Defeat Strahd von Zarovich",
                    "content": "We need the Sunsword AND the Holy Symbol before attempting this.",
                },
                {
                    "task_title": "Rescue Gundren Rockseeker",
                    "content": "Last seen heading to Cragmaw Castle with the map.",
                },
                {
                    "task_title": "Clear the Redbrand Hideout",
                    "content": "Completed! The party found Glasstaff's letters.",
                },
            ]
            for cd in comment_defs:
                task = created_tasks.get(cd["task_title"])
                if task is None:
                    continue
                comment = Comment(
                    guild_id=guild_id,
                    content=cd["content"],
                    author_id=user_id,
                    task_id=task.id,
                )
                session.add(comment)
                await session.flush()
                ids["comments"].append(comment.id)

            # Document comment
            doc_comment = Comment(
                guild_id=guild_id,
                content="Don't forget \u2014 Barovia is a demiplane, no escape without defeating Strahd.",
                author_id=user_id,
                document_id=doc_barovia.id,
            )
            session.add(doc_comment)
            await session.flush()
            ids["comments"].append(doc_comment.id)

        # Transaction committed by context manager

    _save_state(ids)
    print("Done! TTRPG dev data seeded successfully.")
    email = os.environ.get("FIRST_SUPERUSER_EMAIL", "user@example.com")
    print(f"  Login: {email} / abc123")


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
            # Delete in reverse dependency order

            # Comments
            for cid in state.get("comments", []):
                obj = await session.get(Comment, cid)
                if obj:
                    await session.delete(obj)
            print("  Removed comments")

            # Subtasks
            for sid in state.get("subtasks", []):
                obj = await session.get(Subtask, sid)
                if obj:
                    await session.delete(obj)
            print("  Removed subtasks")

            # Task assignees (composite key)
            for ta in state.get("task_assignees", []):
                obj = await session.get(TaskAssignee, (ta["task_id"], ta["user_id"]))
                if obj:
                    await session.delete(obj)
            print("  Removed task assignees")

            # Task tags (composite key)
            for tt in state.get("task_tags", []):
                obj = await session.get(TaskTag, (tt["task_id"], tt["tag_id"]))
                if obj:
                    await session.delete(obj)
            print("  Removed task tags")

            # Project tags (composite key)
            for pt in state.get("project_tags", []):
                obj = await session.get(ProjectTag, (pt["project_id"], pt["tag_id"]))
                if obj:
                    await session.delete(obj)
            print("  Removed project tags")

            # Tasks
            for tid in state.get("tasks", []):
                obj = await session.get(Task, tid)
                if obj:
                    await session.delete(obj)
            print("  Removed tasks")

            # Task statuses
            for sid in state.get("task_statuses", []):
                obj = await session.get(TaskStatus, sid)
                if obj:
                    await session.delete(obj)
            print("  Removed task statuses")

            # Project documents (composite key)
            for pd in state.get("project_documents", []):
                obj = await session.get(
                    ProjectDocument, (pd["project_id"], pd["document_id"])
                )
                if obj:
                    await session.delete(obj)
            print("  Removed project documents")

            # Document permissions (composite key)
            for dp in state.get("document_permissions", []):
                obj = await session.get(
                    DocumentPermission, (dp["document_id"], dp["user_id"])
                )
                if obj:
                    await session.delete(obj)
            print("  Removed document permissions")

            # Documents
            for did in state.get("documents", []):
                obj = await session.get(Document, did)
                if obj:
                    await session.delete(obj)
            print("  Removed documents")

            # Project permissions (composite key)
            for pp in state.get("project_permissions", []):
                obj = await session.get(
                    ProjectPermission, (pp["project_id"], pp["user_id"])
                )
                if obj:
                    await session.delete(obj)
            print("  Removed project permissions")

            # Projects
            for pid in state.get("projects", []):
                obj = await session.get(Project, pid)
                if obj:
                    await session.delete(obj)
            print("  Removed projects")

            # Initiative members (composite key)
            for im in state.get("initiative_members", []):
                obj = await session.get(
                    InitiativeMember, (im["initiative_id"], im["user_id"])
                )
                if obj:
                    await session.delete(obj)
            print("  Removed initiative members")

            # Initiative role permissions (composite key)
            for irp in state.get("initiative_role_permissions", []):
                obj = await session.get(
                    InitiativeRolePermission,
                    (irp["initiative_role_id"], irp["permission_key"]),
                )
                if obj:
                    await session.delete(obj)
            print("  Removed initiative role permissions")

            # Initiative roles
            for rid in state.get("initiative_roles", []):
                obj = await session.get(InitiativeRoleModel, rid)
                if obj:
                    await session.delete(obj)
            print("  Removed initiative roles")

            # Initiatives
            for iid in state.get("initiatives", []):
                obj = await session.get(Initiative, iid)
                if obj:
                    await session.delete(obj)
            print("  Removed initiatives")

            # Tags
            for tid in state.get("tags", []):
                obj = await session.get(Tag, tid)
                if obj:
                    await session.delete(obj)
            print("  Removed tags")

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
