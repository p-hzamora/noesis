"""Consolidation ports."""

from .i_consolidation_guard_lookup import IConsolidationGuardLookup
from .i_consolidation_read_repository import IConsolidationReadRepository
from .i_similar_record_finder import ISimilarRecordFinder

__all__ = ["IConsolidationGuardLookup", "IConsolidationReadRepository", "ISimilarRecordFinder"]
