"""Checks of vectors received from another process (numpy-free)."""

import math
from collections.abc import Sequence

from ....application.ports.embedding import EmbedderUnavailableError

NORM_TOLERANCE: float = 1e-3


def validate_vector(vector: Sequence[float], dimensions: int) -> tuple[float, ...]:
    """Check a vector received from elsewhere: size, finite values, unit norm.

    Raises:
        EmbedderUnavailableError: The vector is malformed.
    """
    if len(vector) != dimensions or not all(
        isinstance(value, float | int) and math.isfinite(value) for value in vector
    ):
        raise EmbedderUnavailableError("the embedder returned a malformed vector")
    norm: float = math.sqrt(sum(float(value) ** 2 for value in vector))
    if abs(norm - 1.0) > NORM_TOLERANCE:
        raise EmbedderUnavailableError("the embedder returned a vector that is not unit length")
    return tuple(float(value) for value in vector)
