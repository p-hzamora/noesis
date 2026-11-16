"""Canonical content digest of a complete outgoing link set."""

import hashlib
import json
from collections.abc import Iterable

from noesis.bounded_context.knowledge.domain.value_objects.record_link import RecordLink
from noesis.shared_kernel.domain.value_objects import ValueObject


class LinkSetDigest(ValueObject):
    """Order-independent hash including the edge origin."""

    value: str

    @classmethod
    def of(cls, links: Iterable[RecordLink], origin: str) -> LinkSetDigest:
        """Hash sorted targets, kinds, counts and canonical anchors."""
        rows: list[tuple[str, str, int, tuple[str, ...]]] = sorted(
            (link.target_record_id.value, link.link_type, link.count, link.anchors)
            for link in links
        )
        canonical: str = json.dumps(
            {"origin": origin, "links": rows}, sort_keys=True, separators=(",", ":")
        )
        return cls(value=f"sha256:{hashlib.sha256(canonical.encode()).hexdigest()}")
