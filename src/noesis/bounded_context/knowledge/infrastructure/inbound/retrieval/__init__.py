"""Knowledge adapters for the Retrieval context (D17).

They satisfy Retrieval's ports structurally, return kernel contracts only and import nothing from
the Retrieval context.
"""

from .catalog_availability_inbound_adapter import CatalogAvailabilityInboundAdapter
from .neo4j_indexable_record_reader_adapter import Neo4jIndexableRecordReaderAdapter
from .neo4j_record_change_feed_adapter import Neo4jRecordChangeFeedAdapter
from .neo4j_record_neighbour_reader_adapter import Neo4jRecordNeighbourReaderAdapter
from .neo4j_record_state_reader_adapter import Neo4jRecordStateReaderAdapter
from .neo4j_record_text_search_adapter import Neo4jRecordTextSearchAdapter
from .neo4j_resource_catalog_reader_adapter import Neo4jResourceCatalogReaderAdapter

__all__ = [
    "CatalogAvailabilityInboundAdapter",
    "Neo4jIndexableRecordReaderAdapter",
    "Neo4jRecordChangeFeedAdapter",
    "Neo4jRecordNeighbourReaderAdapter",
    "Neo4jRecordStateReaderAdapter",
    "Neo4jRecordTextSearchAdapter",
    "Neo4jResourceCatalogReaderAdapter",
]
