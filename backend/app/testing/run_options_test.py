from datetime import date
from types import SimpleNamespace

import pytest

from app.testing.run_options import quarantined_since, shuffled


def test_a_shuffle_keeps_each_module_together_and_repeats_by_seed():
    items = [
        SimpleNamespace(nodeid=f"app/{module}_test.py::test_{n}")
        for module in "abcd"
        for n in range(5)
    ]

    order = shuffled(items, seed=7)

    assert order == shuffled(list(items), seed=7)
    assert order != items
    modules = [item.nodeid.split("::")[0] for item in order]
    assert modules == sorted(modules, key=modules.index)


def test_a_quarantine_names_its_issue_and_day():
    marked = pytest.mark.quarantine(issue=12, since="2026-09-30").mark
    assert quarantined_since("t", marked) == date(2026, 9, 30)

    for kwargs in ({"since": "2026-09-30"}, {"issue": 12, "since": "last week"}):
        with pytest.raises(pytest.UsageError):
            quarantined_since("t", pytest.mark.quarantine(**kwargs).mark)
