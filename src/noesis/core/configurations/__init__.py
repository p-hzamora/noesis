"""Typed settings, one class per concern, all sharing `AppBaseSettings`'s loading policy.

Only `noesis.core.env` builds them; everything else reads them from there.
"""

from .base_settings import AppBaseSettings
from .capture_settings import CaptureSettings
from .claude_code_settings import ClaudeCodeSettings
from .curator_settings import CuratorSettings
from .notes_settings import NotesSettings
from .paths import default_config_dir, default_env_file, default_state_dir
from .recall_settings import RecallRuntimeEnum, RecallSettings
from .runtime_settings import LogLevelEnum, RuntimeSettings
from .session_identity_settings import SessionIdentitySettings

__all__ = [
    "AppBaseSettings",
    "CaptureSettings",
    "ClaudeCodeSettings",
    "CuratorSettings",
    "NotesSettings",
    "RecallRuntimeEnum",
    "RecallSettings",
    "LogLevelEnum",
    "RuntimeSettings",
    "SessionIdentitySettings",
    "default_config_dir",
    "default_env_file",
    "default_state_dir",
]
