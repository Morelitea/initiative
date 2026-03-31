from datetime import datetime, timezone
from typing import List, Optional, TYPE_CHECKING

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSON
from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:  # pragma: no cover
    from app.models.initiative import Initiative
    from app.models.user import User


class AutomationFlow(SQLModel, table=True):
    """Initiative-scoped automation flow definition.

    Stores the full node/edge graph (flow_data) designed by the user.
    The automation engine snapshots flow_data into AutomationRun.flow_snapshot
    at execution time so the run log is immutable even if the flow is edited.
    """
    __tablename__ = "automation_flows"

    id: Optional[int] = Field(default=None, primary_key=True)
    guild_id: int = Field(foreign_key="guilds.id", nullable=False, index=True)
    initiative_id: int = Field(foreign_key="initiatives.id", nullable=False, index=True)
    name: str = Field(nullable=False, max_length=255)
    description: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    flow_data: dict = Field(sa_column=Column(JSON, nullable=False))
    enabled: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default="false"),
    )
    created_by_id: int = Field(foreign_key="users.id", nullable=False)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

    initiative: Optional["Initiative"] = Relationship(back_populates="automation_flows")
    creator: Optional["User"] = Relationship()
    runs: List["AutomationRun"] = Relationship(
        back_populates="flow",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )


class AutomationRun(SQLModel, table=True):
    """Single execution of an automation flow.

    flow_snapshot is an immutable copy of the flow_data at the time of execution.
    trigger_event records what caused the run (e.g., a task status change).
    """
    __tablename__ = "automation_runs"

    id: Optional[int] = Field(default=None, primary_key=True)
    guild_id: int = Field(foreign_key="guilds.id", nullable=False, index=True)
    flow_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("automation_flows.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
    )
    initiative_id: int = Field(foreign_key="initiatives.id", nullable=False, index=True)
    flow_snapshot: dict = Field(sa_column=Column(JSON, nullable=False))
    trigger_event: dict = Field(sa_column=Column(JSON, nullable=False))
    status: str = Field(
        sa_column=Column(String(length=20), nullable=False),
    )
    started_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    completed_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    error: Optional[str] = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
    )

    flow: Optional[AutomationFlow] = Relationship(back_populates="runs")
    steps: List["AutomationRunStep"] = Relationship(
        back_populates="run",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )


class AutomationRunStep(SQLModel, table=True):
    """Per-node execution log within an automation run.

    No guild_id column -- RLS policies join through automation_runs to
    enforce guild isolation.
    """
    __tablename__ = "automation_run_steps"

    id: Optional[int] = Field(default=None, primary_key=True)
    run_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("automation_runs.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
    )
    node_id: str = Field(
        sa_column=Column(String(length=255), nullable=False),
    )
    node_type: str = Field(
        sa_column=Column(String(length=50), nullable=False),
    )
    status: str = Field(
        sa_column=Column(String(length=20), nullable=False),
    )
    input_data: Optional[dict] = Field(
        default=None,
        sa_column=Column(JSON, nullable=True),
    )
    output_data: Optional[dict] = Field(
        default=None,
        sa_column=Column(JSON, nullable=True),
    )
    error: Optional[str] = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
    )
    started_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    completed_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )

    run: Optional[AutomationRun] = Relationship(back_populates="steps")
