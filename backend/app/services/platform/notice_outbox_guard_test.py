"""Static guard: notices are delivered by the notice worker.

Something that wants to tell somebody writes a notice (``notifications.notify``,
``notice_outbox.enqueue``), and the worker writes the bell line and sends the
push. The database already keeps a request from writing the bell; this keeps a
sweep or a job on the system engine from going around the worker too. Two
calls are confined to the worker and a short list of named exceptions:

* ``create_notification(...)`` — a bell line.
* ``send_push_to_user(...)`` — a push, sent now.

The walk is syntactic, like ``app/services/tenant/upload_write_guard_test.py``.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.always


_APP_DIR = Path(__file__).resolve().parents[2]
_BACKEND_DIR = _APP_DIR.parent

#: Who may write a bell line, and why.
_BELL_WRITERS = {
    # The worker: a notice's own line, or one it joins.
    "app/services/notifications.py::deliver_notices",
    "app/services/notifications.py::_roll_up_comment",
    "app/services/notifications.py::_roll_up_reaction",
    # The time-out screen reads the reason off this line the moment the
    # suspension commits.
    "app/services/notifications.py::queue_account_suspended",
    # Direct messages deliver on their own path.
    "app/services/platform/dm_notifications.py::_roll_up",
}

#: Who may send a push there and then, and why.
_PUSH_SENDERS = {
    # Direct messages deliver on their own path, to the devices set up for them.
    "app/services/platform/dm_notifications.py::wake_own_devices",
    "app/services/platform/dm_notifications.py::_push",
}


def _callers(name: str) -> set[str]:
    """Every ``path::function`` outside the tests that calls ``name``."""
    found: set[str] = set()
    for path in sorted(_APP_DIR.rglob("*.py")):
        if path.name.endswith("_test.py"):
            continue
        rel = path.relative_to(_BACKEND_DIR).as_posix()
        for fn in ast.walk(ast.parse(path.read_text())):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for node in ast.walk(fn):
                if isinstance(node, ast.Call) and name in (
                    getattr(node.func, "attr", None),
                    getattr(node.func, "id", None),
                ):
                    found.add(f"{rel}::{fn.name}")
    return found


@pytest.mark.parametrize(
    ("name", "allowed"),
    [
        ("create_notification", _BELL_WRITERS),
        ("send_push_to_user", _PUSH_SENDERS),
    ],
)
def test_only_the_worker_delivers_a_notice(name: str, allowed: set[str]):
    assert _callers(name) <= allowed, (
        f"{name} is called outside the notice worker. Write a notice instead "
        "(notifications.notify, or notice_outbox.enqueue)."
    )
