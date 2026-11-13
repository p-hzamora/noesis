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
from noesis.bounded_context.notes.application.services.manifest import Manifest
from noesis.bounded_context.notes.domain.value_objects import NoteScope, NoteScopeTypeEnum
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


def _prefix(template: str, until: str, **fields: str) -> str:
    return template.split(until, 1)[0].format(**fields)


def _home_group(manifest: Manifest, scope: NoteScope, path: str) -> str | None:
    """The group whose `{root}/repos/<name>/` holds the note: the vault holds no remotes, so
    sitting under a declared group root is what makes a repository a member of that group."""
    for name, group in manifest.groups.items():
        folder: str = _prefix(manifest.layout.grouped_repo, "{name}", root=group.root)
        if path.startswith(f"{folder}{scope.name}/"):
            return name
    return None


def _expected_folder(manifest: Manifest, scope: NoteScope) -> str:
    """The folder (with a trailing slash) the layout puts the notes of `scope` under.

    Outside any group root a repository belongs to a group by its `repos` list only.
    """
    if scope.type is not NoteScopeTypeEnum.REPO:
        return _prefix(manifest.layout.topic, "{kind_folder}", name=scope.name)
    group = next((g for g in manifest.groups.values() if g.matches(scope.name, None)), None)
    if group is None:
        return _prefix(manifest.layout.repo, "{kind_folder}", name=scope.name)
    return _prefix(manifest.layout.grouped_repo, "{kind_folder}", name=scope.name, root=group.root)


def _misplaced(manifest: Manifest, notes: list[tuple[str, NoteScope]]) -> list[str]:
    """Notes outside the folder their scope belongs in.

    A repository with notes under a group root is a member of that group; its notes elsewhere
    are misplaced, and so are its notes under a group root when its `repos` list names another.
    """
    homes: dict[str, str] = {
        scope.name: group
        for path, scope in notes
        if scope.type is NoteScopeTypeEnum.REPO
        if (group := _home_group(manifest, scope, path))
    }
    found: list[str] = []
    for path, scope in notes:
        home: str | None = (
            _home_group(manifest, scope, path) if scope.type is NoteScopeTypeEnum.REPO else None
        )
        if home is not None:
            named = next(
                (n for n, g in manifest.groups.items() if g.matches(scope.name, None)), None
            )
            bad: bool = named is not None and named != home
        else:
            bad = not path.startswith(_expected_folder(manifest, scope)) or (
                scope.type is NoteScopeTypeEnum.REPO and scope.name in homes
            )
        if bad:
            found.append(path)
    return found


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
        group_roots: list[str] = [
            _prefix(manifest.layout.grouped_repo, "{name}", root=g.root).strip("/")
            for g in manifest.groups.values()
        ]
        roots: list[str] = list(
            dict.fromkeys([repo_root, *group_roots, *(root.strip("/") for root in action.roots)])
        )
        valid: int = 0
        without: list[str] = []
        invalid: list[str] = []
        scoped: list[tuple[str, NoteScope]] = []
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
                scoped.append((path, document.frontmatter.scope))
            elif document.malformed_header or BLOCK_KEY in document.header:
                invalid.append(path)
            else:
                without.append(path)
        misplaced: list[str] = _misplaced(manifest, scoped)
        return VaultDiagnosisDto(
            markdown_files=len(markdown),
            with_frontmatter=valid,
            without_frontmatter=len(without),
            invalid_frontmatter=len(invalid),
            duplicate_projects=self._duplicates(files, roots),
            without_paths=tuple(without),
            invalid_paths=tuple(invalid),
            misplaced=len(misplaced),
            misplaced_paths=tuple(misplaced),
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
