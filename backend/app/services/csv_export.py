import csv
import io
import re
from typing import Iterable, Sequence

from app.models.user import User

# UTF-8 BOM so Excel on Windows auto-detects encoding rather than falling back
# to the system code page and garbling accented characters.
_BOM = "\ufeff"


def build_csv(headers: Sequence[str], rows: Iterable[Sequence[object]]) -> bytes:
    """Serialize rows to a UTF-8 encoded CSV byte string with a BOM prefix."""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(headers)
    for row in rows:
        writer.writerow(["" if value is None else value for value in row])
    return (_BOM + buffer.getvalue()).encode("utf-8")


def safe_filename_component(value: str) -> str:
    """Reduce a string to characters that are safe to embed in a download filename."""
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("_")
    return cleaned or "export"


def format_initiative_roles(user: User) -> str:
    """Serialize a user's loaded initiative roles as 'Name: role; Name: role'."""
    roles = getattr(user, "initiative_roles", []) or []
    parts = []
    for entry in roles:
        name = getattr(entry, "initiative_name", None) or ""
        role = getattr(entry, "role", "")
        role_value = role.value if hasattr(role, "value") else role
        parts.append(f"{name}: {role_value}")
    return "; ".join(parts)
