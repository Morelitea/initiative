"""
Service for calculating user statistics and metrics.
"""

from datetime import date, datetime, timedelta, timezone
from typing import List, Literal, Optional, Set
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.initiative import Initiative
from app.models.project import Project
from app.models.task import Task, TaskAssignee, TaskStatus, TaskStatusCategory
from app.models.user import User
from app.schemas.stats import (
    GuildTaskBreakdown,
    HeatmapDayData,
    UserStatsResponse,
    VelocityWeekData,
)


def _resolve_timezone(timezone_str: str) -> ZoneInfo:
    """Resolve timezone string to ZoneInfo object, falling back to UTC if invalid."""
    try:
        return ZoneInfo(timezone_str)
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


def _get_week_start(dt: date, week_starts_on: int) -> date:
    """
    Calculate the start date of the week for a given date.

    Args:
        dt: The date to calculate week start for
        week_starts_on: 0=Sunday, 1=Monday, ..., 6=Saturday

    Returns:
        The date of the week start
    """
    days_since_week_start = (dt.weekday() + 1 - week_starts_on) % 7
    return dt - timedelta(days=days_since_week_start)


def _get_week_boundaries(
    user_tz: ZoneInfo, week_starts_on: int, num_weeks: int = 12
) -> List[tuple[datetime, datetime]]:
    """
    Calculate week boundaries for the last N weeks.

    Returns list of (week_start_datetime, week_end_datetime) tuples in user's timezone.
    """
    now_local = datetime.now(user_tz)
    today_local = now_local.date()

    week_start_date = _get_week_start(today_local, week_starts_on)

    boundaries = []
    for i in range(num_weeks):
        week_start = week_start_date - timedelta(weeks=i)
        week_end = week_start + timedelta(days=7)

        # Convert to datetime at start/end of day in user's timezone
        start_dt = datetime.combine(week_start, datetime.min.time()).replace(tzinfo=user_tz)
        end_dt = datetime.combine(week_end, datetime.min.time()).replace(tzinfo=user_tz)

        boundaries.append((start_dt, end_dt))

    return list(reversed(boundaries))  # Return oldest to newest


async def calculate_user_streak(
    session: AsyncSession,
    user_id: int,
    user_timezone: str,
    guild_id: Optional[int] = None,
) -> int:
    """
    Calculate the user's current streak of consecutive work days (Mon-Fri) with task activity.

    Task activity includes: task creation dates and task updates for tasks user is assigned to.
    Weekends do not break the streak.
    """
    user_tz = _resolve_timezone(user_timezone)
    now_local = datetime.now(user_tz)
    today = now_local.date()

    # Query: Get all dates of task activity (created_at and updated_at) for user's assigned tasks
    activity_stmt = (
        select(Task.created_at, Task.updated_at)
        .join(TaskAssignee, TaskAssignee.task_id == Task.id)
        .where(TaskAssignee.user_id == user_id)
    )

    if guild_id:
        activity_stmt = (
            activity_stmt.join(Project, Project.id == Task.project_id)
            .join(Initiative, Initiative.id == Project.initiative_id)
            .where(Initiative.guild_id == guild_id)
        )

    activity_result = await session.exec(activity_stmt)
    rows = activity_result.all()

    # Collect all activity dates (both created_at and updated_at)
    activity_dates: Set[date] = set()
    for created_at, updated_at in rows:
        if created_at:
            activity_dates.add(created_at.astimezone(user_tz).date())
        if updated_at:
            activity_dates.add(updated_at.astimezone(user_tz).date())

    # Filter to weekdays only (Mon-Fri)
    weekday_activity = {d for d in activity_dates if d.weekday() < 5}

    if not weekday_activity:
        return 0

    # Walk backwards from today, counting consecutive work days with activity
    streak = 0
    current_date = today

    # Skip if today is weekend
    if current_date.weekday() >= 5:  # Saturday or Sunday
        # Go back to Friday
        days_to_subtract = current_date.weekday() - 4
        current_date = current_date - timedelta(days=days_to_subtract)

    while True:
        # If current date is a weekday and has activity
        if current_date.weekday() < 5:
            if current_date in weekday_activity:
                streak += 1
                current_date = current_date - timedelta(days=1)
            else:
                # No activity on this work day, streak is broken
                break
        else:
            # Skip weekends
            current_date = current_date - timedelta(days=1)

        # Safety check: don't go back more than a year
        if (today - current_date).days > 365:
            break

    return streak


