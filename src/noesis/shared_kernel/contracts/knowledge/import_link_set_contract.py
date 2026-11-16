"""Versioned, JSON-native import link-set boundary."""

from typing import Literal

from pydantic import Field

from noesis.shared_kernel.contracts.knowledge.import_knowledge_request_contract import (
    ImportActorContract,
)
from noesis.utils import FrozenObject


class ImportLinkContract(FrozenObject):
    """One grouped outgoing edge."""

    target_record_id: str
    link_type: Literal["links_to", "embeds"]
    count: int = Field(ge=1)
    anchors: tuple[str, ...] = ()


class ImportLinkSetRequestContract(FrozenObject):
    """Replace this source's migrated links as one unit."""

    contract_version: Literal[1] = 1
    space_key: str
    source_record_id: str
    origin_tag: str
    links: tuple[ImportLinkContract, ...]
    actor: ImportActorContract


class ImportLinkSetOutcomeContract(FrozenObject):
    """Actual or assessed result; an empty unstored set is unchanged."""

    contract_version: Literal[1] = 1
    outcome: Literal["created", "replaced", "unchanged", "blocked"]
    source_record_id: str
    edges: int
    block_reason: (
        Literal["record_not_found", "target_not_in_space", "idempotency_key_reused"] | None
    ) = None
    replayed: bool = False
