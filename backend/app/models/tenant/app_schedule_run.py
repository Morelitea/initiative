"""When each of an install's schedules last ran, and when it runs next.

An app's manifest may declare ``schedules``: intervals at which Initiative
calls its ``schedule`` hook, once for each community that installed it. A row
here is one install's schedule, kept in step with the install's pinned
definition (:func:`app.services.tenant.app_schedules.reconcile`) and run by the
minute pass (:func:`app.services.tenant.app_schedules.run_due`).

Written and read by the system engine alone.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from sqlmodel import Field, SQLModel


class AppScheduleRun(SQLModel, table=True):
    __tablename__ = "app_schedule_runs"

    #: The install. Its rows go with it.
    install_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("guild_apps.id", ondelete="CASCADE"),
            primary_key=True,
        )
    )
    #: The schedule's id in the pinned definition, a manifest identifier.
    schedule_id: str = Field(sa_column=Column(String(length=64), primary_key=True))
    #: When the last call that succeeded started: the hook's ``since``.
    last_success_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    next_due_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    #: Calls that have failed since the last success.
    failures: int = Field(
        default=0, sa_column=Column(Integer, nullable=False, default=0)
    )
    #: Set while a worker is calling the app, so no other claims the row.
    claimed_until: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
