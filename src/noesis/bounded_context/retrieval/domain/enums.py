"""Closed vocabularies of retrieval."""

from enum import StrEnum


class AuthorityTierEnum(StrEnum):
    """How much a hit can be trusted; the order is `AuthorityRankingPolicy.order_key`."""

    AUTHORITATIVE = "authoritative"
    EXPERIENCE = "experience"
    PROPOSED = "proposed"
    UNREVIEWED = "unreviewed"
    SUPERSEDED = "superseded"
    RETRACTED = "retracted"


class SemanticStateEnum(StrEnum):
    """What the semantic candidate source contributed to one answer."""

    ABSENT = "absent"
    READY = "ready"
    LAGGING = "lagging"
    UNAVAILABLE = "unavailable"


class CandidateKindEnum(StrEnum):
    """The sources a hit can come from, in the order a hit lists them."""

    LEXICAL = "lexical"
    GRAPH = "graph"
    SEMANTIC = "semantic"


class ProjectScopeEnum(StrEnum):
    """Which records a search may return with respect to projects."""

    PROJECT = "project"
    ALL_PROJECTS = "all_projects"
    SPACE_WIDE_ONLY = "space_wide_only"


class BuildStateEnum(StrEnum):
    """Whether a projection's last build of a space finished."""

    REBUILDING = "rebuilding"
    COMPLETE = "complete"


class SemanticModeEnum(StrEnum):
    """How the semantic source runs (`NOESIS_RETRIEVAL_SEMANTIC_MODE`)."""

    RESIDENT = "resident"
    PER_CALL = "per-call"
    OFF = "off"
