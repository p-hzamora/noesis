"""What Capture needs from an agent transcript."""

from noesis.shared_kernel.application.dtos import BaseDto


class TranscriptSnapshotDto(BaseDto):
    """The transcript read up to its current end.

    Attributes:
        end_offset: Size of the transcript; the next cursor position.
        has_real_work: Whether files were edited or a commit was made after the cursor.
        goal: The session's first real prompt.
        excerpt: User prompts and assistant prose after the cursor (no tool output).
    """

    end_offset: int
    has_real_work: bool
    goal: str
    excerpt: str
