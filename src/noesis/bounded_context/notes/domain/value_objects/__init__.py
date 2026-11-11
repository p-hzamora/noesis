"""Notes value objects."""

from .curation_decision import CurationActionEnum, CurationDecision, NoteDraft
from .note_frontmatter import NoteFrontmatter
from .note_id import NoteId
from .note_kind import NoteKind
from .note_origin_enum import NoteOriginEnum
from .note_path import NotePath
from .note_placement import NotePlacement
from .note_scope import NoteScope
from .note_scope_type_enum import NoteScopeTypeEnum
from .note_section import NoteSection
from .note_slug import NoteSlug
from .note_source_ref import NoteSourceRef
from .recall_candidate import RecallCandidate
from .recall_weights import RecallWeights
from .work_brief import CommitRef, WorkBrief

__all__ = [
    "CommitRef",
    "CurationActionEnum",
    "CurationDecision",
    "NoteDraft",
    "NoteFrontmatter",
    "NoteId",
    "NoteKind",
    "NoteOriginEnum",
    "NotePath",
    "NotePlacement",
    "NoteScope",
    "NoteScopeTypeEnum",
    "NoteSection",
    "NoteSlug",
    "NoteSourceRef",
    "RecallCandidate",
    "RecallWeights",
    "WorkBrief",
]
