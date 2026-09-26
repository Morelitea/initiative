"""The current instant, timezone-aware in UTC."""

from datetime import datetime, timezone


def utcnow() -> datetime:
    """Now, in UTC. Tests freeze a module's clock by patching its ``utcnow``."""
    return datetime.now(timezone.utc)
