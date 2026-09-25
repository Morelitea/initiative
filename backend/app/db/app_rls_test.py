"""Which guild tables an app reaches, checked against the models."""

from __future__ import annotations

import pytest
from sqlmodel import SQLModel

from app.db import base  # noqa: F401  # populates SQLModel.metadata with every table
from app.core.app_scopes import AppScopeResource
from app.db.app_rls import APP_TABLE_ACCESS, AppTableKind
from app.db.tenancy import GUILD_SCOPED_TABLES


def test_every_table_named_is_a_guild_table_that_exists():
    """Every entry names a guild table the models declare."""
    for table in APP_TABLE_ACCESS:
        assert table in SQLModel.metadata.tables, table
        assert table in GUILD_SCOPED_TABLES, table


@pytest.mark.parametrize(
    ("table", "resource"),
    [
        ("projects", "projects"),
        ("tasks", "projects"),
        ("task_assignees", "projects"),
        ("calendar_event_attendees", "calendars"),
        ("queue_items", "queues"),
        ("comments", "comments"),
        ("tags", "tags"),
    ],
)
def test_content_answers_to_the_scope_of_what_it_belongs_to(table, resource):
    access = APP_TABLE_ACCESS[table]
    assert access.kind is AppTableKind.scoped
    assert access.resource is AppScopeResource(resource)
    assert access.writable


@pytest.mark.parametrize("table", ["initiatives", "initiative_members"])
def test_structure_is_read_only(table):
    assert not APP_TABLE_ACCESS[table].writable


@pytest.mark.parametrize(
    "table",
    [
        "guild_settings",
        "guild_apps",
        "initiative_role_permissions",
        "uploads",
        "project_favorites",
        "post_reads",
        "intake_cases",
    ],
)
def test_administration_and_personal_state_are_out_of_reach(table):
    assert table not in APP_TABLE_ACCESS


def test_side_effects_are_never_written_directly():
    access = APP_TABLE_ACCESS["event_outbox"]
    assert access.kind is AppTableKind.side_effect
    assert not access.writable
