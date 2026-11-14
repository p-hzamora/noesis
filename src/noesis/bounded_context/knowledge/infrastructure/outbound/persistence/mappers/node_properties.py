"""Small helpers shared by the node mappers."""

from typing import Any

type NodeProperties = dict[str, Any]
"""Properties of one node as Neo4j returns or receives them (no nulls are written)."""


def without_nulls(properties: NodeProperties) -> NodeProperties:
    """`properties` without the None values: an absent property, not a null one."""
    return {name: value for name, value in properties.items() if value is not None}
