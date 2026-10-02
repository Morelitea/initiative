"""JSONata, as Initiative evaluates a declarative app's expressions.

Standard JSONata (``jsonata-python``, a port of the reference implementation),
with no functions added, answering what the SDK's ``evaluate`` answers: the
same three bounds from the same contract, ``expressionTimeMs``,
``expressionDepth`` and ``expressionOutputBytes``, and ``$now()`` and
``$millis()`` fixed to the time of the call. Passing a bound is a failure, as
an expression that raises an error is (:class:`ExpressionError`).

**Where it runs.** The library checks the time and depth bounds between
evaluation steps, as the reference implementation does. One step can still run
long on its own (a regular expression, a large ``$pad``), so every evaluation
runs in a small pool of worker processes, and a worker still busy after the
time bound and a grace period is stopped and replaced. Each worker evaluates
one expression at a time; the documents travel as JSON, which is also how the
output bound is measured.

An answer comes back as plain JSON, or :data:`UNDEFINED` when the expression
answers nothing.
"""

from __future__ import annotations

import asyncio
import json
import math
import multiprocessing
import os
import signal
import sys
import threading
import time
from multiprocessing.connection import Connection
from typing import Any, Optional

import jsonata
from jsonata.parser import Parser
from jsonata.utils import Utils

from app.services.marketplace import contract

__all__ = [
    "DEPTH",
    "OUTPUT_BYTES",
    "TIME_MS",
    "UNDEFINED",
    "ExpressionError",
    "evaluate",
    "holds",
    "parse",
    "step_reads",
]

TIME_MS = contract.cap("expressionTimeMs")
DEPTH = contract.cap("expressionDepth")
OUTPUT_BYTES = contract.cap("expressionOutputBytes")

#: How long past the time bound a worker may take to answer, for the document
#: to cross the pipe both ways, before it is stopped.
_GRACE_SECONDS = 1.0
#: Workers per process. Evaluations are short; more than this waiting at once
#: wait for one to come free, within the same deadline.
_POOL_SIZE = min(4, os.cpu_count() or 1)


class _Undefined:
    """JSONata's ``undefined``: no answer, which is not ``null``."""

    _instance: Optional["_Undefined"] = None

    def __new__(cls) -> "_Undefined":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "UNDEFINED"


UNDEFINED: Any = _Undefined()


class ExpressionError(Exception):
    """An expression that does not parse, failed, or passed one of its bounds."""

    def __init__(self, message: str, position: Optional[int] = None) -> None:
        super().__init__(message)
        self.position = position


def _failure(error: BaseException) -> ExpressionError:
    if isinstance(error, jsonata.JException):
        return ExpressionError(str(error), error.location)
    if isinstance(error, RecursionError):
        return ExpressionError("Stack overflow")
    return ExpressionError(str(error) or type(error).__name__)


def parse(text: str) -> Any:
    """An expression's syntax tree. Raises :class:`ExpressionError` when
    ``text`` is not a JSONata expression."""
    try:
        return jsonata.Jsonata(text).ast
    except Exception as error:  # noqa: BLE001 - every parser failure is one answer
        raise _failure(error) from error


def step_reads(tree: Any) -> set[str]:
    """The step names a syntax tree reads at its root, as ``steps.<name>`` or
    ``$$.steps.<name>``."""
    names: set[str] = set()
    seen: set[int] = set()

    def walk(node: Any) -> None:
        if isinstance(node, list):
            for child in node:
                walk(child)
            return
        if not isinstance(node, Parser.Symbol) or id(node) in seen:
            return
        seen.add(id(node))
        steps = getattr(node, "steps", None) if node.type == "path" else None
        if isinstance(steps, list) and steps:
            first = steps[0]
            start = 1 if (first.type, first.value) == ("variable", "$") else 0
            if (
                len(steps) > start + 1
                and (steps[start].type, steps[start].value) == ("name", "steps")
                and steps[start + 1].type == "name"
            ):
                names.add(str(steps[start + 1].value))
        for key, child in vars(node).items():
            if key != "_outer_instance":
                walk(child)

    walk(tree)
    return names


# --- one evaluation, in a worker ---------------------------------------------


def _is_function(value: Any) -> bool:
    return isinstance(value, (jsonata.Jsonata.JFunctionCallable, Parser.Symbol))


def _number(value: float) -> Any:
    """A number as a double holds it and ``JSON.stringify`` writes it: integral
    below 1e21 as an integer, otherwise as a float."""
    as_float = float(value)
    if not math.isfinite(as_float):
        return None
    if as_float.is_integer() and abs(as_float) < 1e21:
        return int(as_float)
    return as_float


def _plain(value: Any, *, top: bool = False) -> Any:
    """An answer as JSON reads it, the way ``JSON.stringify`` writes it: a
    function or nothing is left out of an object and ``null`` in a list, and
    nothing at the top is undefined."""
    if value is None or _is_function(value):
        return UNDEFINED if top else None
    if value is Utils.NULL_VALUE:
        return None
    if isinstance(value, (bool, str)):
        return value
    if isinstance(value, (int, float)):
        return _number(value)
    if isinstance(value, dict):
        return {
            str(key): _plain(item)
            for key, item in value.items()
            if item is not None and not _is_function(item)
        }
    if isinstance(value, list):
        return [_plain(item) for item in value]
    return UNDEFINED if top else None


