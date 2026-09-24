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
    SettingsGrantee,
    SystemGuild,
    Unattributed,
    classify,
)

pytestmark = pytest.mark.unit


def test_no_user_and_no_guild_is_unattributed():
    assert isinstance(classify(), Unattributed)


def test_a_user_without_a_guild_is_the_platform_path():
    shape = classify(user_id=7, platform_role="owner")
    assert isinstance(shape, Platform)
    assert (shape.user_id, shape.tier) == (7, "owner")


def test_a_guild_carries_its_own_modifiers():
    standing = object()
    shape = classify(
        user_id=7, guild_id=3, context=standing, read_only=True, query=True
    )
    assert isinstance(shape, GuildScoped)
    assert (shape.guild_id, shape.standing, shape.read_only, shape.query) == (
        3,
        standing,
        True,
        True,
    )


def test_a_grant_is_scoped_by_its_own_guild_id():
    shape = classify(user_id=7, pam_guild_id=3, pam_read=True)
    assert isinstance(shape, PamGrantee)
    assert shape.pam_guild_id == 3
    assert not hasattr(shape, "guild_id")


def test_a_grant_and_a_guild_are_not_the_same_request():
    """Membership and a grant are recorded separately."""
    with pytest.raises(ContextShapeError):
        classify(user_id=7, guild_id=3, pam_guild_id=3, pam_write=True)


def test_a_grant_must_name_the_guild_it_reaches():
    with pytest.raises(ContextShapeError):
        classify(user_id=7, pam_read=True)


def test_guild_modifiers_need_something_to_be_about():
    for kwargs in ({"read_only": True}, {"query": True}):
        with pytest.raises(ContextShapeError):
            classify(user_id=7, **kwargs)


def test_a_grant_narrows_the_way_a_member_does():
    """The query surface replays a request's own context with the reader flag
    and a scope added. A grantee reaching it is replayed the same way, so the
    narrowing keywords have to be part of that shape too."""
    shape = classify(
        user_id=7,
        pam_guild_id=3,
        pam_read=True,
        query=True,
        scope_initiative_id=11,
        via_dashboard_id=None,
    )
    assert isinstance(shape, PamGrantee)
    assert (shape.query, shape.scope_initiative_id) == (True, 11)


def test_a_grant_still_does_not_say_how_a_guild_is_routed():
    with pytest.raises(ContextShapeError):
        classify(user_id=7, pam_guild_id=3, pam_read=True, read_only=True)


def test_a_settings_grant_is_its_own_guild_route():
    shape = classify(user_id=7, settings_guild_id=3)
    assert isinstance(shape, SettingsGrantee)
    assert shape.settings_guild_id == 3


def test_a_settings_grant_cannot_carry_content_authority():
    for kwargs in (
        {"guild_id": 3},
        {"scope_initiative_id": 11},
    ):
        with pytest.raises(ContextShapeError):
            classify(user_id=7, settings_guild_id=3, **kwargs)


def test_the_two_grants_of_a_pair_name_one_community():
    """Break-glass is a content grant and a settings grant issued together.
    Each names the community on its own axis, and it is the same one."""
    shape = classify(user_id=7, settings_guild_id=3, pam_guild_id=3, pam_read=True)
    assert isinstance(shape, PamGrantee)
    assert (shape.pam_guild_id, shape.settings_guild_id) == (3, 3)

    with pytest.raises(ContextShapeError):
        classify(user_id=7, settings_guild_id=4, pam_guild_id=3, pam_read=True)


def test_a_person_needs_the_standing_the_seam_computes():
    """A routing that names both a reader and a community without one would
    run every membership leg against an empty standing. Refused at the call."""
    with pytest.raises(ContextShapeError):
        classify(user_id=7, guild_id=3)


def test_spelling_out_an_absent_argument_reads_as_absent():
    """The grant path names ``guild_id=None`` to say the guild is not part of
    this context. That is the same as leaving it out."""
    shape = classify(user_id=7, guild_id=None, context=None, pam_guild_id=3)
    assert isinstance(shape, PamGrantee)


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
            splatted = False
            for keyword in node.keywords:
                if keyword.arg is None:
                    # ``set_rls_context(session, **context)`` — the keys are not
                    # in the source, so this walk cannot judge the call. Reading
                    # it as "no keywords" would pass it vacuously, which is how
                    # the query surface's replay of a grantee's context got
                    # through the first time. Skipped here and covered by the
                    # round-trip tests above instead.
                    splatted = True
                    continue
                try:
                    kwargs[keyword.arg] = ast.literal_eval(keyword.value)
                except Exception:
                    kwargs[keyword.arg] = _STAND_IN.get(keyword.arg, 1)
            if splatted:
                continue
            found.append((str(path.relative_to(root)), node.lineno, kwargs))
    return found


#: Stand-ins for arguments whose value the source does not spell out. The
#: classifier decides on which arguments are present, so any value of the right
#: shape will do.
_STAND_IN = {
    "satisfied_providers": None,
    "context": object(),
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


def test_a_routed_guild_with_nobody_behind_it_is_system_work():
    """The shape says what the database cannot: that nobody is asking."""
    shape = classify(guild_id=7)
    assert isinstance(shape, SystemGuild)
    assert shape.guild_id == 7
    assert shape.user_id is None


def test_a_person_in_a_guild_is_not_system_work():
    shape = classify(guild_id=7, user_id=3, context=object())
    assert isinstance(shape, GuildScoped)
    assert not isinstance(shape, SystemGuild)


def test_system_work_is_still_a_guild_context():
    """``SystemGuild`` narrows ``GuildScoped`` rather than replacing it.

    Everything that already asks "is this routed into a guild?" keeps its
    answer; naming the unattended case adds a distinction without removing one.
    """
    shape = classify(guild_id=7)
    assert isinstance(shape, GuildScoped)
    assert shape.standing is None
