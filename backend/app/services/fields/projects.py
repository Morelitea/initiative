"""The project dataset.

Everything here is read off ``Project``: its columns, the pickers its foreign
keys imply, and its tags.
"""

from __future__ import annotations

from app.core.tools import Tool
from app.models.tenant.project import Project
from app.services.fields.derive import derive_fields
from app.services.fields.spec import Dataset


def build() -> Dataset:
    return Dataset(
        model=Project,
        tool=Tool.project,
        name_override="projects",
        fields=derive_fields(Project),
    )
