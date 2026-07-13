"""Unit tests for tasks-table adapter helpers."""

from types import SimpleNamespace

import pytest

from app.services.export.adapters.tasks_table import _thread_comments

pytestmark = pytest.mark.unit


def _c(id: int, parent: int | None = None):
    return SimpleNamespace(id=id, parent_comment_id=parent)


def test_thread_comments_nests_replies_under_parents():
    # Chronological input: root A, root B, reply to A, reply to that reply.
    a, b, a_reply, a_reply_reply = _c(1), _c(2), _c(3, 1), _c(4, 3)
    ordered = _thread_comments([a, b, a_reply, a_reply_reply])
    # A, then its reply subtree (depth 1, 2), then root B — not flat order.
    assert [(c.id, d) for c, d in ordered] == [(1, 0), (3, 1), (4, 2), (2, 0)]


def test_thread_comments_preserves_order_within_a_level():
    a, r1, r2 = _c(1), _c(2, 1), _c(3, 1)
    ordered = _thread_comments([a, r1, r2])
    assert [c.id for c, _ in ordered] == [1, 2, 3]  # replies in input order


def test_thread_comments_treats_orphans_as_roots():
    """A reply whose parent isn't in the set (parent deleted / not loaded) is
    kept as a root so nothing is dropped."""
    orphan = _c(5, 99)
    ordered = _thread_comments([orphan])
    assert [(c.id, d) for c, d in ordered] == [(5, 0)]


def test_thread_comments_handles_a_very_deep_chain_without_recursion():
    """A long single reply chain (each replying to the previous) must not blow
    Python's recursion limit — the walk is an explicit-stack DFS."""
    chain = [_c(1)]
    for i in range(2, 3001):
        chain.append(_c(i, i - 1))  # each replies to its predecessor
    ordered = _thread_comments(chain)
    assert len(ordered) == 3000
    assert ordered[0] == (chain[0], 0)
    assert ordered[-1][0].id == 3000
    assert ordered[-1][1] == 2999  # depth grows with the chain


def test_flatten_mentions_keeps_display_text():
    from app.services.export.adapters.tasks_table import _flatten_mentions

    assert _flatten_mentions("ping @[Ada L](7), see #task[Fix boss](12)") == (
        "ping @Ada L, see Fix boss"
    )
    assert _flatten_mentions("#doc[Map](3) and #project[Arc](4)") == "Map and Arc"
    # Plain markdown links are NOT mentions — untouched.
    assert _flatten_mentions("[text](5)") == "[text](5)"
