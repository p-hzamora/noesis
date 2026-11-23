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


class RequirementSourceEnum(StrEnum):
    """Where a requirement facet came from."""

    NEED = "need"
    QUERY = "query"


class CoverageStatusEnum(StrEnum):
    """How well the selected resources and records answer one requirement facet."""

    COVERED = "covered"
    PARTIAL = "partial"
    MISSING = "missing"
    UNKNOWN = "unknown"


class EndorsementEnum(StrEnum):
    """Who stands behind a resource; derived from `recommends` assertions only."""

    USER = "user"
    PROJECT = "project"
    PROPOSED = "proposed"
    NONE = "none"


class DecisionBasisEnum(StrEnum):
    """Who decided an assertion's status."""

    USER = "user"
    AGENT = "agent"


class SupportKindEnum(StrEnum):
    """What backs a requirement facet."""

    RESOURCE = "resource"
    RECORD = "record"


class BriefingModeEnum(StrEnum):
    """What briefing `search` adds to the answer."""

    NONE = "none"
    DIGEST = "digest"
    SYNTHESIS = "synthesis"


class SearchableRecordTypeEnum(StrEnum):
    """The record types a record search returns."""

    KNOWLEDGE = "knowledge"
    EXPERIENCE = "experience"


class NextActionEnum(StrEnum):
    """The closed set of things `search` tells the caller to do next; never free text."""

    LOAD_SKILL = "load_skill"
    USE_AGENT = "use_agent"
    USE_CLI_TOOL = "use_cli_tool"
    USE_MCP_SERVER = "use_mcp_server"
    READ_RECORD = "read_record"
