"""Export the OpenAPI spec to a JSON file without starting the server.

``--app`` exports the app API's spec instead: what an installed app may call.
"""

import json
import os
import sys
from pathlib import Path

# Add backend to path so imports work
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Set required env vars with dummy values so Settings() validates
# without a .env file (no DB connection or crypto needed for schema export)
# 64-hex dummy satisfying the startup validator; schema export does no crypto.
os.environ.setdefault(
    "SECRET_KEY", "0f1e2d3c4b5a69788796a5b4c3d2e1f00f1e2d3c4b5a69788796a5b4c3d2e1f0"
)

from app.main import app, app_openapi  # noqa: E402


def main():
    args = sys.argv[1:]
    spec = app_openapi() if "--app" in args else app.openapi()
    paths = [arg for arg in args if arg != "--app"]
    output = paths[0] if paths else "-"
    content = json.dumps(spec, indent=2)
    if output == "-":
        print(content)
    else:
        Path(output).write_text(content)


if __name__ == "__main__":
    main()