def _clock(millis: int) -> dict[str, Any]:
    """``$now()`` and ``$millis()`` answering one instant, bound as the SDK
    binds them."""
    return {
        "now": jsonata.Jsonata(
            f"function($picture, $timezone) {{ $fromMillis({millis}, $picture, $timezone) }}"
        ).evaluate({}),
        "millis": jsonata.Jsonata(f"function() {{ {millis} }}").evaluate({}),
    }


def _run(expression: str, document: Any, millis: Optional[int]) -> Any:
    bounded = jsonata.Jsonata(expression, timeout=TIME_MS, stack=DEPTH)
    bounded.set_output_convert_nulls(False)
    bindings = _clock(millis) if millis is not None else None
    return _plain(bounded.evaluate(document, bindings), top=True)


def _answer(request: dict[str, Any]) -> dict[str, Any]:
    """What one request to a worker answers: a value, undefined, or an error."""
    document = request["document"] if "document" in request else None
    try:
        value = _run(request["expression"], document, request.get("millis"))
        if value is UNDEFINED:
            return {"undefined": True}
        text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        if len(text.encode("utf-8")) > OUTPUT_BYTES:
            return {"error": f"the answer is over {OUTPUT_BYTES} bytes"}
        if request.get("predicate"):
            # ``$boolean`` of the answer, as JSON gives it back.
            truth = _run("$boolean($)", json.loads(text), None)
            return {"value": truth is True}
        return {"value": value}
    except Exception as error:  # noqa: BLE001 - every evaluation failure is one answer
        failure = _failure(error)
        return {"error": str(failure), "position": failure.position}


def _serve(connection: Connection) -> None:
    """A worker: one request at a time, until the pipe closes."""
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    # The depth bound is the library's; this only keeps Python's own limit
    # from being reached first.
    sys.setrecursionlimit(20_000)
    while True:
        try:
            raw = connection.recv_bytes()
        except (EOFError, OSError):
            return
        reply = _answer(json.loads(raw))
        connection.send_bytes(json.dumps(reply, ensure_ascii=False).encode("utf-8"))


# --- the pool ----------------------------------------------------------------

_CONTEXT = multiprocessing.get_context("spawn")


class _Worker:
    def __init__(self) -> None:
        parent, child = _CONTEXT.Pipe()
        self.process = _CONTEXT.Process(
            target=_serve, args=(child,), daemon=True, name="jsonata"
        )
        self.process.start()
        child.close()
        self.connection = parent

    def stop(self) -> None:
        self.process.kill()
        self.process.join(timeout=5)
        self.connection.close()


_lock = threading.Condition()
_idle: list[_Worker] = []
_live = 0


def _take(deadline: float) -> _Worker:
    global _live
    with _lock:
        while not _idle and _live >= _POOL_SIZE:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ExpressionError("no evaluator came free in time")
            _lock.wait(remaining)
        if _idle:
            return _idle.pop()
        _live += 1
    try:
        return _Worker()
    except BaseException:
        _give_back(None)
        raise


def _give_back(worker: Optional[_Worker]) -> None:
    global _live
    with _lock:
        if worker is None:
            _live -= 1
        else:
            _idle.append(worker)
        _lock.notify()


def _ask(request: bytes) -> dict[str, Any]:
    """Send one request to a worker and wait, within the deadline, for it."""
    budget = TIME_MS / 1000 + _GRACE_SECONDS
    worker = _take(time.monotonic() + budget)
    try:
        worker.connection.send_bytes(request)
        if not worker.connection.poll(budget):
            raise ExpressionError(f"timeout after {TIME_MS} milliseconds")
        reply = json.loads(worker.connection.recv_bytes())
    except BaseException as error:
        worker.stop()
        _give_back(None)
        if isinstance(error, ExpressionError):
            raise
        raise ExpressionError("the evaluator stopped") from error
    _give_back(worker)
    return reply


def _request(text: str, document: Any, millis: Optional[int], predicate: bool) -> bytes:
    body: dict[str, Any] = {"expression": text, "predicate": predicate}
    if document is not UNDEFINED:
        body["document"] = document
    if millis is not None:
        body["millis"] = millis
    return json.dumps(body, ensure_ascii=False).encode("utf-8")


async def _evaluate(
    text: str, document: Any, millis: Optional[int], predicate: bool
) -> dict[str, Any]:
    reply = await asyncio.to_thread(_ask, _request(text, document, millis, predicate))
    if "error" in reply:
        raise ExpressionError(reply["error"], reply.get("position"))
    return reply


async def evaluate(text: str, document: Any, *, millis: Optional[int] = None) -> Any:
    """Evaluate one expression over ``document``, within the contract's bounds.

    ``millis`` fixes what ``$now()`` and ``$millis()`` answer; absent, they
    answer the moment of evaluation. ``document`` must be JSON, with
    :data:`UNDEFINED` for no input at all.
    """
    reply = await _evaluate(text, document, millis, False)
    return UNDEFINED if reply.get("undefined") else reply["value"]


async def holds(text: str, document: Any, *, millis: Optional[int] = None) -> bool:
    """Whether a predicate holds: JSONata's ``$boolean`` of its answer is true."""
    reply = await _evaluate(text, document, millis, True)
    return reply.get("value") is True
