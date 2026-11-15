"""Preview `import run`: read, map and assess every note; write nothing."""

from noesis.bounded_context.interop.application.dtos import VaultImportResultDto
from noesis.bounded_context.interop.application.ports import (
    IHeaderParser,
    IKnowledgeImporter,
    IVaultReader,
)
from noesis.bounded_context.interop.application.services import VaultImportPipeline
from noesis.bounded_context.interop.domain.value_objects import ImportActor
from noesis.shared_kernel.application.handlers import IHandler
from noesis.utils import FrozenObject


class PlanVaultImportQuery(FrozenObject):
    """Preview of a vault import.

    Attributes:
        update: Whether `--update` was given (decides what Knowledge assesses).
        strict: Refuse the run when any note is blocked.
    """

    update: bool = False
    strict: bool = False


class PlanVaultImportHandler(IHandler[PlanVaultImportQuery, VaultImportResultDto]):
    """Steps 2..6 of the ingestion sequence, assessing only."""

    def __init__(
        self,
        *,
        vault: IVaultReader,
        header_parser: IHeaderParser,
        importer: IKnowledgeImporter,
        vault_key: str,
        space_key: str,
        actor: ImportActor,
    ) -> None:
        self._pipeline: VaultImportPipeline = VaultImportPipeline(
            vault=vault,
            header_parser=header_parser,
            importer=importer,
            vault_key=vault_key,
            space_key=space_key,
            actor=actor,
        )

    async def handle(self, action: PlanVaultImportQuery) -> VaultImportResultDto:
        """The preview report.

        Raises:
            VaultReadFailedError: The vault or a note cannot be read.
            BlockingFindingsError: `strict` and a note is blocked.
        """
        return await self._pipeline.run(update=action.update, strict=action.strict, apply=False)
