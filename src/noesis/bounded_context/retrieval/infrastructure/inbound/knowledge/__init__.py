"""Adapters that implement the kernel port interfaces Knowledge consumes."""

from .related_record_finder_adapter import RelatedRecordFinderAdapter
from .similar_record_finder_adapter import SimilarRecordFinderAdapter

__all__ = ["RelatedRecordFinderAdapter", "SimilarRecordFinderAdapter"]
