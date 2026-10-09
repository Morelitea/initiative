"""The template compiler, as the server runs it.

A plug-in's widget and block templates are compiled by the same compiler the
browser runs (``frontend/src/lib/widgets/pluginTemplate.ts``), so a template
that does not compile refuses the plug-in when it is published rather than
reaching a dashboard or a task. Its server build (``frontend/src/lib/widgets/serverTemplates.ts``,
built by ``pnpm build:editor-server``) runs in an embedded V8 in a worker
process (:mod:`app.services.template_worker`, through
:mod:`app.services.worker_pool`). The pool starts on the first check, and a
worker idle for ``_IDLE_SECONDS`` exits, so a server where nobody publishes a
plug-in never starts it.
"""

from __future__ import annotations

import atexit
import threading
from pathlib import Path
from typing import Any, Optional

from app.services.worker_pool import Pool, PoolError

__all__ = ["TemplateEngineError", "check_block", "check_widget", "shutdown"]

_BACKEND = Path(__file__).resolve().parents[2]
#: Where the compiler's server build is: copied beside the backend in the
#: image, built into the frontend in a checkout.
_SCRIPTS = (
    _BACKEND / "editor" / "templates.js",
    _BACKEND.parent / "frontend" / "dist-editor" / "templates.js",
)
_HANDLER = Path(__file__).with_name("template_worker.py")
#: Measured: a template compiles in a few milliseconds once the engine has
#: loaded the compiler, which takes about 40.
_TIME_MS = 5_000
_HEAP_BYTES = 128 * 1024 * 1024
_IDLE_SECONDS = 300


class TemplateEngineError(Exception):
    """The compiler gave no answer: it is not built, or did not run."""


_pool: Optional[Pool] = None
_pool_lock = threading.Lock()


def _script() -> Path:
    for script in _SCRIPTS:
        if script.is_file():
            return script
    raise TemplateEngineError(
        "the template compiler's server build is missing: run "
        "`pnpm build:editor-server` in frontend/"
    )


def _the_pool() -> Pool:
    global _pool
    with _pool_lock:
        if _pool is None:
            script = _script()
            # The app's lifespan stops it; a process that has none stops it
            # on its way out.
            atexit.register(shutdown)
            _pool = Pool(
                handler=_HANDLER,
                arguments=[str(script), str(_HEAP_BYTES)],
                size=1,
                time_ms=_TIME_MS,
                idle_seconds=_IDLE_SECONDS,
            )
        return _pool


def shutdown() -> None:
    """Stop the pool's worker; the next check starts a new pool."""
    global _pool
    with _pool_lock:
        pool, _pool = _pool, None
    if pool is not None:
        pool.shutdown()


def check_widget(
    template: str, returns: list[dict[str, Any]], string_keys: list[str]
) -> list[str]:
    """Every problem with a plug-in widget's template, or none.

    ``returns`` are the declared returns of the endpoint the widget draws, which
    its fields are checked against, and ``string_keys`` the keys of its own
    ``strings``. Blocking: a publish waits for its plug-in's templates.
    """
    return _ask({"template": template, "returns": returns, "strings": string_keys})


def check_block(
    template: str,
    returns: list[dict[str, Any]],
    string_keys: list[str],
    action_keys: list[str],
    page_ids: list[str],
) -> list[str]:
    """Every problem with a plug-in block's template, or none.

    As :func:`check_widget`, with ``returns`` those of the read the block
    draws (none for a block drawn from the task alone), ``action_keys`` its
    actions by key (the endpoint id after ``plugin.<public id>.``) and
    ``page_ids`` the manifest's pages, which its buttons and ``<open>`` name.
    """
    return _ask(
        {
            "kind": "block",
            "template": template,
            "returns": returns,
            "strings": string_keys,
            "actions": action_keys,
            "pages": page_ids,
        }
    )


def _ask(request: dict[str, Any]) -> list[str]:
    try:
        reply = _the_pool().ask(request)
    except PoolError as exc:
        raise TemplateEngineError(str(exc)) from exc
    if "error" in reply:
        raise TemplateEngineError(reply["error"])
    return list(reply["problems"])
