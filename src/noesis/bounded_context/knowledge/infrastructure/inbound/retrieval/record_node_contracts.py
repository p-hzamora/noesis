"""Shared mapping of record and revision nodes to the kernel contracts (inbound adapters only)."""

from typing import Any

type NodeProperties = dict[str, Any]


def record_type_of(labels: list[str]) -> str | None:
    """`knowledge`, `experience` or `catalog_entry` for a record node's labels; else None."""
    if "Knowledge" in labels:
        return "knowledge"
    if "Experience" in labels:
        return "experience"
    if "CatalogEntry" in labels:
        return "catalog_entry"
    return None


def ownership_of(record_type: str, node: NodeProperties) -> str | None:
    """`ownership` of a record node; null for a type without ownership (an Experience)."""
    return str(node["ownership"]) if record_type == "knowledge" else None
