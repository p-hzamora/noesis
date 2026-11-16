"""Adapters that satisfy ports owned by the Knowledge context."""

from .related_record_finder_adapter import RelatedRecordFinderAdapter
from .similar_record_finder_adapter import SimilarRecordFinderAdapter

__all__ = ["RelatedRecordFinderAdapter", "SimilarRecordFinderAdapter"]
