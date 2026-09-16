"""Who is allowed to write the request-scoped authorization context.

Two operations look alike and are not:

**Routing a session** — :func:`app.db.session.set_rls_context` — puts the GUCs
on *one session*. Background work does it per guild, and a request routinely
does it to a *second* session while serving (``published_views`` loading a row
as its author, ``intake`` opening a case in the operations guild). It touches
no task-scoped state, which is what makes that safe.

**Establishing a request's context** — ``deps.py``'s
``_apply_guild_session_context``, reached through ``establish_guild_access`` —
routes the session *and* records the contextvars the sync DAC engine reads
without being handed them.

The state the second writes belongs to the task; the session the first routes
does not. Keeping them apart is why routing stays free of task-scoped writes.

So the setters below are the establishment seam's to call. A path that writes
one by hand is either a new seam — which wants saying out loud — or an
establishment that went through the routing primitive instead. This test makes
that a decision rather than an oversight.
"""

import pathlib
import re

import pytest

pytestmark = pytest.mark.unit

#: The modules that define the setters. Excluded because a definition is not a
#: call; everything else under ``app/core/`` is checked like any other file.
DEFINING_MODULES = frozenset(
    {
        "app/core/role_context.py",
        "app/core/pam_context.py",
    }
)

#: The four writers of task-scoped authorization state.
SETTERS = (
    "set_active_role",
    "set_active_grant",
    "set_override_sharing_initiatives",
    "set_content_read_only_guild",
)

#: Where they may be called from, and why each is allowed to.
SEAM = {
    # The establishment seam itself: the member, PAM and break-glass branches.
    "app/api/deps.py": "establishes a request's context",
    # Stands in another guild's shoes for a cross-guild gather, and puts the
    # caller's context back on the way out.
    "app/services/cross_guild.py": "swaps context per guild, restores after",
    # Decides a published view as its author rather than as its reader, and
    # restores what it borrowed.
    "app/services/tenant/published_views.py": "decides as the author, restores",
}


def _backend_root() -> pathlib.Path:
    return pathlib.Path(__file__).resolve().parents[2]


def test_only_the_establishment_seam_writes_the_context():
    """Nothing outside :data:`SEAM` records task-scoped authorization state.

    Adding a file here is allowed — it is a claim that the new caller either
    establishes a request or restores what it borrows. Making that claim in
    this file is the point; acquiring the behaviour silently is not.
    """
    root = _backend_root()
    pattern = re.compile(r"\b(" + "|".join(SETTERS) + r")\s*\(")
    offenders: dict[str, list[str]] = {}
    for path in (root / "app").rglob("*.py"):
        rel = path.relative_to(root).as_posix()
        if rel.endswith("_test.py") or rel in DEFINING_MODULES:
            continue
        if rel in SEAM:
            continue
        found = sorted(set(pattern.findall(path.read_text())))
        if found:
            offenders[rel] = found
    assert not offenders, (
        "these write the request's authorization context outside the "
        "establishment seam:\n  "
        + "\n  ".join(f"{f}: {', '.join(s)}" for f, s in sorted(offenders.items()))
        + "\n\nRouting a session is set_rls_context and needs none of these. "
        "If this really is a new seam, add it to SEAM with the reason."
    )


@pytest.mark.parametrize("rel", sorted(SEAM))
def test_every_allowed_caller_still_exists(rel: str):
    """A stale entry would quietly widen what the test above permits."""
    assert (_backend_root() / rel).exists(), f"{rel} is in SEAM but not in the tree"


@pytest.mark.parametrize("rel", sorted(SEAM))
def test_every_allowed_caller_still_writes_the_context(rel: str):
    """And one that stopped writing it should stop being excused."""
    pattern = re.compile(r"\b(" + "|".join(SETTERS) + r")\s*\(")
    assert pattern.search((_backend_root() / rel).read_text()), (
        f"{rel} is excused in SEAM but no longer writes the context — drop it"
    )
