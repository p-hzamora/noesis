"""A half-open range of content tokens embedded as one chunk."""

from noesis.shared_kernel.domain.value_objects import ValueObject


class TokenWindow(ValueObject):
    """Content tokens `[start, end)` of one text; special tokens are not counted.

    Attributes:
        index: Position of the window in the text, from 0.
        start: First token.
        end: One past the last token.
    """

    index: int
    start: int
    end: int

    @property
    def size(self) -> int:
        """Number of content tokens."""
        return self.end - self.start
