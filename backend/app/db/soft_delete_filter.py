"""Session-wide ORM filter that hides soft-deleted rows by default.

Wires a ``do_orm_execute`` listener that injects a
``with_loader_criteria(<Model>, deleted_at IS NULL)`` option for every
soft-deletable model into every SELECT statement issued through a Session.
SQLAlchemy applies each criterion only to queries that actually reference the
matching table, so the per-statement overhead is small.

To opt out (for the trash listing / restore endpoints), pass
``execution_options(include_deleted=True)`` either on the Session or on the
individual statement. The ``select_including_deleted`` helper wraps that for
convenience.

The list of soft-deletable models is enumerated explicitly here rather than
discovered via ``SoftDeleteMixin.__subclasses__()`` so the filter is
deterministic and survives import-order shuffles in tests.
"""

from typing import Any, Sequence

from sqlalchemy import event, select as sa_select
from sqlalchemy.orm import Session, with_loader_criteria
from sqlalchemy.orm.session import ORMExecuteState
from sqlmodel import SQLModel

from app.models.calendar_event import CalendarEvent
from app.models.comment import Comment
from app.models.document import Document
from app.models.initiative import Initiative
from app.models.project import Project
from app.models.queue import Queue, QueueItem
from app.models.tag import Tag
from app.models.task import Task


SOFT_DELETE_MODELS: Sequence[type[SQLModel]] = (
    Project,
    Task,
    Document,
    Comment,
    Initiative,
    Tag,
    Queue,
    QueueItem,
    CalendarEvent,
)


_INSTALLED = False


def install_soft_delete_filter() -> None:
    """Install the listener exactly once. Safe to call from app startup
    or test setup multiple times."""
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    @event.listens_for(Session, "do_orm_execute")
    def _filter_deleted(state: ORMExecuteState) -> None:
        if not state.is_select:
            return
        if state.execution_options.get("include_deleted", False):
            return
        for model_cls in SOFT_DELETE_MODELS:
            state.statement = state.statement.options(
                with_loader_criteria(
                    model_cls,
                    model_cls.deleted_at.is_(None),
                    include_aliases=True,
                )
            )


def select_including_deleted(*entities: Any):
    """Construct a SELECT that bypasses the active-row filter.

    Usage:
        stmt = select_including_deleted(Project).where(Project.deleted_at.isnot(None))
        result = await session.exec(stmt)
    """
    return sa_select(*entities).execution_options(include_deleted=True)
