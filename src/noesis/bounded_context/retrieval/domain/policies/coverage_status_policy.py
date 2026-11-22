"""Coverage status of one requirement facet."""

from collections.abc import Iterable

from ..enums import AuthorityTierEnum, CoverageStatusEnum, SupportKindEnum
from ..value_objects.facet_support import FacetSupport


class CoverageStatusPolicy:
    """`covered`, `partial`, `missing` or `unknown`.

    - `covered`: a usable selected resource, or an authoritative record, matches.
    - `partial`: only proposed records or unavailable resources match.
    - `unknown`: nothing counts yet and the runtime for that kind could not be read.
    - `missing`: nothing matches.
    """

    def status(
        self, support: Iterable[FacetSupport], *, unreadable: bool = False
    ) -> CoverageStatusEnum:
        """Status of a facet given everything that matched it."""
        partial = False
        for item in support:
            if item.kind is SupportKindEnum.RESOURCE:
                if item.available is False:
                    partial = True
                else:
                    return CoverageStatusEnum.COVERED
            elif item.authority is AuthorityTierEnum.AUTHORITATIVE:
                return CoverageStatusEnum.COVERED
            elif item.authority is AuthorityTierEnum.PROPOSED:
                partial = True
        if partial:
            return CoverageStatusEnum.PARTIAL
        return CoverageStatusEnum.UNKNOWN if unreadable else CoverageStatusEnum.MISSING
