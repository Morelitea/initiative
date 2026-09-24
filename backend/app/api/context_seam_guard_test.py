"""Static guard: one seam builds a reader's standing in a community.

Three shapes are forbidden anywhere under ``app/``. They are forbidden rather
than reviewed, so there is no allow-list to add a site to.

* ``GuildContext(...)`` outside ``app/api/deps.py``, in anything that runs. The
  context says what somebody reaches in a community; it is what the lookup
  found and what the standing statement computed, and building one anywhere
  else would be a second answer to a question the seam has already asked. A
  unit test's fixture is not one of those answers — it is a value under
  assertion — so the walk for this one skips the test modules.
* ``InstallContext(...)`` outside ``app/api/deps.py``, on the same terms: an
  installed app's standing is what its verified token named and what the
  install standing statement computed, and ``establish_install_access`` is
  where both happen.
* ``set_rls_context(user_id=..., guild_id=...)`` outside ``deps.py`` and
  ``session.py``. Routing a person into a community is the seam's call —
  ``establish_guild_access`` — because the standing has to be computed in the
  same breath. A routing without one answers no to every membership leg.
* ``guild_role=`` passed to ``set_rls_context`` anywhere. There is no such
  parameter: what somebody is in a community is a row the database reads, and
  the setting a routing used to write it into is named nowhere either.

The walk is deliberately syntactic. It matches the call as written, which is
how every one of these is written; it does not follow a callable through a
variable. That is the same tripwire shape as ``sql_injection_guard_test``.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_APP_DIR = Path(__file__).resolve().parents[1]
_BACKEND_DIR = _APP_DIR.parent

#: Where the seam itself lives. These two build and apply a context; nothing
#: else does.
_SEAM = frozenset({"app/api/deps.py", "app/db/session.py"})
_CONTEXT_HOME = "app/api/deps.py"


def _python_files() -> list[Path]:
    return sorted(p for p in _APP_DIR.rglob("*.py"))


def _runtime_files() -> list[Path]:
    """Everything that runs in a request or a job. A test builds fixtures, and
    a fixture standing is a value under assertion rather than one the database
    will be asked to honour."""
    return [p for p in _python_files() if not p.name.endswith("_test.py")]


def _callee(node: ast.Call) -> str | None:
    fn = node.func
    if isinstance(fn, ast.Attribute):
        return fn.attr
    if isinstance(fn, ast.Name):
        return fn.id
    return None


def _calls(path: Path):
    tree = ast.parse(path.read_text())
    rel = path.relative_to(_BACKEND_DIR).as_posix()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            yield rel, node, _callee(node)


def test_only_the_seam_builds_a_guild_context():
    """``GuildContext(...)`` is constructed in one file."""
    offenders = [
        f"{rel}:{node.lineno}"
        for path in _runtime_files()
        for rel, node, callee in _calls(path)
        if callee == "GuildContext" and rel != _CONTEXT_HOME
    ]
    assert offenders == [], (
        "a GuildContext is built by the establishment seam and nowhere else; "
        "call app.api.deps.establish_guild_access instead of constructing one: "
        + ", ".join(offenders)
    )


def test_only_the_seam_builds_an_install_context():
    """``InstallContext(...)`` is constructed in one file."""
    offenders = [
        f"{rel}:{node.lineno}"
        for path in _runtime_files()
        for rel, node, callee in _calls(path)
        if callee == "InstallContext" and rel != _CONTEXT_HOME
    ]
    assert offenders == [], (
        "an InstallContext is built by the establishment seam and nowhere "
        "else; call app.api.deps.establish_install_access instead of "
        "constructing one: " + ", ".join(offenders)
    )


def test_only_the_seam_routes_a_person_into_a_community():
    """``set_rls_context`` never takes a user and a community together."""
    offenders = []
    for path in _python_files():
        for rel, node, callee in _calls(path):
            if callee != "set_rls_context" or rel in _SEAM:
                continue
            named = {k.arg for k in node.keywords if k.value is not None}
            if {"user_id", "guild_id"} <= named:
                offenders.append(f"{rel}:{node.lineno}")
    assert offenders == [], (
        "routing a user into a guild takes the standing the seam computes; "
        "call app.api.deps.establish_guild_access (or, in a test, "
        "app.testing.route_as): " + ", ".join(offenders)
    )


def test_no_routing_carries_a_role():
    """``guild_role=`` is not a parameter of anything here."""
    offenders = [
        f"{rel}:{node.lineno}"
        for path in _python_files()
        for rel, node, callee in _calls(path)
        if callee == "set_rls_context"
        and any(k.arg == "guild_role" for k in node.keywords)
    ]
    assert offenders == [], (
        "a routing states which community it is in, never who the reader is "
        "there: " + ", ".join(offenders)
    )


#: The setting a routing used to write its claim into. Spelled in pieces so
#: this file is not itself what the walk below finds.
_CLAIMED_ROLE_SETTING = "app." + "current_guild_role"


def test_the_setting_a_routing_used_to_claim_is_gone():
    """No rendered policy, and no call site, names it any more."""
    naming_it = [
        p.relative_to(_BACKEND_DIR).as_posix()
        for p in _python_files()
        if _CLAIMED_ROLE_SETTING in p.read_text()
    ]
    assert naming_it == [], (
        f"{_CLAIMED_ROLE_SETTING} was the claim a routing made; the admin fact "
        "is app.guild_admin, written from a lookup: " + ", ".join(naming_it)
    )
