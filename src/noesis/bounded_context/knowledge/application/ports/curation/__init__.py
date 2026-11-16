"""Curation ports."""

from .curation_ticket import CurationTicket, StepOutcome, StepOutcomeEnum
from .i_curation_inbox import ICurationInbox
from .i_curator import ICurator
from .i_related_record_finder import IRelatedRecordFinder

__all__ = [
    "CurationTicket",
    "ICurationInbox",
    "ICurator",
    "IRelatedRecordFinder",
    "StepOutcome",
    "StepOutcomeEnum",
]
