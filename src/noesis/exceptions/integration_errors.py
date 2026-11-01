"""Errors raised while integrating noesis with an agent."""

from .base import InfrastructureException, InterfaceException


class AgentSettingsInvalidError(InfrastructureException):
    """The agent's settings file exists but is not a JSON object."""

    __error_code__ = "INTEGRATION_101_AGENT_SETTINGS_INVALID"


class SkillGuideNotFoundError(InterfaceException):
    """No packaged skill guide has the requested name."""

    __error_code__ = "INTEGRATION_001_SKILL_GUIDE_NOT_FOUND"


class ObsidianMcpError(InfrastructureException):
    """The Obsidian MCP server is unreachable, rejected the call, or answered something unusable."""

    __error_code__ = "INTEGRATION_102_OBSIDIAN_MCP_FAILED"
