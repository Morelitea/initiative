"""The platform totals and the pool report."""

from __future__ import annotations

from prometheus_client import REGISTRY

from app.core import metrics


def test_a_status_nobody_holds_any_more_stops_being_reported():
    metrics.record_platform_totals(
        users_by_status={"active": 3, "suspended": 1},
        guilds_by_status={"active": 2},
        live_sessions=4,
        active_by_window={"1d": 1},
    )
    metrics.record_platform_totals(
        users_by_status={"active": 4},
        guilds_by_status={"active": 2},
        live_sessions=5,
        active_by_window={"1d": 2},
    )

    assert REGISTRY.get_sample_value("initiative_users", {"status": "active"}) == 4
    assert (
        REGISTRY.get_sample_value("initiative_users", {"status": "suspended"}) is None
    )
    assert REGISTRY.get_sample_value("initiative_sessions_active") == 5
    assert REGISTRY.get_sample_value("initiative_active_users", {"window": "1d"}) == 2


def test_a_page_view_outside_the_route_list_is_counted_as_other():
    before = (
        REGISTRY.get_sample_value(
            "initiative_page_views_total", {"route": metrics.OTHER_PAGE}
        )
        or 0
    )

    metrics.record_page_view("/c/42/projects/913")

    assert (
        REGISTRY.get_sample_value(
            "initiative_page_views_total", {"route": metrics.OTHER_PAGE}
        )
        == before + 1
    )
    assert (
        REGISTRY.get_sample_value(
            "initiative_page_views_total", {"route": "/c/42/projects/913"}
        )
        is None
    )
