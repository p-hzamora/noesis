"""Curator adapters: the LLM that judges what is worth keeping."""

from .claude_cli_curator_adapter import ClaudeCliCuratorAdapter, default_system_prompt

__all__ = ["ClaudeCliCuratorAdapter", "default_system_prompt"]
