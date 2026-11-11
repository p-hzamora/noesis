"""One hit of a vector index."""

from pydantic import Field

from noesis.shared_kernel.application.dtos import BaseDto


class VectorHitDto(BaseDto):
    """A ranked answer of a vector index, with no vendor detail.

    Attributes:
        id: Id of the note, as written in its frontmatter.
        path: Path of the note in the indexed source.
        rank: Position in the answer, 0 is the best match.
    """

    id: str
    path: str
    rank: int = Field(ge=0)
