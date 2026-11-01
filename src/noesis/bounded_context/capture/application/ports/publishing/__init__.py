"""Work-brief publishing ports."""

from noesis.bounded_context.capture.application.ports.publishing.i_work_brief_publisher import (
    IWorkBriefPublisher,
)
from noesis.bounded_context.capture.application.ports.publishing.i_work_brief_publisher_factory import (
    IWorkBriefPublisherFactory,
)

__all__ = ["IWorkBriefPublisher", "IWorkBriefPublisherFactory"]
