"""One JSONata evaluator process, run as a script by :mod:`jsonata_pool`.

Started as ``python -I jsonata_worker.py <time ms> <depth> <output bytes>
<idle seconds> <address space bytes>``, so it imports the standard library
and the JSONata library and nothing of Initiative. It reads one request at a time from stdin and
writes one answer to stdout, each a length-prefixed JSON document, and exits
when stdin closes or no request arrives for the idle time.

A request is ``{"expression", "document"?, "millis"?, "predicate"?}``; the
answer is ``{"value"}``, ``{"undefined": true}`` or ``{"error", "position"}``.
Bounds are the library's own time and depth guardrails, a check on the
answer's size as JSON, and a limit on the process's address space where the
platform has one. An evaluation that runs out of memory is answered with
``"replace": true``, and the worker exits. An answer is JSON as ``JSON.stringify`` writes it.
"""

from __future__ import annotations

import json
import math
import os
import select
import signal
import struct
import sys
from typing import Any, Optional

import jsonata
from jsonata.parser import Parser
from jsonata.utils import Utils

_LENGTH = struct.Struct(">I")

#: No answer: JSONata's ``undefined``, which is not ``null``.
_UNDEFINED = object()


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


def plain(value: Any, *, top: bool = False) -> Any:
    """An answer as JSON reads it: a function or nothing is left out of an
    object and ``null`` in a list, and nothing at the top is undefined."""
    if value is None or _is_function(value):
        return _UNDEFINED if top else None
    if value is Utils.NULL_VALUE:
        return None
    if isinstance(value, (bool, str)):
        return value
    if isinstance(value, (int, float)):
        return _number(value)
    if isinstance(value, dict):
        return {
            str(key): plain(item)
            for key, item in value.items()
            if item is not None and not _is_function(item)
        }
    if isinstance(value, list):
        return [plain(item) for item in value]
    return _UNDEFINED if top else None


def _clock(millis: int) -> dict[str, Any]:
    """``$now()`` and ``$millis()`` answering one instant, bound as the SDK
    binds them."""
    return {
        "now": jsonata.Jsonata(
            f"function($picture, $timezone) {{ $fromMillis({millis}, $picture, $timezone) }}"
        ).evaluate({}),
        "millis": jsonata.Jsonata(f"function() {{ {millis} }}").evaluate({}),
    }


def _run(expression: str, document: Any, millis: Optional[int], bounds: tuple) -> Any:
    time_ms, depth, _ = bounds
    bounded = jsonata.Jsonata(expression, timeout=time_ms, stack=depth)
    bounded.set_output_convert_nulls(False)
    bindings = _clock(millis) if millis is not None else None
    return plain(bounded.evaluate(document, bindings), top=True)


def answer(request: dict[str, Any], bounds: tuple) -> dict[str, Any]:
    """What one request answers: a value, undefined, or an error."""
    document = request["document"] if "document" in request else None
    try:
        value = _run(request["expression"], document, request.get("millis"), bounds)
        if value is _UNDEFINED:
            return {"undefined": True}
        text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        if len(text.encode("utf-8")) > bounds[2]:
            return {"error": f"the answer is over {bounds[2]} bytes"}
        if request.get("predicate"):
            # ``$boolean`` of the answer, as JSON gives it back.
            truth = _run("$boolean($)", json.loads(text), None, bounds)
            return {"value": truth is True}
        return {"value": value}
    except jsonata.JException as error:
        return {"error": str(error), "position": error.location}
    except RecursionError:
        return {"error": "Stack overflow"}
    except MemoryError:
        return {"error": "the evaluation ran out of memory", "replace": True}
    except Exception as error:  # noqa: BLE001 - every evaluation failure is one answer
        return {"error": str(error) or type(error).__name__}


def _read(stream: int, size: int) -> Optional[bytes]:
    chunks = bytearray()
    while len(chunks) < size:
        chunk = os.read(stream, size - len(chunks))
        if not chunk:
            return None
        chunks += chunk
    return bytes(chunks)


def _write(stream: int, data: bytes) -> None:
    view = memoryview(_LENGTH.pack(len(data)) + data)
    while view:
        view = view[os.write(stream, view) :]


def main(arguments: list[str]) -> None:
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    # The depth bound is the library's; this only keeps Python's own limit
    # from being reached first.
    sys.setrecursionlimit(20_000)
    time_ms, depth, output, idle, address_space = (int(value) for value in arguments)
    bounds = (time_ms, depth, output)
    try:
        import resource

        resource.setrlimit(resource.RLIMIT_AS, (address_space, address_space))
    except (ImportError, ValueError, OSError):
        pass
    stdin, stdout = sys.stdin.fileno(), sys.stdout.fileno()
    while True:
        ready, _, _ = select.select([stdin], [], [], idle)
        if not ready:
            return
        header = _read(stdin, _LENGTH.size)
        if header is None:
            return
        body = _read(stdin, _LENGTH.unpack(header)[0])
        if body is None:
            return
        reply = answer(json.loads(body), bounds)
        _write(stdout, json.dumps(reply, ensure_ascii=False).encode("utf-8"))
        if reply.get("replace"):
            return


if __name__ == "__main__":
    main(sys.argv[1:])
