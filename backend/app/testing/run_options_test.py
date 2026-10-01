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


def test_a_quarantined_test_runs_only_when_asked_for(pytester: pytest.Pytester):
    pytester.makeini(
        "[pytest]\nmarkers = quarantine\nasyncio_default_fixture_loop_scope = function"
    )
    pytester.makepyfile(
        """
        import pytest

        @pytest.mark.quarantine(issue=1, since="2999-01-01")
        def test_flaky(): pass

        def test_plain(): pass
        """
    )
    plugin = ("-p", "app.testing.run_options")

    pytester.runpytest(*plugin).assert_outcomes(passed=1, deselected=1)
    pytester.runpytest(*plugin, "--quarantined").assert_outcomes(passed=1, deselected=1)

    pytester.makepyfile(
        test_old="""
        import pytest

        @pytest.mark.quarantine(issue=2, since="2026-01-01")
        def test_old(): pass
        """
    )
    overdue = pytester.runpytest(*plugin, "--quarantined")
    assert overdue.ret == pytest.ExitCode.USAGE_ERROR
    overdue.stderr.fnmatch_lines(["*test_old.py::test_old (#2, 2026-01-01)"])
