"""The JSON shape of a curator answer and an apply payload, and its translation to candidates.

This is the anti-corruption layer between the model's (or the caller's) JSON and the curation
domain. Both use one entry shape inside the envelope `{"candidates": [...]}` (Q-016). The
curator is read leniently: a flawed entry keeps its position and becomes a policy skip. The apply
payload is read strictly: every flaw is reported with its position.
"""

import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from noesis.bounded_context.knowledge.domain.value_objects import (
    CandidateKindEnum,
    CurationCandidate,
    CurationSubtypes,
)

CANDIDATES_KEY: str = "candidates"
MAX_ECHOED_LENGTH: int = 40


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CandidateEntryModel(_Strict):
    """One candidate: something worth keeping, or a skip with the reason."""

    kind: Literal["experience", "knowledge", "skip"] = Field(
        description="`experience`: something that happened. `knowledge`: guidance worth "
        "keeping. `skip`: a candidate you considered and rejected."
    )
    key: str = Field(description="Short local name, unique in this answer.")
    subtype: str | None = Field(
        default=None, description="Required unless `skip`: one of the listed subtypes."
    )
    title: str | None = Field(default=None, description="Required for `knowledge`.")
    body: str | None = Field(
        default=None,
        description="Required unless `skip`. Short Markdown. Cite commit SHAs (first 8 "
        "characters); never paste diffs.",
    )
    target_record_id: str | None = Field(
        default=None,
        description="`knowledge` only: id of the related record this refines or replaces.",
    )
    evidence_keys: list[str] = Field(
        default_factory=list,
        description="`knowledge` only: keys of `experience` candidates that support it.",
    )
    reason: str | None = Field(
        default=None,
        description="One sentence. Required for `skip`, and whenever a target or evidence is given.",
    )


class CandidateAnswerModel(_Strict):
    """The whole answer. An empty `candidates` list is valid."""

    candidates: list[CandidateEntryModel]


def response_json_schema(subtypes: CurationSubtypes) -> str:
    """The schema passed to `claude --json-schema`, with `subtype` limited to the allowed set."""
    schema: dict[str, Any] = CandidateAnswerModel.model_json_schema()
    subtype: dict[str, Any] = schema["$defs"]["CandidateEntryModel"]["properties"]["subtype"]
    subtype.pop("anyOf", None)
    subtype["enum"] = [*sorted(subtypes.knowledge | subtypes.experience), None]
    return json.dumps(schema)


def read_entry_strictly(entry: object) -> CurationCandidate | str:
    """One entry as a candidate, or the reason it cannot be one (never echoing its values)."""
    if not isinstance(entry, dict):
        return "entry is not an object"
    try:
        model: CandidateEntryModel = CandidateEntryModel.model_validate(entry)
    except ValidationError as error:
        first = error.errors()[0]
        location: str = ".".join(str(part) for part in first["loc"])
        return f"{location}: {first['msg']}" if location else first["msg"]
    candidate: CurationCandidate = _candidate(model)
    return candidate.entry_flaw() or candidate


def read_entry_leniently(entry: object) -> CurationCandidate:
    """One entry as a candidate, whatever it holds; what could not be read becomes `flaw`."""
    if not isinstance(entry, dict):
        return CurationCandidate(flaw="entry is not an object")
    flaws: list[str] = []

    def text(name: str) -> str | None:
        value: object = entry.get(name)
        if value is None:
            return None
        if isinstance(value, str):
            return value
        flaws.append(f"{name} is not text")
        return None

    kind: CandidateKindEnum | None = None
    raw_kind: str | None = text("kind")
    if raw_kind is not None:
        try:
            kind = CandidateKindEnum(raw_kind)
        except ValueError:
            flaws.append(f"unknown kind {raw_kind[:MAX_ECHOED_LENGTH]!r}")
    evidence: object = entry.get("evidence_keys") or []
    keys: tuple[str, ...] = ()
    if isinstance(evidence, list) and all(isinstance(item, str) for item in evidence):
        keys = tuple(evidence)
    else:
        flaws.append("evidence_keys is not a list of text")
    return CurationCandidate(
        kind=kind,
        key=text("key"),
        subtype=text("subtype"),
        title=text("title"),
        body=text("body"),
        target_record_id=text("target_record_id"),
        evidence_keys=keys,
        reason=text("reason"),
        flaw="; ".join(flaws) or None,
    )


def candidates_of_answer(answer: object) -> tuple[CurationCandidate, ...] | None:
    """The candidates of a curator answer, read leniently; None when it is not usable.

    An answer is usable when it is an object with a `candidates` list.
    """
    if not isinstance(answer, dict) or not isinstance(answer.get(CANDIDATES_KEY), list):
        return None
    return tuple(read_entry_leniently(entry) for entry in answer[CANDIDATES_KEY])


def _candidate(model: CandidateEntryModel) -> CurationCandidate:
    return CurationCandidate(
        kind=CandidateKindEnum(model.kind),
        key=model.key,
        subtype=model.subtype,
        title=model.title,
        body=model.body,
        target_record_id=model.target_record_id,
        evidence_keys=tuple(model.evidence_keys),
        reason=model.reason,
    )