async def calculate_on_time_rate(
    session: AsyncSession,
    user_id: int,
    guild_id: Optional[int] = None,
) -> float:
    """
    Calculate the percentage of completed tasks that were finished before their due date.

    Returns a percentage between 0 and 100.
    """
    stmt = (
        select(
            func.count(Task.id).label("total"),
            func.sum(case((Task.updated_at <= Task.due_date, 1), else_=0)).label("on_time"),
        )
        .join(TaskAssignee, TaskAssignee.task_id == Task.id)
        .join(TaskStatus, TaskStatus.id == Task.task_status_id)
        .where(
            TaskAssignee.user_id == user_id,
            TaskStatus.category == TaskStatusCategory.done,
            Task.due_date.is_not(None),
        )
    )

    if guild_id:
        stmt = (
            stmt.join(Project, Project.id == Task.project_id)
            .join(Initiative, Initiative.id == Project.initiative_id)
            .where(Initiative.guild_id == guild_id)
        )

    result = await session.exec(stmt)
    row = result.one()

    total = row.total or 0
    on_time = row.on_time or 0

    if total == 0:
        return 0.0

    return (on_time / total) * 100.0


async def calculate_avg_completion_days(
    session: AsyncSession,
    user_id: int,
    guild_id: Optional[int] = None,
) -> Optional[float]:
    """
    Calculate average days from start_date to completion.

    Only includes tasks that have a start_date set.
    Returns None if no tasks with start_date are completed.
    """
    stmt = (
        select(func.avg(func.extract("epoch", Task.updated_at - Task.start_date) / 86400))
        .join(TaskAssignee, TaskAssignee.task_id == Task.id)
        .join(TaskStatus, TaskStatus.id == Task.task_status_id)
        .where(
            TaskAssignee.user_id == user_id,
            TaskStatus.category == TaskStatusCategory.done,
            Task.start_date.is_not(None),
        )
    )

    if guild_id:
        stmt = (
            stmt.join(Project, Project.id == Task.project_id)
            .join(Initiative, Initiative.id == Project.initiative_id)
            .where(Initiative.guild_id == guild_id)
        )

    result = await session.exec(stmt)
    avg_days = result.scalar()

    if avg_days is None:
        return None

    return float(avg_days)


async def get_completed_counts(
    session: AsyncSession,
    user_id: int,
    user_timezone: str,
    week_starts_on: int,
    guild_id: Optional[int] = None,
) -> tuple[int, int]:
    """
    Get total completed tasks and tasks completed this week.

    Returns (total_completed, this_week_completed)
    """
    user_tz = _resolve_timezone(user_timezone)
    now_local = datetime.now(user_tz)
    today = now_local.date()

    # Calculate this week's boundaries
    week_start_date = _get_week_start(today, week_starts_on)
    week_start_dt = datetime.combine(week_start_date, datetime.min.time()).replace(tzinfo=user_tz)
    week_end_dt = week_start_dt + timedelta(days=7)

    # Convert to UTC for database query
    week_start_utc = week_start_dt.astimezone(timezone.utc)
    week_end_utc = week_end_dt.astimezone(timezone.utc)

    base_stmt = (
        select(
            func.count(Task.id).label("total"),
            func.sum(
                case(
                    (
                        (Task.updated_at >= week_start_utc) & (Task.updated_at < week_end_utc),
                        1,
                    ),
                    else_=0,
                )
            ).label("this_week"),
        )
        .join(TaskAssignee, TaskAssignee.task_id == Task.id)
        .join(TaskStatus, TaskStatus.id == Task.task_status_id)
        .where(TaskAssignee.user_id == user_id, TaskStatus.category == TaskStatusCategory.done)
    )

    if guild_id:
        base_stmt = (
            base_stmt.join(Project, Project.id == Task.project_id)
            .join(Initiative, Initiative.id == Project.initiative_id)
            .where(Initiative.guild_id == guild_id)
        )

    result = await session.exec(base_stmt)
    row = result.one()

    total = row.total or 0
    this_week = row.this_week or 0

    return (total, this_week)


