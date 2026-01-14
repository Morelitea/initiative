"""Service for importing tasks from external platforms."""

import csv
import io
from typing import Dict, List, Optional, Tuple

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.task import Task, TaskPriority, Subtask
from app.schemas.import_data import (
    ImportResult,
    TodoistSection,
    TodoistParseResult,
)


# Todoist priority mapping (Todoist uses 1=highest, 4=lowest)
TODOIST_PRIORITY_MAP: Dict[int, TaskPriority] = {
    1: TaskPriority.urgent,
    2: TaskPriority.high,
    3: TaskPriority.medium,
    4: TaskPriority.low,
}


def parse_todoist_csv(csv_content: str) -> Tuple[TodoistParseResult, List[dict]]:
    """
    Parse Todoist CSV export and extract sections and tasks.

    Returns:
        Tuple of (parse_result with metadata, list of task dicts)
    """
    # Handle BOM if present
    if csv_content.startswith("\ufeff"):
        csv_content = csv_content[1:]

    reader = csv.DictReader(io.StringIO(csv_content))

    sections: Dict[str, int] = {}  # section_name -> task_count
    tasks: List[dict] = []
    current_section: Optional[str] = None
    has_subtasks = False

    for row in reader:
        row_type = row.get("TYPE", "").strip().lower()

        if row_type == "meta":
            # Skip metadata rows
            continue
        elif row_type == "section":
            # New section
            section_name = row.get("CONTENT", "").strip()
            if section_name:
                current_section = section_name
                if section_name not in sections:
                    sections[section_name] = 0
        elif row_type == "task":
            # Task row
            content = row.get("CONTENT", "").strip()
            if not content:
                continue

            indent = int(row.get("INDENT", "1") or "1")
            if indent > 1:
                has_subtasks = True

            # Get priority (Todoist uses 1-4, where 1 is highest)
            try:
                todoist_priority = int(row.get("PRIORITY", "4") or "4")
            except ValueError:
                todoist_priority = 4

            task_data = {
                "title": content,
                "description": row.get("DESCRIPTION", "").strip() or None,
                "priority": todoist_priority,
                "indent": indent,
                "section": current_section,
                "responsible": row.get("RESPONSIBLE", "").strip() or None,
                "date": row.get("DATE", "").strip() or None,
            }
            tasks.append(task_data)

            # Count tasks per section
            if current_section and current_section in sections:
                sections[current_section] += 1

    # Build result
    section_list = [
        TodoistSection(name=name, task_count=count) for name, count in sections.items()
    ]

    parse_result = TodoistParseResult(
        sections=section_list,
        task_count=len([t for t in tasks if t["indent"] == 1]),  # Only top-level tasks
        has_subtasks=has_subtasks,
    )

    return parse_result, tasks


async def import_todoist_tasks(
    session: AsyncSession,
    project_id: int,
    csv_content: str,
    section_mapping: Dict[str, int],
) -> ImportResult:
    """
    Import tasks from Todoist CSV into a project.

    Args:
        session: Database session
        project_id: Target project ID
        csv_content: Raw CSV content
        section_mapping: Mapping of section names to task_status_id

    Returns:
        ImportResult with counts and errors
    """
    result = ImportResult()

    try:
        _, tasks = parse_todoist_csv(csv_content)
    except Exception as e:
        result.errors.append(f"Failed to parse CSV: {str(e)}")
        return result

    if not tasks:
        result.errors.append("No tasks found in CSV")
        return result

    # Get the next sort_order for the project
    max_order_result = await session.execute(
        select(func.coalesce(func.max(Task.sort_order), 0)).where(
            Task.project_id == project_id
        )
    )
    next_sort_order = float(max_order_result.scalar() or 0) + 1

    # Track parent tasks for subtask creation
    last_parent_task: Optional[Task] = None
    subtask_position = 0

    for task_data in tasks:
        try:
            section = task_data.get("section")
            indent = task_data.get("indent", 1)

            # Get status from mapping
            status_id = section_mapping.get(section) if section else None
            if status_id is None:
                # Use first mapped status as default
                status_id = next(iter(section_mapping.values()), None)

            if status_id is None:
                result.errors.append(
                    f"No status mapping for section '{section}', skipping task: {task_data['title']}"
                )
                result.tasks_failed += 1
                continue

            # Map priority
            todoist_priority = task_data.get("priority", 4)
            priority = TODOIST_PRIORITY_MAP.get(todoist_priority, TaskPriority.low)

            if indent == 1:
                # Top-level task
                task = Task(
                    project_id=project_id,
                    task_status_id=status_id,
                    title=task_data["title"],
                    description=task_data.get("description"),
                    priority=priority,
                    sort_order=next_sort_order,
                )
                session.add(task)
                await session.flush()

                last_parent_task = task
                subtask_position = 0
                next_sort_order += 1
                result.tasks_created += 1
            else:
                # Subtask (indent > 1)
                if last_parent_task is None:
                    result.errors.append(
                        f"Subtask without parent task, skipping: {task_data['title']}"
                    )
                    result.tasks_failed += 1
                    continue

                subtask = Subtask(
                    task_id=last_parent_task.id,
                    content=task_data["title"],
                    is_completed=False,
                    position=subtask_position,
                )
                session.add(subtask)
                subtask_position += 1
                result.subtasks_created += 1

        except Exception as e:
            result.errors.append(f"Failed to import task '{task_data.get('title', 'unknown')}': {str(e)}")
            result.tasks_failed += 1

    await session.commit()
    return result
