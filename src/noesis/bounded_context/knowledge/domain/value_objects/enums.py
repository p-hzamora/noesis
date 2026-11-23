"""Closed vocabularies of the Knowledge domain."""

from enum import StrEnum


class OwnershipEnum(StrEnum):
    """Who owns a Knowledge record's text.

    FILE: a file does; the record keeps only its hash, version Source and title.
    GRAPH: the store does; revisions carry the text.
    """

    FILE = "file"
    GRAPH = "graph"


class RecordStatusEnum(StrEnum):
    """Review state of Knowledge or an Assertion; `PROPOSED` at creation."""

    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    SUPERSEDED = "superseded"
    RETRACTED = "retracted"


class SourceKindEnum(StrEnum):
    """What a Source points at."""

    FILE_VERSION = "file_version"
    COMMIT = "commit"
    AGENT_SESSION = "agent_session"
    URL = "url"
    WORK_BRIEF = "work_brief"
    MANIFEST = "manifest"


class ExperienceSubtypeEnum(StrEnum):
    """What an Experience records."""

    OBSERVATION = "observation"
    OUTCOME = "outcome"
    FAILURE = "failure"


class AssertionPredicateEnum(StrEnum):
    """How an Assertion relates its subject to its object."""

    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    SUPERSEDES = "supersedes"
    RECOMMENDS = "recommends"
    REFINES = "refines"


class RecordRelationEnum(StrEnum):
    """How one record relates to another in an imported link set (vault vocabulary)."""

    REFINES = "refines"
    PART_OF = "part_of"
    CONTAINS = "contains"
    IMPLEMENTS = "implements"
    CONSUMES = "consumes"
    EXTENDS = "extends"
    CONTRADICTS = "contradicts"
    SUPERSEDES = "supersedes"


class CatalogEntryKindEnum(StrEnum):
    """What a catalog entry describes (D-029)."""

    SKILL = "skill"
    AGENT = "agent"
    CLI_TOOL = "cli_tool"
    MCP_SERVER = "mcp_server"


class CatalogOriginEnum(StrEnum):
    """How a catalog revision came to be: stated by a caller or found by `catalog sync`."""

    REGISTERED = "registered"
    DISCOVERED = "discovered"


class ActorKindEnum(StrEnum):
    """Who acted: a person or an agent."""

    USER = "user"
    AGENT = "agent"


class RecordTypeEnum(StrEnum):
    """The type of a persisted record."""

    KNOWLEDGE = "knowledge"
    EXPERIENCE = "experience"
    ASSERTION = "assertion"
    SOURCE = "source"
    PROJECT = "project"
    CATALOG_ENTRY = "catalog_entry"


class AuthorityLabelEnum(StrEnum):
    """How much a consumer may trust a record as guidance (decided in the domain)."""

    AUTHORITATIVE = "authoritative"
    PROPOSED = "proposed"
    SUPERSEDED = "superseded"
    RETRACTED = "retracted"
    NOT_REVIEWABLE = "not_reviewable"


class DecisionBasisEnum(StrEnum):
    """Why a review decision was taken."""

    USER = "user"
    AGENT_PROJECT = "agent_project"
    SUPERSESSION_EFFECT = "supersession_effect"
    MIGRATION = "migration"


class ReviewTransitionEnum(StrEnum):
    """A step of the review lifecycle."""

    ACCEPT = "accept"
    REJECT = "reject"
    RETRACT = "retract"
    SUPERSEDE = "supersede"


class ReviewRequirementEnum(StrEnum):
    """Who must decide a queued item."""

    USER = "user"
    AGENT_OR_USER = "agent_or_user"


class AssertionRoleEnum(StrEnum):
    """The part a record plays in an assertion."""

    SUBJECT = "subject"
    OBJECT = "object"
    EVIDENCE = "evidence"
    ANY = "any"


class ConsolidationKindEnum(StrEnum):
    """What a consolidation does; `graph_merge` is the only kind (a successor, never a file merge)."""

    GRAPH_MERGE = "graph_merge"


class ConsolidationStateEnum(StrEnum):
    """Where a consolidation is: `acceptance_started` and `dismissed` are terminal."""

    OPENED = "opened"
    MATERIALISED = "materialised"
    ACCEPTANCE_STARTED = "acceptance_started"
    DISMISSED = "dismissed"


class DismissalReasonKindEnum(StrEnum):
    """Why a consolidation was dismissed; only `distinct` remembers the judged pairs."""

    DISTINCT = "distinct"
    POOR_DRAFT = "poor_draft"
    OTHER = "other"


class ConsolidationProgressEnum(StrEnum):
    """How far the review of a consolidation's proposals got, derived from review state."""

    PENDING = "pending"
    PARTIALLY_APPLIED = "partially_applied"
    APPLIED = "applied"
    SUCCESSOR_RETRACTED = "successor_retracted"