async def get_velocity_data(
    session: AsyncSession,
    user_id: int,
    user_timezone: str,
    week_starts_on: int,
    guild_id: Optional[int] = None,
) -> List[VelocityWeekData]:
    """
    Get weekly velocity data for the last 12 weeks.

    Returns list of VelocityWeekData with assigned and completed counts per week.
    Note: "Assigned" counts tasks created in the week (assumes assignment at creation).
    """
    user_tz = _resolve_timezone(user_timezone)
    week_boundaries = _get_week_boundaries(user_tz, week_starts_on, num_weeks=12)

    velocity_data: List[VelocityWeekData] = []

    for week_start_local, week_end_local in week_boundaries:
        week_start_utc = week_start_local.astimezone(timezone.utc)
        week_end_utc = week_end_local.astimezone(timezone.utc)

        # Count assigned tasks this week (using task created_at as proxy for assignment)
        assigned_stmt = (
            select(func.count(Task.id))
            .join(TaskAssignee, TaskAssignee.task_id == Task.id)
            .where(
                TaskAssignee.user_id == user_id,
                Task.created_at >= week_start_utc,
                Task.created_at < week_end_utc,
            )
        )

        if guild_id:
            assigned_stmt = (
                assigned_stmt.join(Project, Project.id == Task.project_id)
                .join(Initiative, Initiative.id == Project.initiative_id)
                .where(Initiative.guild_id == guild_id)
            )

        assigned_result = await session.exec(assigned_stmt)
        assigned_count = assigned_result.scalar() or 0

        # Count completed tasks this week
        completed_stmt = (
            select(func.count(Task.id))
            .join(TaskAssignee, TaskAssignee.task_id == Task.id)
            .join(TaskStatus, TaskStatus.id == Task.task_status_id)
            .where(
                TaskAssignee.user_id == user_id,
                TaskStatus.category == TaskStatusCategory.done,
                Task.updated_at >= week_start_utc,
                Task.updated_at < week_end_utc,
            )
        )

        if guild_id:
            completed_stmt = (
                completed_stmt.join(Project, Project.id == Task.project_id)
                .join(Initiative, Initiative.id == Project.initiative_id)
                .where(Initiative.guild_id == guild_id)
            )

        completed_result = await session.exec(completed_stmt)
        completed_count = completed_result.scalar() or 0

        velocity_data.append(
            VelocityWeekData(
                week_start=week_start_local.date(),
                assigned=assigned_count,
                completed=completed_count,
            )
        )

    return velocity_data


async def get_heatmap_data(
    session: AsyncSession,
    user_id: int,
    user_timezone: str,
    guild_id: Optional[int] = None,
) -> List[HeatmapDayData]:
    """
    Get daily activity counts for the last 365 days.

    Activity includes task creation and task updates for user's assigned tasks.
    """
    user_tz = _resolve_timezone(user_timezone)
    now_local = datetime.now(user_tz)
    today = now_local.date()

    # Calculate date range (last 365 days)
    start_date = today - timedelta(days=365)
    start_dt = datetime.combine(start_date, datetime.min.time()).replace(tzinfo=user_tz)
    end_dt = datetime.combine(today + timedelta(days=1), datetime.min.time()).replace(tzinfo=user_tz)

    # Convert to UTC
    start_utc = start_dt.astimezone(timezone.utc)
    end_utc = end_dt.astimezone(timezone.utc)

    # Query task activity (created_at and updated_at) for user's assigned tasks
    activity_stmt = (
        select(Task.created_at, Task.updated_at)
        .join(TaskAssignee, TaskAssignee.task_id == Task.id)
        .where(TaskAssignee.user_id == user_id)
    )

    if guild_id:
        activity_stmt = (
            activity_stmt.join(Project, Project.id == Task.project_id)
            .join(Initiative, Initiative.id == Project.initiative_id)
            .where(Initiative.guild_id == guild_id)
        )

    result = await session.exec(activity_stmt)
    rows = result.all()

    # Combine and count by date
    activity_by_date: dict[date, int] = {}
    for created_at, updated_at in rows:
        # Count created_at if in range
        if created_at and start_utc <= created_at < end_utc:
            local_date = created_at.astimezone(user_tz).date()
            activity_by_date[local_date] = activity_by_date.get(local_date, 0) + 1

        # Count updated_at if in range
        if updated_at and start_utc <= updated_at < end_utc:
            local_date = updated_at.astimezone(user_tz).date()
            activity_by_date[local_date] = activity_by_date.get(local_date, 0) + 1

    # Build result with all dates (including zero-activity days)
    heatmap_data: List[HeatmapDayData] = []
    current_date = start_date
    while current_date <= today:
        activity_count = activity_by_date.get(current_date, 0)
        heatmap_data.append(HeatmapDayData(day=current_date, activity_count=activity_count))
        current_date = current_date + timedelta(days=1)

    return heatmap_data


async def get_guild_breakdown(
    session: AsyncSession,
    user_id: int,
) -> List[GuildTaskBreakdown]:
    """
    Get task completion breakdown by guild.

    Returns count of completed tasks per guild for the user.
    """
    from app.models.guild import Guild

    stmt = (
        select(Guild.id, Guild.name, func.count(Task.id).label("completed_count"))
        .join(Initiative, Initiative.guild_id == Guild.id)
        .join(Project, Project.initiative_id == Initiative.id)
        .join(Task, Task.project_id == Project.id)
        .join(TaskAssignee, TaskAssignee.task_id == Task.id)
        .join(TaskStatus, TaskStatus.id == Task.task_status_id)
        .where(TaskAssignee.user_id == user_id, TaskStatus.category == TaskStatusCategory.done)
        .group_by(Guild.id, Guild.name)
        .order_by(func.count(Task.id).desc())
    )

    result = await session.exec(stmt)
    rows = result.all()

    return [
        GuildTaskBreakdown(guild_id=guild_id, guild_name=guild_name, completed_count=count)
        for guild_id, guild_name, count in rows
    ]


