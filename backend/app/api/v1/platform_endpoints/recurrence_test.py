async def test_a_preview_lists_the_next_starts(client, acting_user):
    """A rule picked in Berlin comes back as stored, with its shift and next
    starts; a rule a task can't have is refused."""
    a = await acting_user()
    picked = {
        "rule": "FREQ=MONTHLY;BYDAY=2MO",
        # Monday 12 October, 00:30 in Berlin.
        "start": "2026-10-11T22:30:00Z",
        "tz": "Europe/Berlin",
        "kind": "event",
        "count": 2,
    }
    response = await client.post(
        "/api/v1/recurrence/preview", headers=a.headers, json=picked
    )
    assert response.status_code == 200
    assert response.json() == {
        "rule": "RRULE:FREQ=MONTHLY;BYDAY=2MO",
        "shift": 1440,
        "occurrences": ["2026-10-11T22:30:00Z", "2026-11-08T22:30:00Z"],
    }

    # A stored rule previews with its own shift, whatever zone asks.
    stored = await client.post(
        "/api/v1/recurrence/preview",
        headers=a.headers,
        json={**picked, "tz": "America/New_York", "shift": 1440},
    )
    assert stored.json()["occurrences"] == response.json()["occurrences"]

    refused = await client.post(
        "/api/v1/recurrence/preview",
        headers=a.headers,
        json={**picked, "rule": "FREQ=HOURLY", "kind": "task"},
    )
    assert refused.status_code == 422
    assert refused.json()["detail"] == "RECURRENCE_INVALID"
