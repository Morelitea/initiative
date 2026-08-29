"""Run the API under the debugger on this checkout's port.

VSCode's launch.json is static JSON: it can substitute a variable but cannot run
a shell, so it has no way to ask which port a linked worktree was allocated. The
debug config points here instead. This asks ``scripts/dev-ports.sh`` — the one
place dev ports are decided — and then starts uvicorn in-process, so breakpoints
land exactly as they did when the config invoked the uvicorn module directly.

Run it by hand the same way:  python scripts/dev_api.py
"""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
DEV_PORTS_SH = BACKEND_DIR.parent / "scripts" / "dev-ports.sh"


def dev_port() -> int:
    """This checkout's backend port, straight from dev-ports.sh.

    An explicit DEV_BACKEND_PORT wins, exactly as it does in the shell scripts.
    """
    pinned = os.environ.get("DEV_BACKEND_PORT")
    if pinned:
        return int(pinned)

    result = subprocess.run(
        [
            "bash",
            "-c",
            f'. {shlex.quote(str(DEV_PORTS_SH))}; printf "%s" "${{DEV_BACKEND_PORT:-}}"',
        ],
        capture_output=True,
        text=True,
    )
    # dev-ports.sh explains itself on stderr when it cannot resolve a port.
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    port = result.stdout.strip()
    if not port:
        raise SystemExit("dev_api: no port for this checkout — see above.")
    return int(port)


if __name__ == "__main__":
    import uvicorn

    # `python -m uvicorn` put the working directory on sys.path, which is how
    # "app.main" resolved before. Running a *script* puts the script's own
    # directory there instead — backend/scripts — so backend/ has to be added
    # back explicitly. PYTHONPATH as well as sys.path: the reloader serves from
    # a spawned subprocess, and that is what carries the path into it.
    os.chdir(BACKEND_DIR)
    sys.path.insert(0, str(BACKEND_DIR))
    existing = os.environ.get("PYTHONPATH")
    os.environ["PYTHONPATH"] = (
        f"{BACKEND_DIR}{os.pathsep}{existing}" if existing else str(BACKEND_DIR)
    )

    uvicorn.run("app.main:app", host="0.0.0.0", port=dev_port(), reload=True)
