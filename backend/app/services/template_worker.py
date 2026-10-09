"""The template compiler in a worker process, for :mod:`worker_host`.

The host loads this module by path and calls :func:`start` with ``<compiler
script> <heap bytes>``: the server build of the template compiler
(``frontend/src/lib/widgets/serverTemplates.ts``, built by ``pnpm
build:editor-server``), run in an embedded V8 held to that much heap. This
imports the standard library and ``mini-racer`` and nothing of Initiative.

A request is ``{"template": <source>, "returns": [<declared return>],
"strings": [<key>]}``, answered ``{"problems": [<message>]}``, empty when the
template compiles. One the engine cannot run is answered ``{"error"}``; one
that runs out of heap also carries ``"replace": true``, and the worker exits.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from py_mini_racer import JSEvalException, JSOOMException, MiniRacer


def answer(engine: MiniRacer, request: dict[str, Any]) -> dict[str, Any]:
    """What one request answers: the template's problems, or an error."""
    try:
        problems = engine.call(
            "serverTemplates.checkWidget",
            request["template"],
            json.dumps(request["returns"]),
            json.dumps(request["strings"]),
        )
        return {"problems": json.loads(problems)}
    except JSOOMException:
        return {"error": "the template compiler ran out of memory", "replace": True}
    except JSEvalException as error:
        return {"error": str(error).splitlines()[0]}


def start(arguments: list[str]) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """Load the compiler into a fresh engine, and answer requests with it."""
    script, heap_bytes = arguments
    engine = MiniRacer()
    engine.set_hard_memory_limit(int(heap_bytes))
    engine.eval(Path(script).read_text(encoding="utf-8"))
    return lambda request: answer(engine, request)
