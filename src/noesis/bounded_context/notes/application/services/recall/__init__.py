"""Recall rules: search queries, secret masking and briefing grounding."""

from .briefing_grounder import BriefingGrounder
from .rank_fusion import RANK_FUSION_OFFSET, RankedNotes, fuse_rankings
from .recall_query_builder import (
    CHARS_PER_TOKEN,
    MAX_QUERIES,
    OVERFETCH_CAP,
    OVERFETCH_FACTOR,
    PER_QUERY_CAP,
    RecallQueryBuilder,
)
from .secret_redactor import SecretRedactor

__all__ = [
    "CHARS_PER_TOKEN",
    "MAX_QUERIES",
    "OVERFETCH_CAP",
    "OVERFETCH_FACTOR",
    "PER_QUERY_CAP",
    "RANK_FUSION_OFFSET",
    "BriefingGrounder",
    "RankedNotes",
    "RecallQueryBuilder",
    "SecretRedactor",
    "fuse_rankings",
]
