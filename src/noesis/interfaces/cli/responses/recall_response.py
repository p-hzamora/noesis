"""Public evidence metadata of a briefing, without internal search machinery."""

from noesis.bounded_context.retrieval.application.dtos.briefing_dtos import EvidenceDto


class RecallRecordResponse(EvidenceDto):
    """Public evidence metadata; body is presented only through grounded sections."""

    body: None = None
