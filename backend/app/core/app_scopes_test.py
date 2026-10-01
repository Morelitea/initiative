"""The scope vocabulary: what parses, and what a scope set lets an app do."""

from __future__ import annotations

import pytest

from app.core.app_scopes import (
    ALL_SCOPES,
    LEVEL_SCOPES,
    MAX_PUBLIC_ID_LENGTH,
    PUBLIC_ID_CHARS,
    app_scope,
    app_scope_target,
    is_known_scope,
    ordered_scopes,
    AppScopeAccess,
    AppScopeResource,
    InstallLevel,
    UnknownAppScope,
    is_standing_scope,
    expand,
    parse_scope,
    tool_resource,
    validate_scopes,
)
from app.core.tools import Tool


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
        validate_scopes(["documents:read", "guild:owner"])
    assert refused.value.scope == "guild:owner"


def test_each_level_has_a_standing_scope_a_community_can_grant():
    assert LEVEL_SCOPES == {
        InstallLevel.moderator: "initiatives:moderate",
        InstallLevel.guild_admin: "guild:admin",
    }
    for scope in LEVEL_SCOPES.values():
        assert scope in ALL_SCOPES
        assert is_known_scope(scope)
        assert is_standing_scope(scope)
    assert validate_scopes(["guild:admin", "documents:read"]) == {
        "guild:admin",
        "documents:read",
    }


@pytest.mark.parametrize("scope", ["initiatives:moderate", "guild:admin"])
def test_a_standing_names_no_resource(scope):
    """A standing is held by exact name: it reads and writes nothing itself,
    so a grant of one alone reaches no tool."""
    with pytest.raises(UnknownAppScope):
        parse_scope(scope)
    assert expand([scope]) == (frozenset(), frozenset())
    read, write = expand([scope, "documents:read"])
    assert read == {AppScopeResource("documents")} and write == frozenset()


def test_writing_implies_reading():
    read, write = expand(["documents:write", "comments:read"])
    assert write == {AppScopeResource("documents")}
    assert read == {AppScopeResource("documents"), AppScopeResource("comments")}


def test_read_only_resources_have_no_write_scope():
    assert "members:read" in ALL_SCOPES
    assert "initiatives:read" in ALL_SCOPES
    assert "members:write" not in ALL_SCOPES


def test_the_app_kit_contract_names_the_same_scopes():
    """Two sources in two repositories: the kit's contract, which an author
    requests scopes from, and this vocabulary, which grants and enforces them.
    A scope in one and not the other is either one no app can ask for or one
    an app can ask for and never be granted."""
    from app.services.marketplace import contract

    assert contract.enum("scope") == frozenset(ALL_SCOPES)


def test_an_app_scope_names_the_app_it_lets_one_call():
    assert app_scope("acme.github") == "apps:acme.github"
    assert app_scope_target("apps:acme.github") == "acme.github"
    assert is_known_scope("apps:acme.github")
    assert validate_scopes(["apps:acme.github", "documents:read"]) == {
        "apps:acme.github",
        "documents:read",
    }


@pytest.mark.parametrize(
    "scope",
    [
        "apps:",
        "apps:github",
        "apps:Acme.github",
        "apps:acme github",
        "app:acme.github",
        "xapps:acme.github",
        "apps:" + "a." + "b" * MAX_PUBLIC_ID_LENGTH,
    ],
)
def test_what_is_not_an_app_scope_is_refused(scope):
    assert app_scope_target(scope) is None
    with pytest.raises(UnknownAppScope):
        validate_scopes([scope])


def test_an_app_scope_reaches_no_resource():
    read, write = expand(["apps:acme.github", "tags:read"])
    assert read == {AppScopeResource("tags")}
    assert write == set()


def test_app_scopes_follow_the_vocabulary_in_order():
    assert ordered_scopes(
        ["apps:b.one", "tags:read", "apps:a.two", "projects:read", "nope"]
    ) == ["projects:read", "tags:read", "apps:a.two", "apps:b.one"]


def test_the_public_id_rule_is_the_contracts():
    from app.services.marketplace import contract

    assert PUBLIC_ID_CHARS == contract.charset("publicId")
    assert MAX_PUBLIC_ID_LENGTH == contract.cap("publicIdLength")
