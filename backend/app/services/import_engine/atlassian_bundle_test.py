"""The one bundle an Atlassian fetch writes."""

from collections import Counter

import pytest

from app.services.import_engine.atlassian_bundle import merge_people

pytestmark = pytest.mark.unit


def test_somebody_in_both_products_is_asked_about_once():
    people = merge_people(
        [
            {"handle": "Robin Ade", "name": "Robin Ade", "comment_count": 3},
            {"handle": "Sam Bee", "name": "Sam Bee", "comment_count": 0},
        ],
        Counter({"robin ade": 2, "Kit Cole": 5}),
    )
    assert [p["handle"] for p in people] == ["Robin Ade", "Kit Cole", "Sam Bee"]
    # Jira's spelling, and its comment count, are the ones kept.
    assert people[0]["comment_count"] == 3
