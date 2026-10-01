"""Two ways a run can differ from the gates': quarantined tests, and a
shuffled order. Both are for the nightly run (.github/workflows/nightly.yml).

A flaky test is marked ``@pytest.mark.quarantine(issue=1234,
since="2026-09-30")`` and leaves every run that doesn't ask for it.
``--quarantined`` runs only those tests, and fails when one has been
quarantined longer than two weeks: by then it is fixed or deleted.

``--shuffle=SEED`` runs the modules in a random order, and each module's tests
in a random order, so a test that passes only after another one does is found.
The same seed gives the same order, which is how every xdist worker agrees on
it and how a failure is reproduced.
"""

import random
from datetime import date, timedelta
from typing import Protocol

import pytest

QUARANTINE_LIMIT = timedelta(days=14)


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("initiative")
    group.addoption(
        "--quarantined",
        action="store_true",
        help="run only the tests marked quarantine",
    )
    group.addoption(
        "--shuffle",
        type=int,
        metavar="SEED",
        help="run modules, and the tests in each, in an order drawn from SEED",
    )


def pytest_report_header(config: pytest.Config) -> str | None:
    seed = config.getoption("shuffle")
    return None if seed is None else f"shuffled with --shuffle={seed}"


def quarantined_since(nodeid: str, marker: pytest.Mark) -> date:
    """The day the test's quarantine started."""
    issue, since = marker.kwargs.get("issue"), marker.kwargs.get("since")
    if isinstance(issue, int) and isinstance(since, str):
        try:
            return date.fromisoformat(since)
        except ValueError:
            pass
    raise pytest.UsageError(
        f'{nodeid}: quarantine needs issue=<number> and since="YYYY-MM-DD"'
    )


class _Node(Protocol):
    nodeid: str


def shuffled[N: _Node](items: list[N], seed: int) -> list[N]:
    """The items with their modules shuffled, and each module's tests."""
    rng = random.Random(seed)
    modules: dict[str, list[N]] = {}
    for item in items:
        modules.setdefault(item.nodeid.split("::")[0], []).append(item)
    groups = list(modules.values())
    rng.shuffle(groups)
    for group in groups:
        rng.shuffle(group)
    return [item for group in groups for item in group]


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    only_quarantined = config.getoption("quarantined")
    selected, deselected, overdue = [], [], []
    for item in items:
        marker = item.get_closest_marker("quarantine")
        if marker is None:
            (deselected if only_quarantined else selected).append(item)
            continue
        since = quarantined_since(item.nodeid, marker)
        if only_quarantined and date.today() - since > QUARANTINE_LIMIT:
            overdue.append(f"  {item.nodeid} (#{marker.kwargs['issue']}, {since})")
        (selected if only_quarantined else deselected).append(item)
    if overdue:
        raise pytest.UsageError(
            "Quarantined for more than two weeks; fix or delete:\n" + "\n".join(overdue)
        )
    if deselected:
        config.hook.pytest_deselected(items=deselected)
        items[:] = selected
    seed = config.getoption("shuffle")
    if seed is not None:
        items[:] = shuffled(items, seed)
