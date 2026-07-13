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
