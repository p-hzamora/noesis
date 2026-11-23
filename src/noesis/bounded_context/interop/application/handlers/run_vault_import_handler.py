"""Apply `import run`: the preview steps, then apply every note that would write."""

from noesis.bounded_context.interop.application.dtos import VaultImportResultDto
from noesis.bounded_context.interop.application.ports import IHeaderParser, IVaultReader
from noesis.bounded_context.interop.application.services import VaultImportPipeline
from noesis.bounded_context.interop.domain.value_objects import ImportActor
from noesis.shared_kernel.application.handlers import IHandler
from noesis.shared_kernel.contracts.ports.interop import IKnowledgeImporter
from noesis.utils import FrozenObject


class RunVaultImportCommand(FrozenObject):
    """Apply a vault import.

    Attributes:
        update: Revise or supersede records whose note changed (`--update`).
        strict: Refuse the run when any note is blocked.
    """

    update: bool = False
    strict: bool = False


class RunVaultImportHandler(IHandler[RunVaultImportCommand, VaultImportResultDto]):
    """Resumable, not atomic: a failure stops the run and earlier notes stay written."""

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

    async def handle(self, action: RunVaultImportCommand) -> VaultImportResultDto:
        """The apply report.

        Raises:
            VaultReadFailedError: The vault or a note cannot be read.
            BlockingFindingsError: `strict` and a note is blocked.
        """
        return await self._pipeline.run(update=action.update, strict=action.strict, apply=True)
