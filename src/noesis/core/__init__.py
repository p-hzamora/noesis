"""Framework-agnostic configuration: typed settings and how the environment is loaded."""

from .env import (
    ClaudeCodeSettings,
    Environment,
    default_state_dir,
    load_claude_code_settings,
    load_environment,
)
from .env_template import env_example_text, write_env_file
from .repo_config import resolve_env_file

__all__ = [
    "ClaudeCodeSettings",
    "Environment",
    "default_state_dir",
    "env_example_text",
    "load_claude_code_settings",
    "load_environment",
    "resolve_env_file",
    "write_env_file",
]
