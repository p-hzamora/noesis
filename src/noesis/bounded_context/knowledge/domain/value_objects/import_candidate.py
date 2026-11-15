"""A record an import might match, as the decision policy reads it."""

from datetime import datetime
from enum import StrEnum

from pydantic import Field

from noesis.bounded_context.knowledge.domain.value_objects.content_hash import ContentHash
from noesis.bounded_context.knowledge.domain.value_objects.enums import RecordStatusEnum
from noesis.bounded_context.knowledge.domain.value_objects.record_id import RecordId
from noesis.bounded_context.knowledge.domain.value_objects.revision import GraphContent
from noesis.shared_kernel.domain.value_objects import ValueObject


class IdHolderEnum(StrEnum):
    """What holds a record id an import was given, in the active space.

    NONE: nothing does.
    GRAPH_KNOWLEDGE: graph-owned Knowledge does, so the import may revise or match it.
    OTHER: any other record type, or file-owned Knowledge, does.
    """

    NONE = "none"
    GRAPH_KNOWLEDGE = "graph_knowledge"
    OTHER = "other"


class ImportOnChangeEnum(StrEnum):
    """What an import does with a note whose content differs from the record's.

    REPORT: nothing; the change is reported.
    UPDATE: revise the record, or propose a successor when it is accepted.
    """

    REPORT = "report"
    UPDATE = "update"


class ImportCandidate(ValueObject):
    """A Knowledge record that has the note's id or cites the note's file locator.

    Attributes:
        id: Record id.
        status: Review state.
        created_at: When the record was created.
        head_revision: Number of the head revision.
        head_content: Title and text of the head, or None when the head is file-owned.
        head_file_digests: Digests of every `file_version` Source the head revision cites.
        holds_record_id: True when the candidate matched by the id the note declares.
    """

    id: RecordId
    status: RecordStatusEnum
    created_at: datetime
    head_revision: int = Field(ge=1)
    head_content: GraphContent | None = None
    head_file_digests: tuple[ContentHash, ...] = ()
    holds_record_id: bool = False
