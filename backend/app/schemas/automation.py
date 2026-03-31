"""Pydantic schemas for the automation system.

Covers flow CRUD payloads, run/step read payloads, and a lightweight
flow graph validator used on create/update.
"""

from __future__ import annotations

from collections import defaultdict, deque
from datetime import datetime
from typing import Any, List, Optional

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Flow graph validation
# ---------------------------------------------------------------------------


def validate_flow_graph(flow_data: dict[str, Any]) -> list[str]:
    """Validate a flow graph structure.

    Checks:
    - ``nodes`` is a non-empty list.
    - Exactly one node has ``type == "trigger"``.
    - The graph defined by ``edges`` is acyclic (topological sort).

    Returns a list of warning strings. An empty list means the graph is valid.
    Raises nothing — callers decide whether warnings are fatal.
    """
    warnings: list[str] = []

    nodes: list[dict[str, Any]] = flow_data.get("nodes", [])
    edges: list[dict[str, Any]] = flow_data.get("edges", [])

    if not nodes:
        warnings.append("Flow must contain at least one node.")
        return warnings

    # -- trigger count --
    trigger_nodes = [n for n in nodes if n.get("type") == "trigger"]
    if len(trigger_nodes) == 0:
        warnings.append("Flow must contain exactly one trigger node.")
    elif len(trigger_nodes) > 1:
        warnings.append(
            f"Flow contains {len(trigger_nodes)} trigger nodes; "
            "exactly one is required."
        )

    # -- cycle detection via Kahn's algorithm --
    node_ids = {n.get("id") for n in nodes if n.get("id") is not None}
    adjacency: dict[Any, list[Any]] = defaultdict(list)
    in_degree: dict[Any, int] = {nid: 0 for nid in node_ids}

    for edge in edges:
        src = edge.get("source")
        tgt = edge.get("target")
        if src in node_ids and tgt in node_ids:
            adjacency[src].append(tgt)
            in_degree[tgt] = in_degree.get(tgt, 0) + 1

    queue: deque[Any] = deque(nid for nid, deg in in_degree.items() if deg == 0)
    visited_count = 0
    while queue:
        current = queue.popleft()
        visited_count += 1
        for neighbor in adjacency[current]:
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    if visited_count != len(node_ids):
        warnings.append("Flow graph contains a cycle.")

    return warnings


# ---------------------------------------------------------------------------
# Flow schemas
# ---------------------------------------------------------------------------


class AutomationFlowCreate(BaseModel):
    """Payload to create a new automation flow."""

    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    initiative_id: int
    flow_data: dict  # { nodes: [...], edges: [...] }
    enabled: bool = False


class AutomationFlowUpdate(BaseModel):
    """Partial update payload for an automation flow."""

    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    description: Optional[str] = None
    flow_data: Optional[dict] = None
    enabled: Optional[bool] = None


class AutomationFlowRead(BaseModel):
    """Full flow detail including the graph payload."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    guild_id: int
    initiative_id: int
    name: str
    description: Optional[str]
    flow_data: dict
    enabled: bool
    created_by_id: int
    created_at: datetime
    updated_at: datetime


class AutomationFlowListItem(BaseModel):
    """List item — omits flow_data to keep list responses small."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: Optional[str]
    enabled: bool
    created_at: datetime
    updated_at: datetime


class AutomationFlowListResponse(BaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    items: List[AutomationFlowListItem]
    total_count: int
    page: int
    page_size: int
    has_next: bool


# ---------------------------------------------------------------------------
# Run / step read schemas
# ---------------------------------------------------------------------------


class AutomationRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    flow_id: int
    flow_snapshot: dict
    trigger_event: dict
    status: str
    started_at: datetime
    completed_at: Optional[datetime]
    error: Optional[str]


class AutomationRunStepRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    node_id: str
    node_type: str
    status: str
    input_data: Optional[dict]
    output_data: Optional[dict]
    error: Optional[str]
    started_at: datetime
    completed_at: Optional[datetime]


class AutomationRunDetailRead(AutomationRunRead):
    """Run with nested step details."""

    steps: List[AutomationRunStepRead] = []


class AutomationRunListResponse(BaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    items: List[AutomationRunRead]
    total_count: int
    page: int
    page_size: int
    has_next: bool
