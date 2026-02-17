"""Export the OpenAPI spec to a JSON file without starting the server."""
import json
import sys
from pathlib import Path

# Add backend to path so imports work
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.main import app


def main():
    spec = app.openapi()
    output = sys.argv[1] if len(sys.argv) > 1 else "-"
    content = json.dumps(spec, indent=2)
    if output == "-":
        print(content)
    else:
        Path(output).write_text(content)


if __name__ == "__main__":
    main()
