"""Canonical content digest of a complete outgoing link set."""

import hashlib
import json
from collections.abc import Iterable
from typing import Any

from noesis.bounded_context.knowledge.domain.value_objects.record_link import RecordLink
from noesis.bounded_context.knowledge.domain.value_objects.record_relation import RecordRelation
from noesis.shared_kernel.domain.value_objects import ValueObject


class LinkSetDigest(ValueObject):
    """Order-independent hash including the edge origin."""

    value: str

    @classmethod
    def of(
        cls,
        links: Iterable[RecordLink],
        origin: str,
        relations: Iterable[RecordRelation] = (),
    ) -> LinkSetDigest:
        """Hash sorted targets, kinds, counts, canonical anchors and, when any, relations."""
        rows: list[tuple[str, str, int, tuple[str, ...]]] = sorted(
            (link.target_record_id.value, link.link_type, link.count, link.anchors)
            for link in links
        )
        content: dict[str, Any] = {"origin": origin, "links": rows}
        relation_rows: list[tuple[str, str]] = sorted(
            (relation.target_record_id.value, relation.relation.value) for relation in relations
        )
        if relation_rows:
            content["relations"] = relation_rows
        canonical: str = json.dumps(content, sort_keys=True, separators=(",", ":"))
        return cls(value=f"sha256:{hashlib.sha256(canonical.encode()).hexdigest()}")
