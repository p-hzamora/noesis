"""Count the vault's notes by frontmatter state and find projects kept under two roots."""

from collections import defaultdict

from noesis.bounded_context.notes.application.dtos import (
    DuplicateProjectDto,
    ParsedDocumentDto,
    VaultDiagnosisDto,
)
from noesis.bounded_context.notes.application.ports.frontmatter import IFrontmatterCodec
from noesis.bounded_context.notes.application.ports.manifest import IManifestProvider
from noesis.bounded_context.notes.application.ports.vault import IVaultFiles
from noesis.shared_kernel.application.handlers import IHandler
from noesis.utils import FrozenObject

NOTE_SUFFIX: str = ".md"
BLOCK_KEY: str = "noesis"


class DiagnoseVaultQuery(FrozenObject):
    """Diagnose the vault.

    Attributes:
        roots: Folders whose subfolders are projects, besides the manifest's repository folder.
    """

    roots: tuple[str, ...] = ()


class DiagnoseVaultHandler(IHandler[DiagnoseVaultQuery, VaultDiagnosisDto]):
    """Read-only: never changes a file."""

    def __init__(
        self, *, vault: IVaultFiles, manifests: IManifestProvider, codec: IFrontmatterCodec
    ) -> None:
        self._vault: IVaultFiles = vault
        self._manifests: IManifestProvider = manifests
        self._codec: IFrontmatterCodec = codec

    async def handle(self, action: DiagnoseVaultQuery) -> VaultDiagnosisDto:
        """The counts and the duplicate project names."""
        files: list[str] = await self._vault.list_files()
        manifest = await self._manifests.load()
        repo_root: str = manifest.layout.repo.split("{name}", 1)[0].strip("/")
        roots: list[str] = list(
            dict.fromkeys([repo_root, *(root.strip("/") for root in action.roots)])
        )
        valid: int = 0
        without: list[str] = []
        invalid: list[str] = []
        markdown: list[str] = [
            path
            for path in files
            if path.endswith(NOTE_SUFFIX) and not any(p.startswith(".") for p in path.split("/"))
        ]
        for path in markdown:
            try:
                text: str = (await self._vault.read(path)).decode("utf-8")
            except UnicodeDecodeError:
                invalid.append(path)
                continue
            document: ParsedDocumentDto = self._codec.parse(text)
            if document.frontmatter is not None:
                valid += 1
            elif document.malformed_header or BLOCK_KEY in document.header:
                invalid.append(path)
            else:
                without.append(path)
        return VaultDiagnosisDto(
            markdown_files=len(markdown),
            with_frontmatter=valid,
            without_frontmatter=len(without),
            invalid_frontmatter=len(invalid),
            duplicate_projects=self._duplicates(files, roots),
            without_paths=tuple(without),
            invalid_paths=tuple(invalid),
        )

    @staticmethod
    def _duplicates(files: list[str], roots: list[str]) -> tuple[DuplicateProjectDto, ...]:
        found: dict[str, set[str]] = defaultdict(set)
        for root in roots:
            for path in files:
                relative: list[str] = path.removeprefix(f"{root}/").split("/")
                if path.startswith(f"{root}/") and len(relative) > 1:
                    found[relative[0]].add(root)
        return tuple(
            DuplicateProjectDto(name=name, roots=tuple(sorted(where)))
            for name, where in sorted(found.items())
            if len(where) > 1
        )
