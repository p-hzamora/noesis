"""In-memory fakes and builders for the interop (import) handlers.

The fakes hold no lifecycle rule: a test scripts exactly the outcome it needs (`90-verification.md`).
"""

from collections.abc import Callable
from typing import Any

from noesis.bounded_context.interop.application.handlers import (
    ImportFileCommand,
    ImportFileHandler,
    PlanVaultImportHandler,
    PlanVaultImportQuery,
    RunVaultImportCommand,
    RunVaultImportHandler,
)
from noesis.bounded_context.interop.domain.value_objects import ImportActor
from noesis.bounded_context.interop.infrastructure.outbound import YamlHeaderParserAdapter
from noesis.shared_kernel.contracts.knowledge import (
    ImportKnowledgeOutcomeContract,
    ImportKnowledgeRequestContract,
)

MINTED_PREFIX: str = "01JCKMNPM"
ACTOR: ImportActor = ImportActor(kind="user", name="tester", session=None)


def note(body: str = "Body.", header: str | None = None, *, newline: str = "\n") -> bytes:
    """A note's bytes: an optional YAML header between `---` lines, then the body."""
    text: str = f"---\n{header}\n---\n{body}" if header is not None else body
    return text.replace("\n", newline).encode()


def current_header(**noesis: str) -> str:
    """A current-layout header block: `noesis:` with the given keys (`id`, `scope`, `kind`, ...)."""
    lines: list[str] = ["noesis:", *(f"  {key}: {value}" for key, value in noesis.items())]
    return "\n".join(lines)


def outcome(kind: str, **fields: Any) -> ImportKnowledgeOutcomeContract:
    """A scripted outcome contract; every field not given is null (`replayed` false)."""
    values: dict[str, Any] = {
        "outcome": kind,
        "record_id": None,
        "revision": None,
        "status": None,
        "target_record_id": None,
        "assertion_id": None,
        "block_reason": None,
        "reason": None,
        "detail": None,
        "replayed": False,
    }
    values.update(fields)
    return ImportKnowledgeOutcomeContract(**values)


class FakeVaultReader:
    """`IVaultReader` over a dict of relative path -> bytes (the port contract: sorted paths)."""

    def __init__(self, files: dict[str, bytes]) -> None:
        self.files: dict[str, bytes] = dict(files)
        self.reads: list[str] = []

    def list_notes(self) -> list[str]:
        """Relative POSIX paths of every note, sorted by code point."""
        return sorted(self.files)

    def read(self, relative_path: str) -> bytes:
        """The bytes of one note."""
        self.reads.append(relative_path)
        return self.files[relative_path]


class FakeFileReader:
    """`IFileReader` over a dict of absolute path -> bytes; `links` maps a path to its target."""

    def __init__(self, files: dict[str, bytes], links: dict[str, str] | None = None) -> None:
        self.files: dict[str, bytes] = dict(files)
        self.links: dict[str, str] = dict(links or {})

    def resolve(self, path: str) -> str:
        """The absolute path with links resolved."""
        return self.links.get(path, path)

    def read(self, absolute_path: str) -> bytes:
        """The bytes of the resolved file."""
        return self.files[absolute_path]


