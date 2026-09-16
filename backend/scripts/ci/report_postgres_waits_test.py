from __future__ import annotations

import json

import pytest

from scripts.ci.report_postgres_waits import report_once


class FakeConnection:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    async def fetch(self, sql: str, argument: object):
        self.calls.append((sql, argument))
        if len(self.calls) == 1:
            return [
                {
                    "pid": 12,
                    "datname": "initiative_test_worker",
                    "usename": "initiative",
                    "state": "active",
                    "wait_event_type": "Lock",
                    "wait_event": "transactionid",
                    "backend_xid": "91",
                    "backend_xmin": "90",
                    "age_s": 6.2,
                    "blocking_pids": [34],
                }
            ]
        if len(self.calls) == 2:
            return [
                {
                    "pid": 12,
                    "datname": "initiative_test_worker",
                    "usename": "initiative",
                    "state": "active",
                    "wait_event_type": "Lock",
                    "wait_event": "transactionid",
                    "backend_xid": "91",
                    "backend_xmin": "90",
                    "age_s": 6.2,
                    "blocking_pids": [34],
                    "query_preview": "UPDATE comments SET content=$1",
                },
                {
                    "pid": 34,
                    "datname": "initiative_test_worker",
                    "usename": "initiative",
                    "state": "idle in transaction",
                    "wait_event_type": "Client",
                    "wait_event": "ClientRead",
                    "backend_xid": "89",
                    "backend_xmin": None,
                    "age_s": 7.1,
                    "blocking_pids": [],
                    "query_preview": "UPDATE comments SET content='<redacted>'",
                },
            ]
        return [
            {
                "pid": 12,
                "locktype": "transactionid",
                "mode": "ShareLock",
                "granted": False,
                "database_oid": 7,
                "relation_oid": None,
                "schema_name": None,
                "relation_name": None,
                "transaction_id": "42",
            }
        ]


@pytest.mark.asyncio
async def test_reports_wait_and_lock_metadata_with_bounded_redacted_sql(capsys):
    conn = FakeConnection()

    found = await report_once(conn, threshold_seconds=5)

    assert found is True
    lines = capsys.readouterr().out.splitlines()
    activity = json.loads(lines[0].removeprefix("CI_POSTGRES_ACTIVITY "))
    participants = json.loads(lines[1].removeprefix("CI_POSTGRES_PARTICIPANTS "))
    locks = json.loads(lines[2].removeprefix("CI_POSTGRES_LOCKS "))
    assert activity == [
        {
            "age_s": 6.2,
            "backend_xid": "91",
            "backend_xmin": "90",
            "blocking_pids": [34],
            "datname": "initiative_test_worker",
            "pid": 12,
            "state": "active",
            "usename": "initiative",
            "wait_event": "transactionid",
            "wait_event_type": "Lock",
        }
    ]
    assert {row["pid"] for row in participants} == {12, 34}
    assert participants[1]["query_preview"].endswith("'<redacted>'")
    assert locks[0]["granted"] is False
    assert conn.calls[1][1] == [12, 34]
    assert conn.calls[2][1] == [12, 34]
    assert "query_preview" not in conn.calls[0][0].lower()


@pytest.mark.asyncio
async def test_prints_nothing_when_no_long_wait_exists(capsys):
    class EmptyConnection:
        async def fetch(self, _sql: str, _threshold: float):
            return []

    found = await report_once(EmptyConnection(), threshold_seconds=5)

    assert found is False
    assert capsys.readouterr().out == ""
