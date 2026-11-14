"""Errors raised while integrating noesis with an agent."""

from .base import InfrastructureException, InterfaceException


class AgentSettingsInvalidError(InfrastructureException):
    """The agent's settings file exists but is not a JSON object."""

    __error_code__ = "INTEGRATION_101_AGENT_SETTINGS_INVALID"


class SkillGuideNotFoundError(InterfaceException):
    """No packaged skill guide has the requested name."""

    __error_code__ = "INTEGRATION_001_SKILL_GUIDE_NOT_FOUND"


# INTEGRATION_102 was the Obsidian MCP failure. The backends were removed (C2, D-018); the code
# stays reserved and must never be reused.


class GraphStoreUnavailableError(InfrastructureException):
    """Neo4j cannot be reached, or the connection was lost mid-work (fail closed, D-014).

    Metadata: `uri` (no credentials), `database`, `connect_timeout_seconds`, `phase`
    (`connect`, `query` or `commit`) and, when lost during commit, `commit_outcome: unknown`.
    """

    __error_code__ = "INTEGRATION_103_GRAPH_STORE_UNAVAILABLE"


class GraphStoreAuthenticationFailedError(InfrastructureException):
    """Neo4j was reached but rejected the configured user or password."""

    __error_code__ = "INTEGRATION_104_GRAPH_STORE_AUTHENTICATION_FAILED"


class GraphStoreBusyError(InfrastructureException):
    """Neo4j refused the work for a transient reason (lock timeout, deadlock); retrying is safe."""

    __error_code__ = "INTEGRATION_105_GRAPH_STORE_BUSY"


class GraphStoreConstraintViolatedError(InfrastructureException):
    """A write broke a uniqueness constraint.

    Persistence adapters catch it to resolve races (optimistic concurrency, idempotency) and
    raise their own context's error; it reaches a caller only if an adapter forgot to.
    Metadata: `label` and `property` when Neo4j names them.
    """

    __error_code__ = "INTEGRATION_106_GRAPH_STORE_CONSTRAINT_VIOLATED"


class GraphStoreQueryFailedError(InfrastructureException):
    """Neo4j rejected a statement for a reason that is a defect, not an outage (bad Cypher, wrong type)."""

    __error_code__ = "INTEGRATION_107_GRAPH_STORE_QUERY_FAILED"
