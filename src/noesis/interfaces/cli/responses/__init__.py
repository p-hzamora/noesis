"""What every `noesis` command prints: the wire contract of the CLI.

The CLI is a delivery adapter, like an HTTP API. Its output contract lives here and is
independent of the application DTOs, so a DTO can change without silently changing what
scripts and agents read. A response is built from a DTO (`XResponse.model_validate(dto)`),
never from an entity or value object, and a command never prints a DTO directly.

Envelope, on stdout with `--json`:
    success: `SuccessResponse` -> `{"ok": true, "result": <a command response>}`
    failure: `ErrorResponse`   -> `{"ok": false, "error": {...}}`
"""

from .capture_run_response import CaptureRunListResponse, CaptureRunResponse
from .capture_status_response import CaptureStatusResponse
from .config_init_response import ConfigInitResponse
from .config_show_response import ConfigShowResponse
from .curation_response import CurationResponse, SkippedCandidateResponse
from .doctor_response import DoctorCheckResponse, DoctorResponse
from .error_response import ErrorDetail, ErrorResponse
from .integration_response import IntegrationResponse
from .note_response import NoteListResponse, NoteResponse, NoteSearchFallbackResponse
from .parked_curation_response import ParkedCurationListResponse, ParkedCurationResponse
from .skill_guide_response import SkillGuideListResponse, SkillGuideResponse
from .success_response import SuccessResponse

__all__ = [
    "CaptureRunListResponse",
    "CaptureRunResponse",
    "CaptureStatusResponse",
    "ConfigInitResponse",
    "ConfigShowResponse",
    "CurationResponse",
    "DoctorCheckResponse",
    "DoctorResponse",
    "ErrorDetail",
    "ErrorResponse",
    "IntegrationResponse",
    "NoteListResponse",
    "NoteSearchFallbackResponse",
    "NoteResponse",
    "ParkedCurationListResponse",
    "ParkedCurationResponse",
    "SkillGuideListResponse",
    "SkillGuideResponse",
    "SkippedCandidateResponse",
    "SuccessResponse",
]
