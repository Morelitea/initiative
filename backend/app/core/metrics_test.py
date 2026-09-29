"""The platform totals and the pool report."""

from __future__ import annotations

from prometheus_client import REGISTRY

from app.core import metrics


def test_a_status_nobody_holds_any_more_stops_being_reported():
    metrics.record_platform_totals(
        users_by_status={"active": 3, "suspended": 1},
        guilds_by_status={"active": 2},
        live_sessions=4,
    )
    metrics.record_platform_totals(
        users_by_status={"active": 4},
        guilds_by_status={"active": 2},
        live_sessions=5,
    )

    assert REGISTRY.get_sample_value("initiative_users", {"status": "active"}) == 4
    assert (
        REGISTRY.get_sample_value("initiative_users", {"status": "suspended"}) is None
    )
    assert REGISTRY.get_sample_value("initiative_sessions_active") == 5
