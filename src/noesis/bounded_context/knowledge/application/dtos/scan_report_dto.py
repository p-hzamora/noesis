"""Result of `scan`."""

from noesis.bounded_context.knowledge.application.dtos.scan_runtime_dto import ScanRuntimeDto
from noesis.shared_kernel.application.dtos import BaseDto


class ScanReportDto(BaseDto):
    """Result of `scan`.

    Attributes:
        runtimes: One block per resolved runtime, in the order asked.
        next_steps: The location of each not-installed entry, and `noesis catalog revise` for
            each entry whose installed version drifted.
    """

    runtimes: tuple[ScanRuntimeDto, ...] = ()
    next_steps: tuple[str, ...] = ()
