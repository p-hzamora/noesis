"""What every `noesis` command prints: the wire contract of the CLI.

The CLI is a delivery adapter, like an HTTP API. Its output contract lives here and is
independent of the application DTOs, so a DTO can change without silently changing what
scripts and agents read. A response is built from a DTO (`XResponse.model_validate(dto)`),
never from an entity or value object, and a command never prints a DTO directly.
Every printable response extends `IRenderableResponse`: `render()` is its text form.

Envelope, on stdout with `--json`:
    success: `SuccessResponse` -> `{"ok": true, "result": <a command response>}`
    failure: `ErrorResponse`   -> `{"ok": false, "error": {...}}`
"""

from .assertion_response import (
    AssertionApplicabilityResponse,
    AssertionEndpointResponse,
    AssertionItemResponse,
    AssertionListResponse,
    AssertionProposeResponse,
)
from .capture_run_response import CaptureRunListResponse, CaptureRunResponse
from .capture_status_response import CaptureStatusResponse
from .catalog_response import (
    AvailabilitySummaryResponse,
    CatalogCheckResponse,
    CatalogEntryResponse,
    CatalogListResponse,
    CatalogScanResponse,
    CatalogShowResponse,
    CatalogWriteResponse,
    CheckRuntimeResponse,
    NotInstalledResponse,
    ObservationResponse,
    ScanRuntimeResponse,
    UncatalogedResponse,
    UnreadableKindResponse,
    VersionDriftResponse,
)
from .config_init_response import ConfigInitResponse
from .config_show_response import ConfigShowResponse
from .consolidation_response import (
    ConsolidationDecisionResponse,
    ConsolidationDismissalResponse,
    ConsolidationItemResponse,
    ConsolidationListResponse,
    ConsolidationMemberResponse,
    ConsolidationProducedResponse,
    ConsolidationProposeResponse,
    ConsolidationScanResponse,
    ConsolidationShowResponse,
    ConsolidationStepResponse,
    PlannedAssertionResponse,
    ScanCandidateResponse,
    ScanConflictResponse,
    ScanGroupResponse,
)
from .curate_response import (
    CurateParkedItemResponse,
    CurateParkedResponse,
    CurateResponse,
    CurateRetryAllResponse,
    CurationItemResponse,
    CurationSourceResponse,
    RelatedLookupResponse,
    RetryTicketResponse,
)
from .doctor_response import DoctorCheckResponse, DoctorResponse
from .error_response import ErrorDetail, ErrorResponse
from .i_renderable_response import IRenderableResponse
from .import_file_response import ImportFileResponse
from .import_run_response import (
    ImportNoteRowResponse,
    ImportRunResponse,
    ImportTotalsResponse,
    ImportWarningCountsResponse,
)
from .index_response import (
    EmbedderServeResponse,
    IndexDivergenceResponse,
    IndexProjectionStatusResponse,
    IndexRebuildResponse,
    IndexRebuiltProjectionResponse,
    IndexStatusResponse,
    IndexSyncedProjectionResponse,
    IndexSyncResponse,
    ModelPrepareResponse,
)
from .integration_response import (
    IntegrationBaseResponse,
    IntegrationResponse,
    IntegrationStatusResponse,
)
from .record_response import (
    RecordActorResponse,
    RecordApplicabilityResponse,
    RecordCaptureResponse,
    RecordEndpointResponse,
    RecordResponse,
    RecordReviseResponse,
    RecordRevisionResponse,
    RecordSourceResponse,
    RecordSupersededByResponse,
    StoreInitResponse,
    StoreSpaceResponse,
)
from .review_response import (
    ReviewAcceptResponse,
    ReviewBulkAcceptResponse,
    ReviewLogResponse,
    ReviewQueueResponse,
    ReviewRepairResponse,
    ReviewRetractResponse,
)
from .search_response import (
    SearchHitResponse,
    SearchIndexResponse,
    SearchResponse,
    SearchScopeResponse,
    SearchSemanticResponse,
)
from .skill_guide_response import SkillGuideListResponse, SkillGuideResponse
from .success_response import SuccessResponse
from .update_check_response import UpdateCheckResponse

__all__ = [
    "ConsolidationDecisionResponse",
    "ConsolidationDismissalResponse",
    "ConsolidationItemResponse",
    "ConsolidationListResponse",
    "ConsolidationMemberResponse",
    "ConsolidationProducedResponse",
    "ConsolidationProposeResponse",
    "ConsolidationScanResponse",
    "ConsolidationShowResponse",
    "ConsolidationStepResponse",
    "PlannedAssertionResponse",
    "ScanCandidateResponse",
    "ScanConflictResponse",
    "ScanGroupResponse",
    "CurateParkedItemResponse",
    "CurateParkedResponse",
    "CurateResponse",
    "CurateRetryAllResponse",
    "CurationItemResponse",
    "CurationSourceResponse",
    "RelatedLookupResponse",
    "RetryTicketResponse",
    "AssertionApplicabilityResponse",
    "AssertionEndpointResponse",
    "AssertionItemResponse",
    "AssertionListResponse",
    "AssertionProposeResponse",
    "IndexDivergenceResponse",
    "IndexProjectionStatusResponse",
    "IndexRebuildResponse",
    "IndexRebuiltProjectionResponse",
    "IndexStatusResponse",
    "IndexSyncResponse",
    "ModelPrepareResponse",
    "EmbedderServeResponse",
    "IndexSyncedProjectionResponse",
    "ReviewAcceptResponse",
    "ReviewBulkAcceptResponse",
    "ReviewLogResponse",
    "ReviewQueueResponse",
    "ReviewRepairResponse",
    "ReviewRetractResponse",
    "SearchHitResponse",
    "SearchIndexResponse",
    "SearchResponse",
    "SearchScopeResponse",
    "SearchSemanticResponse",
    "AvailabilitySummaryResponse",
    "CatalogCheckResponse",
    "CatalogEntryResponse",
    "CatalogListResponse",
    "CatalogScanResponse",
    "CatalogShowResponse",
    "CatalogWriteResponse",
    "CheckRuntimeResponse",
    "NotInstalledResponse",
    "ObservationResponse",
    "ScanRuntimeResponse",
    "UncatalogedResponse",
    "UnreadableKindResponse",
    "VersionDriftResponse",
    "CaptureRunListResponse",
    "CaptureRunResponse",
    "CaptureStatusResponse",
    "ConfigInitResponse",
    "ConfigShowResponse",
    "DoctorCheckResponse",
    "DoctorResponse",
    "ErrorDetail",
    "ErrorResponse",
    "ImportFileResponse",
    "ImportNoteRowResponse",
    "ImportRunResponse",
    "ImportTotalsResponse",
    "ImportWarningCountsResponse",
    "IntegrationBaseResponse",
    "IntegrationResponse",
    "IntegrationStatusResponse",
    "IRenderableResponse",
    "RecordActorResponse",
    "RecordApplicabilityResponse",
    "RecordCaptureResponse",
    "RecordEndpointResponse",
    "RecordResponse",
    "RecordReviseResponse",
    "RecordRevisionResponse",
    "RecordSourceResponse",
    "RecordSupersededByResponse",
    "StoreInitResponse",
    "StoreSpaceResponse",
    "SkillGuideListResponse",
    "SkillGuideResponse",
    "SuccessResponse",
    "UpdateCheckResponse",
]
