"""The evaluator pool: started on first use, small, and gone when idle or
shut down."""

import time

from app.services.jsonata_pool import Pool


def _pool(**overrides) -> Pool:
    return Pool(
        **{
            "size": 2,
            "time_ms": 1000,
            "depth": 500,
            "output_bytes": 1024,
            "idle_seconds": 300,
            **overrides,
        }
    )


def _running(pool: Pool) -> list[int]:
    return [w.process.pid for w in pool._idle if w.process.poll() is None]


def test_nothing_runs_until_the_first_evaluation_and_shutdown_stops_it():
    pool = _pool()
    assert pool._live == 0

    assert pool.ask({"expression": "1 + 1"}) == {"value": 2}
    (worker,) = pool._idle
    pool.shutdown()

    assert worker.process.poll() is not None
    assert pool._live == 0


def test_an_idle_worker_exits_and_the_next_evaluation_starts_another():
    pool = _pool(idle_seconds=1)
    pool.ask({"expression": "1"})
    (first,) = pool._idle

    first.process.wait(timeout=5)
    assert pool.ask({"expression": '"again"'}) == {"value": "again"}
    assert _running(pool) and first.process.pid not in _running(pool)
    pool.shutdown()


def test_an_answer_past_the_output_bound_is_an_error():
    pool = _pool()
    started = time.monotonic()
    assert "over 1024 bytes" in pool.ask({"expression": '$pad("", 2000, "x")'})["error"]
    assert time.monotonic() - started < 2
    pool.shutdown()
