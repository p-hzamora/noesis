"""One graph neighbour of a seed record."""

from typing import Literal

from noesis.utils import FrozenObject


class GraphNeighbourContract(FrozenObject):
    """A Knowledge or Experience record that shares a Source with a seed.

    One item per (neighbour, seed) pair; seeds are not returned as neighbours.

    Attributes:
        contract_version: Schema version of this payload.
        record_id: The neighbour.
        seed_id: The seed it relates to.
        relation: How they relate; `shared_source` is the only value.
        distance: Hops from the seed (1).
        shared_sources: Number of distinct Sources the two records share.
    """

    contract_version: Literal[1] = 1
    record_id: str
    seed_id: str
    relation: Literal["shared_source"] = "shared_source"
    distance: int = 1
    shared_sources: int
