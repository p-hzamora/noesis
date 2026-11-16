"""Strict reader of the payload `noesis curate apply` accepts.

It reads the curator's entry shape but never downgrades a flawed entry to a skip: every flaw is
reported with its position, so the caller can fix the input, and any flaw fails the whole call
before anything is staged or written.
"""

import json

from noesis.bounded_context.knowledge.application.dtos import RejectedEntryDto
from noesis.bounded_context.knowledge.domain.services import CurationAdmissionPolicy
from noesis.bounded_context.knowledge.domain.value_objects import CurationCandidate
from noesis.utils import FrozenObject

from .candidate_answer_schema import CANDIDATES_KEY, read_entry_strictly


class ParsedApplyPayload(FrozenObject):
    """What an apply payload held.

    Attributes:
        candidates: The entries that are valid, in order (every entry, when none is rejected).
        rejected: The entries that are not, with their position and reason.
    """

    candidates: tuple[CurationCandidate, ...] = ()
    rejected: tuple[RejectedEntryDto, ...] = ()


def parse_apply_payload(text: str) -> ParsedApplyPayload:
    """Read an apply payload.

    Args:
        text: The JSON exactly as the caller sent it.

    Returns:
        The valid candidates and the rejected entries. A payload that is not JSON, or not an
        object with a single `candidates` list, gives one rejection without an index.
    """
    try:
        payload: object = json.loads(text)
    except json.JSONDecodeError as error:
        return ParsedApplyPayload(
            rejected=(RejectedEntryDto(index=None, reason=f"not valid JSON: {error.msg}"),)
        )
    if (
        not isinstance(payload, dict)
        or set(payload) != {CANDIDATES_KEY}
        or not isinstance(payload[CANDIDATES_KEY], list)
    ):
        return ParsedApplyPayload(
            rejected=(
                RejectedEntryDto(
                    index=None,
                    reason=f'expected an object with a single "{CANDIDATES_KEY}" list',
                ),
            )
        )
    entries: list[object] = payload[CANDIDATES_KEY]
    reasons: dict[int, str] = {}
    candidates: list[CurationCandidate] = []
    for index, entry in enumerate(entries):
        outcome: CurationCandidate | str = read_entry_strictly(entry)
        if isinstance(outcome, str):
            reasons[index] = outcome
            candidates.append(CurationCandidate(flaw=outcome))
        else:
            candidates.append(outcome)
    for index, reason in CurationAdmissionPolicy.flaws(candidates).items():
        reasons.setdefault(index, reason)
    if reasons:
        return ParsedApplyPayload(
            rejected=tuple(
                RejectedEntryDto(index=index, reason=reason)
                for index, reason in sorted(reasons.items())
            )
        )
    return ParsedApplyPayload(candidates=tuple(candidates))
