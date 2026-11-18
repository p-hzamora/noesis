"""Typed `related` entries and their resolution within one vault scan."""

from dataclasses import dataclass
from typing import Literal

type RelationClass = Literal[
    "resolved",
    "dangling",
    "ambiguous",
    "not_imported",
    "self",
    "unknown_relation",
    "invalid_relation",
]
type TargetClass = Literal["resolved", "dangling", "ambiguous", "invalid_relation"]


@dataclass(frozen=True, slots=True, kw_only=True)
class RawRelation:
    """One well-formed `related` entry: the vault id of the target and a vocabulary word."""

    target_key: str
    relation: str


@dataclass(frozen=True, slots=True, kw_only=True)
class RejectedRelation:
    """A `related` entry that cannot become an edge, named for `--verbose`."""

    classification: Literal["unknown_relation", "invalid_relation"]
    target_key: str
    relation: str


@dataclass(frozen=True, slots=True, kw_only=True)
class RelationResolution:
    """Where a vault relation id points, with sorted candidates when ambiguous."""

    classification: TargetClass
    path: str | None = None
    candidates: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True, kw_only=True)
class ClassifiedRelation:
    """A relation entry with its final class and, when ambiguous, the candidate paths."""

    target_key: str
    relation: str
    classification: RelationClass
    candidates: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True, kw_only=True)
class ImportedRelation:
    """An outgoing typed edge to a target record."""

    target_record_id: str
    relation: str
