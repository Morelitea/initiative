"""Source-adapter registry: which sources exist and which formats each
supports. Unsupported source×format combos are rejected centrally by
``engine.get_adapter``."""

from app.services.export.adapters.tasks_table import TasksTableAdapter

ADAPTERS = {adapter.source: adapter for adapter in (TasksTableAdapter(),)}

__all__ = ["ADAPTERS"]
