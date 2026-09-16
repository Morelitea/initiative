"""What a request's database context may and may not be.

The rules these pin used to live in ``set_rls_context``'s docstring. The last
test is the one that earns its keep: it reads every call to that function in
the tree and checks the arguments form a shape, so a new call site that mixes
two contexts fails here rather than running.
"""

import ast
import pathlib

import pytest

from app.db.request_context import (
    ContextShapeError,
    GuildScoped,
    PamGrantee,
    Platform,
    Unattributed,
    classify,
)
from app.models.platform.guild import GuildRole

pytestmark = pytest.mark.unit


def test_no_user_and_no_guild_is_unattributed():
    assert isinstance(classify(), Unattributed)


def test_a_user_without_a_guild_is_the_platform_path():
    shape = classify(user_id=7, platform_role="owner")
    assert isinstance(shape, Platform)
    assert (shape.user_id, shape.tier) == (7, "owner")


def test_a_guild_carries_its_own_modifiers():
    shape = classify(
        user_id=7, guild_id=3, guild_role="admin", read_only=True, query=True
    )
    assert isinstance(shape, GuildScoped)
    assert (shape.guild_id, shape.role, shape.read_only, shape.query) == (
        3,
        "admin",
        True,
        True,
    )


def test_a_grant_is_scoped_by_its_own_guild_id():
    shape = classify(user_id=7, pam_guild_id=3, pam_read=True)
    assert isinstance(shape, PamGrantee)
    assert shape.pam_guild_id == 3
    assert not hasattr(shape, "guild_id")


def test_a_grant_and_a_guild_are_not_the_same_request():
    """The separation the shared-table write policies depend on."""
    with pytest.raises(ContextShapeError):
        classify(user_id=7, guild_id=3, pam_guild_id=3, pam_write=True)


def test_a_grant_must_name_the_guild_it_reaches():
    with pytest.raises(ContextShapeError):
        classify(user_id=7, pam_read=True)


def test_guild_modifiers_need_a_guild():
    for kwargs in ({"guild_role": "admin"}, {"read_only": True}, {"query": True}):
        with pytest.raises(ContextShapeError):
            classify(user_id=7, **kwargs)


def test_a_stored_role_does_not_reach_the_guc():
    """``security_admin`` is a membership row, not a content role. It arrives
    as ``admin`` through ``content_role``; anything else is a caller that
    skipped that step."""
    with pytest.raises(ContextShapeError):
        classify(guild_id=3, guild_role=GuildRole.security_admin.value)
    with pytest.raises(ContextShapeError):
        classify(guild_id=3, guild_role=GuildRole.support.value)


def test_spelling_out_an_absent_argument_reads_as_absent():
    """The grant path names ``guild_id=None`` to say the guild is not part of
    this context. That is the same as leaving it out."""
    shape = classify(user_id=7, guild_id=None, guild_role=None, pam_guild_id=3)
    assert isinstance(shape, PamGrantee)


def test_the_name_rule_is_read_off_the_guild():
    class _Row:
        id = 4
        show_member_names = True

    assert GuildScoped.for_guild(_Row()).shows_member_names is True

    class _Quiet(_Row):
        show_member_names = False

    assert GuildScoped.for_guild(_Quiet()).shows_member_names is False


def _call_sites() -> list[tuple[str, int, dict]]:
    """Every ``set_rls_context`` call in the app, with the keywords whose
    values can be read from the source. A value that is computed is passed as a
    stand-in, since what is being checked is which arguments are present."""
    found = []
    root = pathlib.Path(__file__).resolve().parents[1]
    for path in root.rglob("*.py"):
        if path.name.endswith("_test.py"):
            continue
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:  # pragma: no cover - not valid python, not our call
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = (
                func.attr
                if isinstance(func, ast.Attribute)
                else getattr(func, "id", None)
            )
            if name != "set_rls_context":
                continue
            kwargs = {}
            for keyword in node.keywords:
                if keyword.arg is None:
                    continue
                try:
                    kwargs[keyword.arg] = ast.literal_eval(keyword.value)
                except Exception:
                    kwargs[keyword.arg] = _STAND_IN.get(keyword.arg, 1)
            found.append((str(path.relative_to(root)), node.lineno, kwargs))
    return found


#: Stand-ins for arguments whose value the source does not spell out. The
#: classifier decides on which arguments are present, so any value of the right
#: shape will do — except the role, which it also checks.
_STAND_IN = {
    "guild_role": "admin",
    "satisfied_providers": None,
    "override_initiatives": (),
}


def test_every_call_in_the_tree_forms_a_shape():
    sites = _call_sites()
    assert sites, "found no call sites — the walker is looking in the wrong place"
    broken = []
    for path, line, kwargs in sites:
        try:
            classify(**kwargs)
        except ContextShapeError as exc:
            broken.append(f"{path}:{line} — {exc}")
    assert not broken, "context that is not a request:\n" + "\n".join(broken)
