"""Ranking metrics over graded judgments, and latency percentiles."""

import math
from collections.abc import Sequence

CUTOFF = 10


def ndcg_at_k(ranked: Sequence[str], relevance: dict[str, int], k: int = CUTOFF) -> float:
    """nDCG with gain 2^grade - 1 and log2 discount; 0.0 when nothing is relevant."""
    gains = [relevance.get(key, 0) for key in ranked[:k]]
    dcg = sum((2**g - 1) / math.log2(i + 2) for i, g in enumerate(gains))
    ideal = sorted(relevance.values(), reverse=True)[:k]
    idcg = sum((2**g - 1) / math.log2(i + 2) for i, g in enumerate(ideal))
    return dcg / idcg if idcg > 0 else 0.0


def recall_at_k(
    ranked: Sequence[str], relevance: dict[str, int], k: int = CUTOFF, *, min_grade: int = 1
) -> float:
    """Share of records graded at least `min_grade` found in the top k."""
    wanted = {key for key, grade in relevance.items() if grade >= min_grade}
    if not wanted:
        return 0.0
    return len(wanted & set(ranked[:k])) / len(wanted)


def mrr_at_k(ranked: Sequence[str], relevance: dict[str, int], k: int = CUTOFF) -> float:
    """Reciprocal rank of the first record graded at least 1 in the top k."""
    for position, key in enumerate(ranked[:k], start=1):
        if relevance.get(key, 0) >= 1:
            return 1.0 / position
    return 0.0


def percentile(values: Sequence[float], fraction: float) -> float:
    """Nearest-rank percentile (`fraction` in 0..1); 0.0 for no values."""
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(fraction * len(ordered)) - 1))
    return ordered[index]


def latency_summary(seconds: Sequence[float]) -> dict[str, float | int]:
    """Count, p50, p95, mean and max in milliseconds."""
    millis = [value * 1000 for value in seconds]
    return {
        "n": len(millis),
        "p50_ms": round(percentile(millis, 0.50), 1),
        "p95_ms": round(percentile(millis, 0.95), 1),
        "mean_ms": round(sum(millis) / len(millis), 1) if millis else 0.0,
        "max_ms": round(max(millis), 1) if millis else 0.0,
    }


def mean(values: Sequence[float]) -> float:
    """Arithmetic mean, 0.0 for no values."""
    return sum(values) / len(values) if values else 0.0
