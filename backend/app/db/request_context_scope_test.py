"""Request context stays inside its transaction.

``set_config(..., true)`` is scoped to the transaction; ``set_config(..., false)``
is scoped to the connection. The request engines reach Postgres through a pooler
in transaction mode, where a connection is one caller's only until the
transaction ends — so a value written the second way is still there when the
connection is handed to whoever asks next.

CI runs the whole suite that way on purpose, which means a regression is caught
before merge. It is caught *late*, though, and it reads as hundreds of unrelated
failures spread across one xdist worker rather than as one wrong line. These two
checks are the same rule applied to the source, so it reads as the wrong line.
"""

import re
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2]

#: A third argument of ``false`` — the connection-scoped form. The first
#: argument must be a quoted setting name, so this reads SQL and not the prose
#: around it (including the paragraph above).
SESSION_SCOPED = re.compile(r"""set_config\(\s*['"][^'"]+['"][^)]*,\s*false\s*\)""")

_WHY = (
    "Use set_config(..., true) and keep the statements it applies to in the "
    "same transaction, the way app.db.session.set_rls_context does."
)


def _offenders(path: Path) -> list[str]:
    """Lines in ``path`` that set connection-scoped state, numbered."""
    if path.resolve() == Path(__file__).resolve():
        return []
    return [
        f"{path.relative_to(BACKEND)}:{n}: {line.strip()}"
        for n, line in enumerate(path.read_text().splitlines(), 1)
        if SESSION_SCOPED.search(line)
    ]


@pytest.mark.unit
def test_no_endpoint_sets_connection_scoped_state():
    """Every endpoint answers on a pooled engine, so none of them may.

    Scoped to ``app/api`` rather than the whole tree: provisioning, migrations
    and background jobs hold a connection of their own for the length of the
    work, and some of them legitimately need it to carry state.
    """
    found: list[str] = []
    for path in sorted((BACKEND / "app" / "api").rglob("*.py")):
        found.extend(_offenders(path))

    assert not found, (
        "An endpoint set state on the connection rather than the transaction:\n"
        + "\n".join(found)
        + f"\n\n{_WHY}"
    )


@pytest.mark.unit
def test_no_pooled_test_session_sets_connection_scoped_state():
    """``role_session`` hands out the real login roles, on the pooled engines.

    A test that assumes a role there and leaves it on the connection is the
    same defect as an endpoint doing it, and it lands on whichever test draws
    that connection next. The tests that assume a role on the superuser
    ``session`` fixture are a different case — it connects directly, so the
    connection is theirs — and are deliberately not covered here.
    """
    found: list[str] = []
    for path in sorted((BACKEND / "app").rglob("*_test.py")):
        if "role_session" in path.read_text():
            found.extend(_offenders(path))

    assert not found, (
        "A test set state on a pooled connection rather than its transaction:\n"
        + "\n".join(found)
        + f"\n\n{_WHY}"
    )
