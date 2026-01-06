from datetime import date
from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class VelocityWeekData(BaseModel):
    """Weekly velocity data showing tasks assigned vs completed."""

    week_start: date = Field(..., description="Start date of the week")
    assigned: int = Field(..., description="Number of tasks assigned to user this week")
    completed: int = Field(..., description="Number of tasks completed this week")


class HeatmapDayData(BaseModel):
    """Daily activity data for heatmap visualization."""

    day: date = Field(..., description="Date of activity", serialization_alias="date")
    activity_count: int = Field(..., description="Number of task activities on this date")


class GuildTaskBreakdown(BaseModel):
    """Task completion breakdown by guild."""

    guild_id: int = Field(..., description="Guild ID")
    guild_name: str = Field(..., description="Guild name")
    completed_count: int = Field(..., description="Number of completed tasks in this guild")


class UserStatsResponse(BaseModel):
    """Comprehensive user statistics response."""

    streak: int = Field(..., description="Current streak of consecutive work days (Mon-Fri) with task activity")
    on_time_rate: float = Field(
        ..., ge=0, le=100, description="Percentage of completed tasks finished before due date"
    )
    avg_completion_days: Optional[float] = Field(
        None, description="Average days from start_date to completion (only tasks with start_date)"
    )
    tasks_completed_total: int = Field(..., description="Total number of completed tasks")
    tasks_completed_this_week: int = Field(..., description="Number of tasks completed this week")
    backlog_trend: Literal["Growing", "Shrinking"] = Field(
        ..., description="Trend based on tasks assigned vs completed this week"
    )
    velocity_data: List[VelocityWeekData] = Field(..., description="Weekly velocity data for last 12 weeks")
    heatmap_data: List[HeatmapDayData] = Field(..., description="Daily activity data for last 365 days")
    guild_breakdown: List[GuildTaskBreakdown] = Field(..., description="Task completion breakdown by guild")
