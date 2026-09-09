"""The project dataset.

Everything here is read off ``Project``: its columns, the pickers its foreign
keys imply, and its tags. What is left to say is the one column that records a
screen's preference rather than anything about the project.
"""

from __future__ import annotations

from app.core.tools import Tool
from app.models.tenant.project import Project
from app.services.fields.derive import derive_fields
from app.services.fields.spec import Dataset

#: Which layout the project last opened in — a preference belonging to the
#: screen that reads it, not a property anybody narrows a list by.
_INTERNAL = frozenset({"default_view_mode"})


def build() -> Dataset:
    return Dataset(
        model=Project,
        tool=Tool.project,
        name_override="projects",
        fields=derive_fields(Project, internal=_INTERNAL),
    )
