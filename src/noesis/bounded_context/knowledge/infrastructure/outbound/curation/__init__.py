"""Curator adapters: the LLM that judges what is worth keeping."""

from .claude_cli_curator_adapter import ClaudeCliCuratorAdapter

__all__ = ["ClaudeCliCuratorAdapter"]
