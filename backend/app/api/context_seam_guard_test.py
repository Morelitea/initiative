"""Static guard: one seam establishes who a request is in a community.

What is forbidden here is forbidden rather than reviewed, so there is no
allow-list to add a site to.

* **What the seam builds is built only in ``app/api/deps.py``**, in anything
  that runs: a person's standing (``GuildContext``) or an installed app's
  (``InstallContext``), the routing shapes that carry one (``Member``,
  ``ContentGrantee``, ``SettingsGrantee``, ``Install``), and the credential
  those record (``SignIn``), which is where work on somebody's behalf is
  said. Each is what the lookup found and what the standing statement
  computed; building one anywhere else would be a second answer to a question
  the seam has already asked. A unit test's fixture is not one of those answers
  — it is a value under assertion — so the walk skips the test modules.
* **The on-behalf sentinel** is named by the seam and the shapes module alone.
* **A session variable is spelled in ``app/db/gucs.py`` alone.** Every read and
  write takes its name and its SQL from the registry, so what the policies read
  and what a routing writes are one list.

The walk is deliberately syntactic. It matches the call as written, which is
how every one of these is written; it does not follow a callable through a
variable. That is the same tripwire shape as ``sql_injection_guard_test``.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.always


_APP_DIR = Path(__file__).resolve().parents[1]
_BACKEND_DIR = _APP_DIR.parent

#: Where the seam lives.
_SEAM = "app/api/deps.py"

#: What only the seam constructs.
_ESTABLISHED = frozenset(
    {
        "GuildContext",
        "InstallContext",
        "Member",
        "ContentGrantee",
        "SettingsGrantee",
        "Install",
        "SignIn",
    }
)


def _python_files() -> list[Path]:
    return sorted(p for p in _APP_DIR.rglob("*.py"))


def _runtime_files() -> list[Path]:
    """Everything that runs in a request or a job. A test builds fixtures, and
    a fixture standing is a value under assertion rather than one the database
    will be asked to honour."""
    return [p for p in _python_files() if not p.name.endswith("_test.py")]


def _rel(path: Path) -> str:
    return path.relative_to(_BACKEND_DIR).as_posix()


def _callee(node: ast.Call) -> str | None:
    fn = node.func
    if isinstance(fn, ast.Attribute):
        return fn.attr
    if isinstance(fn, ast.Name):
        return fn.id
    return None


#: The seam, and the module that defines the shapes and their defaults.
_HOMES = frozenset({_SEAM, "app/db/request_context.py"})


def test_only_the_seam_builds_what_it_establishes():
    offenders = [
        f"{_rel(path)}:{node.lineno} {_callee(node)}"
        for path in _runtime_files()
        if _rel(path) not in _HOMES
        for node in ast.walk(ast.parse(path.read_text()))
        if isinstance(node, ast.Call) and _callee(node) in _ESTABLISHED
    ]
    assert offenders == [], (
        "a standing, a routing that carries one and the sign-in it records "
        "are built by the establishment seam and nowhere else; call "
        "app.api.deps.establish_guild_access or establish_install_access: "
        + ", ".join(offenders)
    )


#: The on-behalf sentinel's name, in pieces so this file is not what the walk
#: finds.
_SENTINEL = "SYSTEM_" + "SATISFIED"


def test_the_on_behalf_sentinel_stays_in_the_seam():
    naming_it = [
        _rel(p)
        for p in _python_files()
        if _rel(p) not in _HOMES and _SENTINEL in p.read_text()
    ]
    assert naming_it == [], (
        "work on somebody's behalf is routed with on_behalf=True through the "
        "seam: " + ", ".join(naming_it)
    )


#: A session variable read or written by name. ``app._bootstrap_*`` is the
#: bootstrap's own scratch, not request context.
_SPELLED = re.compile(r"(current_setting|set_config)\s*\(\s*'app\.[a-z]")


def test_session_variables_are_spelled_in_the_registry_alone():
    spelled = [
        _rel(p)
        for p in _runtime_files()
        if _rel(p) != "app/db/gucs.py" and _SPELLED.search(p.read_text())
    ]
    assert spelled == [], (
        "read or write a session variable through app.db.gucs: " + ", ".join(spelled)
    )


#: The setting a routing used to write its claim into. Spelled in pieces so
#: this file is not itself what the walk below finds.
_CLAIMED_ROLE_SETTING = "app." + "current_guild_role"


def test_the_setting_a_routing_used_to_claim_is_gone():
    """No rendered policy, and no call site, names it any more."""
    naming_it = [
        _rel(p) for p in _python_files() if _CLAIMED_ROLE_SETTING in p.read_text()
    ]
    assert naming_it == [], (
        f"{_CLAIMED_ROLE_SETTING} was the claim a routing made; the admin fact "
        "is app.guild_admin, written from a lookup: " + ", ".join(naming_it)
    )
