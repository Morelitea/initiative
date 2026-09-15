"""The report registry: what can be reported, and who handles it."""

from __future__ import annotations

import pytest

from app.core.moderation import (
    PlatformReportTarget,
    ReportOutcome,
    ReportVenue,
    parse_target,
    target_table,
    venue_for,
)
from app.core.search import SearchEntityType
from app.core.tools import Tool

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("target", list(SearchEntityType))
def test_every_community_target_resolves_to_a_venue(target: SearchEntityType):
    """A tool added later must not ship un-reportable."""
    assert venue_for(target) in (ReportVenue.initiative, ReportVenue.platform)


@pytest.mark.parametrize("tool", list(Tool))
def test_every_tool_is_reportable_to_its_own_community(tool: Tool):
    """Derived from `Tool`, so a new one needs no edit to the report code."""
    target = SearchEntityType(tool.value)
    assert venue_for(target) is ReportVenue.initiative


def test_a_guild_level_target_falls_to_the_platform():
    """A tag belongs to no initiative, so no community owns the complaint."""
    assert venue_for(SearchEntityType.tag) is ReportVenue.platform


@pytest.mark.parametrize("target", list(PlatformReportTarget))
def test_identity_targets_are_the_platforms(target: PlatformReportTarget):
    assert venue_for(target) is ReportVenue.platform


def test_the_venue_matches_the_registry_the_policies_are_rendered_from():
    """The venue and the access gate read one declaration, so they agree."""
    from app.db.initiative_rls import INITIATIVE_PATHS

    for target in SearchEntityType:
        scoped = target_table(target) in INITIATIVE_PATHS
        expected = ReportVenue.initiative if scoped else ReportVenue.platform
        assert venue_for(target) is expected, target


def test_a_target_type_nobody_defines_is_refused():
    with pytest.raises(ValueError):
        parse_target("the_vibes")


def test_parsing_accepts_both_planes():
    assert parse_target("comment") is SearchEntityType.comment
    assert parse_target("username") is PlatformReportTarget.username


def test_every_outcome_closes_a_report():
    """There is no "pending" member: a report is work or a record."""
    assert set(ReportOutcome) == {
        ReportOutcome.dismissed,
        ReportOutcome.content_removed,
        ReportOutcome.member_warned,
        ReportOutcome.escalated,
    }