async def get_backlog_trend(
    session: AsyncSession,
    user_id: int,
    user_timezone: str,
    week_starts_on: int,
    guild_id: Optional[int] = None,
) -> Literal["Growing", "Shrinking"]:
    """
    Determine if backlog is growing or shrinking this week.

    Returns "Growing" if more tasks assigned than completed this week, else "Shrinking".
    Note: "Assigned" counts tasks created this week (assumes assignment at creation).
    """
    user_tz = _resolve_timezone(user_timezone)
    now_local = datetime.now(user_tz)
    today = now_local.date()

    # Calculate this week's boundaries
    week_start_date = _get_week_start(today, week_starts_on)
    week_start_dt = datetime.combine(week_start_date, datetime.min.time()).replace(tzinfo=user_tz)
    week_end_dt = week_start_dt + timedelta(days=7)

    # Convert to UTC
    week_start_utc = week_start_dt.astimezone(timezone.utc)
    week_end_utc = week_end_dt.astimezone(timezone.utc)

    # Count assigned this week (using task created_at as proxy for assignment)
    assigned_stmt = (
        select(func.count(Task.id))
        .join(TaskAssignee, TaskAssignee.task_id == Task.id)
        .where(
            TaskAssignee.user_id == user_id,
            Task.created_at >= week_start_utc,
            Task.created_at < week_end_utc,
        )
    )

    if guild_id:
        assigned_stmt = (
            assigned_stmt.join(Project, Project.id == Task.project_id)
            .join(Initiative, Initiative.id == Project.initiative_id)
            .where(Initiative.guild_id == guild_id)
        )

    assigned_result = await session.exec(assigned_stmt)
    assigned_count = assigned_result.scalar() or 0

    # Count completed this week
    completed_stmt = (
        select(func.count(Task.id))
        .join(TaskAssignee, TaskAssignee.task_id == Task.id)
        .join(TaskStatus, TaskStatus.id == Task.task_status_id)
        .where(
            TaskAssignee.user_id == user_id,
            TaskStatus.category == TaskStatusCategory.done,
            Task.updated_at >= week_start_utc,
            Task.updated_at < week_end_utc,
        )
    )

    if guild_id:
        completed_stmt = (
            completed_stmt.join(Project, Project.id == Task.project_id)
            .join(Initiative, Initiative.id == Project.initiative_id)
            .where(Initiative.guild_id == guild_id)
        )

    completed_result = await session.exec(completed_stmt)
    completed_count = completed_result.scalar() or 0

    return "Growing" if assigned_count > completed_count else "Shrinking"


async def get_user_stats(
    session: AsyncSession,
    user: User,
    guild_id: Optional[int] = None,
    days: int = 90,
) -> UserStatsResponse:
    """
    Get comprehensive user statistics.

    Args:
        session: Database session
        user: User object
        guild_id: Optional guild ID to filter stats
        days: Number of days to include in analysis (not currently used, for future extension)

    Returns:
        UserStatsResponse with all metrics
    """
    # Execute all metric calculations sequentially
    # Note: SQLAlchemy async sessions don't support concurrent operations on the same session
    streak = await calculate_user_streak(session, user.id, user.timezone, guild_id)
    on_time_rate = await calculate_on_time_rate(session, user.id, guild_id)
    avg_completion_days = await calculate_avg_completion_days(session, user.id, guild_id)
    tasks_completed_total, tasks_completed_this_week = await get_completed_counts(
        session, user.id, user.timezone, user.week_starts_on, guild_id
    )
    velocity_data = await get_velocity_data(session, user.id, user.timezone, user.week_starts_on, guild_id)
    heatmap_data = await get_heatmap_data(session, user.id, user.timezone, guild_id)
    guild_breakdown = await get_guild_breakdown(session, user.id)
    backlog_trend = await get_backlog_trend(session, user.id, user.timezone, user.week_starts_on, guild_id)

    # If guild_id is specified, filter guild_breakdown to only show that guild
    if guild_id:
        guild_breakdown = [g for g in guild_breakdown if g.guild_id == guild_id]

    return UserStatsResponse(
        streak=streak,
        on_time_rate=round(on_time_rate, 1),
        avg_completion_days=round(avg_completion_days, 1) if avg_completion_days is not None else None,
        tasks_completed_total=tasks_completed_total,
        tasks_completed_this_week=tasks_completed_this_week,
        backlog_trend=backlog_trend,
        velocity_data=velocity_data,
        heatmap_data=heatmap_data,
        guild_breakdown=guild_breakdown,
    )
