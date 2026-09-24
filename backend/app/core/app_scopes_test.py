"""The scope vocabulary: what parses, and what a scope set lets an app do."""

from __future__ import annotations

import pytest

from app.core.app_scopes import (
    ALL_SCOPES,
    AppScopeAccess,
    AppScopeResource,
    UnknownAppScope,
    expand,
    parse_scope,
    tool_resource,
    validate_scopes,
)
from app.core.tools import Tool

pytestmark = pytest.mark.unit


def test_a_tool_scope_parses_to_its_tool():
    resource, access = parse_scope("counter_groups:write")
    assert resource is tool_resource(Tool.counter_group)
    assert access is AppScopeAccess.write


@pytest.mark.parametrize(
    "scope",
    [
        "members:write",
        "initiatives:write",
        "projects",
        "projects:admin",
        "project:read",
        "settings:read",
        "",
    ],
)
def test_what_is_not_a_scope_is_refused(scope):
    with pytest.raises(UnknownAppScope):
        parse_scope(scope)


def test_validate_names_the_scope_it_refused():
    with pytest.raises(UnknownAppScope) as refused:
        validate_scopes(["documents:read", "guild:admin"])
    assert refused.value.scope == "guild:admin"


def test_writing_implies_reading():
    read, write = expand(["documents:write", "comments:read"])
    assert write == {AppScopeResource("documents")}
    assert read == {AppScopeResource("documents"), AppScopeResource("comments")}


def test_read_only_resources_have_no_write_scope():
    assert "members:read" in ALL_SCOPES
    assert "initiatives:read" in ALL_SCOPES
    assert "members:write" not in ALL_SCOPES
