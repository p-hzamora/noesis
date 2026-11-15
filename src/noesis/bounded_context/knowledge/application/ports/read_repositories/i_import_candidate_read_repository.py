"""Read side of the vault import: which records a note already has."""

import abc

from noesis.bounded_context.knowledge.application.dtos import ImportCandidatesDto
from noesis.bounded_context.knowledge.domain.value_objects import RecordId, SpaceId, Tag


class IImportCandidateReadRepository(abc.ABC):
    """Finds the records an import of one note might match."""

    @abc.abstractmethod
    async def find_candidates(
        self, record_id: RecordId | None, locator: str, origin_tag: Tag, *, space_id: SpaceId
    ) -> ImportCandidatesDto:
        """The id holder and the candidates for one note, read in one transaction.

        Args:
            record_id: The id the note declares, when it has one.
            locator: The redacted, stripped file locator.
            origin_tag: The origin tag a record found by locator must carry.
            space_id: The only space searched.

        Returns:
            `id_holder` for `record_id` (`none` without one), and every Knowledge record of the
            space that has that id, or carries `origin_tag` and cites a `file_version` Source
            with `locator`.
        """
        ...
