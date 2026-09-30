async def test_a_preview_converts_both_ways_and_lists_the_next_starts(
    client, acting_user
):
    """Days picked in Berlin come back as the stored rule in UTC terms with the
    next starts; the stored rule reads back as picked; a rule a task can't have
    is refused."""
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
    body = response.json()
    stored = "RRULE:FREQ=MONTHLY;BYDAY=SU;BYMONTHDAY=7,8,9,10,11,12,13"
    assert body == {
        "rule": stored,
        "local_rule": "RRULE:FREQ=MONTHLY;BYDAY=2MO",
        "occurrences": ["2026-10-11T22:30:00Z", "2026-11-08T22:30:00Z"],
        "exact": True,
    }

    back = await client.post(
        "/api/v1/recurrence/preview",
        headers=a.headers,
        json={**picked, "rule": stored, "terms": "utc"},
    )
    assert back.json()["local_rule"] == "RRULE:FREQ=MONTHLY;BYDAY=2MO"

    refused = await client.post(
        "/api/v1/recurrence/preview",
        headers=a.headers,
        json={**picked, "rule": "FREQ=HOURLY", "kind": "task"},
    )
    assert refused.status_code == 422
    assert refused.json()["detail"] == "RECURRENCE_INVALID"