class FakeKnowledgeImporter:
    """`IKnowledgeImporter` that records every call and answers from scripts.

    Attributes:
        calls: `("assess" | "apply", request)` in call order.
    """

    def __init__(
        self,
        *,
        assess: Callable[[ImportKnowledgeRequestContract], ImportKnowledgeOutcomeContract]
        | None = None,
        apply: Callable[[ImportKnowledgeRequestContract], ImportKnowledgeOutcomeContract]
        | None = None,
    ) -> None:
        self._assess: Callable[[ImportKnowledgeRequestContract], ImportKnowledgeOutcomeContract] = (
            assess or self._default_assess
        )
        self._apply: Callable[[ImportKnowledgeRequestContract], ImportKnowledgeOutcomeContract] = (
            apply or self._default_apply
        )
        self.calls: list[tuple[str, ImportKnowledgeRequestContract]] = []
        self._minted: int = 0

    @staticmethod
    def _default_assess(request: ImportKnowledgeRequestContract) -> ImportKnowledgeOutcomeContract:
        return outcome("created", record_id=request.record_id, revision=1, status="proposed")

    def _default_apply(
        self, request: ImportKnowledgeRequestContract
    ) -> ImportKnowledgeOutcomeContract:
        self._minted += 1
        record_id: str = request.record_id or f"{MINTED_PREFIX}{self._minted:017d}"
        return outcome("created", record_id=record_id, revision=1, status="proposed")

    async def assess(
        self, request: ImportKnowledgeRequestContract
    ) -> ImportKnowledgeOutcomeContract:
        """Record the call and return the scripted outcome."""
        self.calls.append(("assess", request))
        return self._assess(request)

    async def apply(
        self, request: ImportKnowledgeRequestContract
    ) -> ImportKnowledgeOutcomeContract:
        """Record the call and return the scripted outcome (or raise what the script raises)."""
        self.calls.append(("apply", request))
        return self._apply(request)

    def requests(self, kind: str = "assess") -> dict[str, ImportKnowledgeRequestContract]:
        """The requests of one call kind, keyed by `source_locator`."""
        return {request.source_locator: request for call, request in self.calls if call == kind}

    def sequence(self) -> list[tuple[str, str]]:
        """`(kind, source_locator)` in call order."""
        return [(kind, request.source_locator) for kind, request in self.calls]


def _common(vault_key: str) -> dict[str, Any]:
    return {
        "header_parser": YamlHeaderParserAdapter(),
        "space_key": "personal",
        "actor": ACTOR,
    } | ({"vault_key": vault_key} if vault_key else {})


def build_plan(
    vault: FakeVaultReader, importer: FakeKnowledgeImporter, *, vault_key: str = "fixture"
) -> PlanVaultImportHandler:
    """The preview handler over the fakes."""
    return PlanVaultImportHandler(vault=vault, importer=importer, **_common(vault_key))


def build_run(
    vault: FakeVaultReader, importer: FakeKnowledgeImporter, *, vault_key: str = "fixture"
) -> RunVaultImportHandler:
    """The apply handler over the fakes."""
    return RunVaultImportHandler(vault=vault, importer=importer, **_common(vault_key))


def build_file(files: FakeFileReader, importer: FakeKnowledgeImporter) -> ImportFileHandler:
    """The `import file` handler over the fakes."""
    common: dict[str, Any] = _common("")
    return ImportFileHandler(files=files, importer=importer, **common)


async def plan(
    files: dict[str, bytes],
    importer: FakeKnowledgeImporter | None = None,
    *,
    update: bool = False,
    strict: bool = False,
) -> dict[str, Any]:
    """Preview over `files`; the result as a JSON-native dict."""
    handler = build_plan(FakeVaultReader(files), importer or FakeKnowledgeImporter())
    result = await handler.handle(PlanVaultImportQuery(update=update, strict=strict))
    return result.model_dump(mode="json")


async def run(
    files: dict[str, bytes],
    importer: FakeKnowledgeImporter | None = None,
    *,
    update: bool = False,
    strict: bool = False,
) -> dict[str, Any]:
    """Apply over `files`; the result as a JSON-native dict."""
    handler = build_run(FakeVaultReader(files), importer or FakeKnowledgeImporter())
    result = await handler.handle(RunVaultImportCommand(update=update, strict=strict))
    return result.model_dump(mode="json")


def row(result: dict[str, Any], path: str) -> dict[str, Any]:
    """The result row of `path`."""
    rows: list[dict[str, Any]] = [item for item in result["notes"] if item["path"] == path]
    assert len(rows) == 1, (path, [item["path"] for item in result["notes"]])
    return rows[0]


def file_command(path: str, **options: Any) -> ImportFileCommand:
    """`ImportFileCommand` with no option set unless given."""
    values: dict[str, Any] = {
        "path": path,
        "title": None,
        "subtype": None,
        "project_key": None,
        "tags": (),
        "dry_run": False,
    }
    values.update(options)
    return ImportFileCommand(**values)
