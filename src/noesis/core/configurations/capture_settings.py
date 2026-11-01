"""Settings for capturing work from agent sessions."""

from pydantic import Field
from pydantic_settings import SettingsConfigDict

from .base_settings import AppBaseSettings


class CaptureSettings(AppBaseSettings):
    """Capture thresholds.

    Attributes:
        min_files: Files a change must touch to count as significant (`NOESIS_CAPTURE_MIN_FILES`).
        min_lines: Changed lines that also make it significant (`NOESIS_CAPTURE_MIN_LINES`).
        debounce_seconds: Minimum seconds between two hand-overs (`NOESIS_CAPTURE_DEBOUNCE_SECONDS`).
        trace: Journal every hook invocation, including the silent ones (`NOESIS_CAPTURE_TRACE`).
    """

    model_config = SettingsConfigDict(env_prefix="NOESIS_CAPTURE_")

    min_files: int = Field(default=2, ge=0)
    min_lines: int = Field(default=20, ge=0)
    debounce_seconds: float = Field(default=300.0, ge=0)
    trace: bool = False
