"""What the rerun lookup finds for one note."""

from datetime import datetime

from noesis.shared_kernel.application.dtos import BaseDto


class ImportCandidateDto(BaseDto):
    """A Knowledge record that has the note's id or cites the note's file locator.

    Attributes:
        id: Record id.
        status: Review state.
        created_at: When the record was created.
        head_revision: Number of the head revision.
        title: Title of the head revision.
        body: Text of the head revision; None when the head is file-owned.
        head_file_digests: Digests of every `file_version` Source the head revision cites.
    """

    id: str
    status: str
    created_at: datetime
    head_revision: int
    title: str
    body: str | None = None
    head_file_digests: tuple[str, ...] = ()


class ImportCandidatesDto(BaseDto):
    """Everything the decision for one note needs from the store.

    Attributes:
        id_holder: For a given record id: `none`, `graph_knowledge` or `other`.
        candidates: The matching Knowledge records of the space.
    """

    id_holder: str
    candidates: tuple[ImportCandidateDto, ...] = ()
