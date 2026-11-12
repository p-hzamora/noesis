"""`MigrateVaultHandler` and `DiagnoseVaultHandler` on a real folder."""

import hashlib
import json
import re
from collections.abc import Sequence
from datetime import date
from pathlib import Path

import pytest
from tests.support.notes_support import SequentialIds

from noesis.bounded_context.notes.application.dtos import VaultMigrationDto
from noesis.bounded_context.notes.application.handlers.commands import (
    MigrateVaultCommand,
    MigrateVaultHandler,
)
from noesis.bounded_context.notes.application.handlers.queries import (
    DiagnoseVaultHandler,
    DiagnoseVaultQuery,
)
from noesis.bounded_context.notes.application.ports.vault import IVaultFiles
from noesis.bounded_context.notes.application.services.migration import NoteDocumentMigrator
from noesis.bounded_context.notes.infrastructure.outbound.frontmatter import (
    YamlFrontmatterCodecAdapter,
)
from noesis.bounded_context.notes.infrastructure.outbound.manifest import (
    YamlManifestProviderAdapter,
)
from noesis.bounded_context.notes.infrastructure.outbound.vault import FilesystemVaultFilesAdapter
from noesis.exceptions import (
    InvalidMigrationPlanError,
    MigrationConflictError,
    MigrationVerificationError,
)

pytestmark = pytest.mark.integration

CODEC = YamlFrontmatterCodecAdapter()
LEGACY_NOTE: str = (
    "---\ntype: decision\nid: legacy-id\nrepo: alpha\narea: company\norigin: auto\n"
    "session: s1\ncommits: [abc123]\ncreated: 2026-01-02\ntags: [one, two]\naliases: [Use X]\n"
    "---\n\n# Use X\n\n## Decision\n\nSee [[company/p/alpha/index|the hub]] and [[arch#Why]].\n"
)
HUB: str = "---\ntype: index\nrepo: alpha\n---\n# alpha\n[[company/p/alpha/decisions/use-x]]\n"
VALID_NOTE: str = (
    "---\nnoesis:\n  id: 01ARZ3NDEKTSV4RRFFQ69G5FAV\n  scope: repo:beta\n  kind: gotcha\n"
    "  origin: manual\n  sources: []\n  updated: 2026-11-01\n---\n\n# Trap\n"
)
ID_PATTERN = re.compile(r"[0-9A-Z]{26}")

FILES: dict[str, str | bytes] = {
    "company/p/alpha/index.md": HUB,
    "company/p/alpha/brain.config.json": '{"repo": "alpha"}',
    "company/p/alpha/logo.png": b"\x89PNG\x00\xff",
    "company/p/alpha/decisions/use-x.md": LEGACY_NOTE,
    "company/p/alpha/drift/d1.md": "# Drift\n\n## What drifted\n\nx [[company/p/alpha/index]]\n",
    "repos/beta/auto/gotchas/g.md": "---\ntype: gotcha\ntags: [t]\n---\n# G\n",
    "repos/beta/gotchas/ok.md": VALID_NOTE,
    "learning/t/plain.md": "# Plain\n\nbody\n",
    "README.md": "[[company/p/alpha/index|Alpha]] [[arch]] [[nowhere]]\n",
    "repos/beta/concepts/arch.md": "# Arch\n",
    "company/branding/guide.md": "---\ntype: reference\n---\nbrand\n",
}
PLAN: list[dict[str, str]] = [
    {"old": "company/p/alpha/index.md", "new": "repos/alpha/index.md", "action": "move"},
    {
        "old": "company/p/alpha/brain.config.json",
        "new": "repos/alpha/brain.config.json",
        "action": "move",
    },
    {"old": "company/p/alpha/logo.png", "new": "repos/alpha/logo.png", "action": "move"},
    {
        "old": "company/p/alpha/decisions/use-x.md",
        "new": "repos/alpha/decisions/use-x.md",
        "action": "note",
        "scope": "repo:alpha",
        "kind": "decision",
    },
    {
        "old": "company/p/alpha/drift/d1.md",
        "new": "repos/alpha/drift/d1.md",
        "action": "note",
        "scope": "repo:alpha",
        "kind": "drift",
    },
    {
        "old": "repos/beta/auto/gotchas/g.md",
        "new": "repos/beta/gotchas/g.md",
        "action": "note",
        "scope": "repo:beta",
        "kind": "gotcha",
    },
    {"old": "repos/beta/gotchas/ok.md", "action": "keep"},
    {
        "old": "learning/t/plain.md",
        "new": "learning/t/concepts/plain.md",
        "action": "note",
        "scope": "topic:t",
        "kind": "concept",
    },
    {"old": "README.md", "action": "keep"},
    {"old": "company/branding/guide.md", "action": "keep"},
]


def build_vault(root: Path, files: dict[str, str | bytes] = FILES) -> Path:
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))
    for empty in ("decisions", "tmp", "company/p/alpha/empty/deeper"):
        (root / empty).mkdir(parents=True, exist_ok=True)
    return root


def snapshot(root: Path) -> dict[str, str]:
    """Every file and folder under `root`, with ids masked (a rerun may mint other ones)."""
    found: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_dir():
            found[relative + "/"] = ""
        else:
            raw = path.read_bytes()
            try:
                text = ID_PATTERN.sub("<ID>", raw.decode("utf-8"))
                found[relative] = hashlib.sha256(text.encode()).hexdigest()
            except UnicodeDecodeError:
                found[relative] = hashlib.sha256(raw).hexdigest()
    return found


def handler(root: Path, vault: IVaultFiles | None = None) -> MigrateVaultHandler:
    return MigrateVaultHandler(
        vault=vault or FilesystemVaultFilesAdapter(root),
        manifests=YamlManifestProviderAdapter(None),
        migrator=NoteDocumentMigrator(CODEC, SequentialIds(), date(2026, 11, 12)),
    )


def command(plan: Sequence[dict[str, str]] = PLAN, *, apply: bool) -> MigrateVaultCommand:
    return MigrateVaultCommand(plan_text=json.dumps(plan), apply=apply)


async def test_a_dry_run_changes_nothing_and_reports_what_it_would_do(tmp_path: Path) -> None:
    build_vault(tmp_path)
    before = snapshot(tmp_path)

    result = await handler(tmp_path).handle(command(apply=False))

    assert snapshot(tmp_path) == before
    assert not result.applied
    assert (result.notes, result.moves, result.keeps) == (4, 3, 3)
    assert (result.to_write, result.to_delete, result.already_done) == (7, 7, 0)
    assert result.links_rewritten == 4 and result.link_files == 4
    assert (result.unresolved_before, result.unresolved_after) == (1, 1)
    assert result.dirs_removed == 10
    assert len(result.lines) == 7


async def test_apply_moves_everything_and_a_second_run_plans_nothing(tmp_path: Path) -> None:
    build_vault(tmp_path)

    applied = await handler(tmp_path).handle(command(apply=True))
    again = await handler(tmp_path).handle(command(apply=False))

    assert applied.applied and applied.to_write == 7 and applied.dirs_removed == 10
    assert (again.to_write, again.to_delete, again.links_rewritten, again.dirs_removed) == (
        0,
        0,
        0,
        0,
    )
    assert again.pending == 0 and again.already_done == 7
    assert (tmp_path / "repos/alpha/logo.png").read_bytes() == b"\x89PNG\x00\xff"
    assert (tmp_path / "repos/alpha/brain.config.json").read_text() == '{"repo": "alpha"}'
    assert not (tmp_path / "company/p").exists()
    assert not (tmp_path / "decisions").exists() and not (tmp_path / "tmp").exists()
    assert (
        tmp_path / "company/branding/guide.md"
    ).read_text() == "---\ntype: reference\n---\nbrand\n"


async def test_a_note_keeps_every_foreign_key_and_drops_only_the_legacy_ones(
    tmp_path: Path,
) -> None:
    build_vault(tmp_path)
    await handler(tmp_path).handle(command(apply=True))

    document = CODEC.parse((tmp_path / "repos/alpha/decisions/use-x.md").read_text())

    assert list(document.header) == ["created", "tags", "aliases", "noesis"]
    assert document.header["created"] == "2026-01-02"
    assert document.header["tags"] == ["one", "two"] and document.header["aliases"] == ["Use X"]
    frontmatter = document.frontmatter
    assert frontmatter is not None
    assert (frontmatter.scope.value, frontmatter.kind.value, frontmatter.origin.value) == (
        "repo:alpha",
        "decision",
        "auto",
    )
    assert [ref.value for ref in frontmatter.sources] == ["commit:abc123", "session:s1"]
    assert frontmatter.updated == date(2026, 11, 12)
    assert document.body == (
        "\n# Use X\n\n## Decision\n\nSee [[repos/alpha/index|the hub]] and [[arch#Why]].\n"
    )


async def test_a_note_without_a_header_gets_one_and_a_valid_note_is_only_moved_when_needed(
    tmp_path: Path,
) -> None:
    build_vault(tmp_path)
    await handler(tmp_path).handle(command(apply=True))

    plain = CODEC.parse((tmp_path / "learning/t/concepts/plain.md").read_text())
    assert plain.frontmatter is not None and plain.frontmatter.scope.value == "topic:t"
    assert plain.body == "# Plain\n\nbody\n"
    assert (tmp_path / "repos/beta/gotchas/ok.md").read_text() == VALID_NOTE  # keep: untouched


async def test_an_existing_block_is_refreshed_keeping_its_id(tmp_path: Path) -> None:
    files: dict[str, str | bytes] = {"misc/trap.md": VALID_NOTE}
    build_vault(tmp_path, files)
    plan = [
        {
            "old": "misc/trap.md",
            "new": "repos/beta/howtos/trap.md",
            "action": "note",
            "scope": "repo:beta",
            "kind": "howto",
        }
    ]
    await handler(tmp_path).handle(command(plan, apply=True))

    frontmatter = CODEC.parse((tmp_path / "repos/beta/howtos/trap.md").read_text()).frontmatter
    assert frontmatter is not None
    assert (frontmatter.id.value, frontmatter.kind.value) == ("01ARZ3NDEKTSV4RRFFQ69G5FAV", "howto")


async def test_a_note_can_be_rewritten_in_place(tmp_path: Path) -> None:
    build_vault(tmp_path, {"repos/x/decisions/d.md": "---\ntags: [a]\n---\n# D\n"})
    plan = [
        {
            "old": "repos/x/decisions/d.md",
            "new": "repos/x/decisions/d.md",
            "action": "note",
            "scope": "repo:x",
            "kind": "decision",
        }
    ]
    result = await handler(tmp_path).handle(command(plan, apply=True))
    assert (result.to_write, result.to_delete) == (1, 0)
    assert CODEC.parse((tmp_path / "repos/x/decisions/d.md").read_text()).frontmatter is not None
    assert (await handler(tmp_path).handle(command(plan, apply=False))).pending == 0


async def test_keep_entries_are_never_touched(tmp_path: Path) -> None:
    build_vault(tmp_path)
    kept = {
        p: (tmp_path / p).read_bytes()
        for p in ("repos/beta/gotchas/ok.md", "company/branding/guide.md")
    }
    await handler(tmp_path).handle(command(apply=True))
    for path, content in kept.items():
        assert (tmp_path / path).read_bytes() == content


async def test_wikilinks_are_rewritten_in_every_markdown_file_but_dot_folders_are_left(
    tmp_path: Path,
) -> None:
    files = {**FILES, ".obsidian/notes.md": "[[company/p/alpha/index]]\n"}
    build_vault(tmp_path, files)
    await handler(tmp_path).handle(command(apply=True))

    assert (
        tmp_path / "README.md"
    ).read_text() == "[[repos/alpha/index|Alpha]] [[arch]] [[nowhere]]\n"
    assert "[[repos/alpha/index]]" in (tmp_path / "repos/alpha/drift/d1.md").read_text()
    assert "[[repos/alpha/decisions/use-x]]" in (tmp_path / "repos/alpha/index.md").read_text()
    assert (tmp_path / ".obsidian/notes.md").read_text() == "[[company/p/alpha/index]]\n"


async def test_a_target_with_other_content_is_a_conflict_and_nothing_is_written(
    tmp_path: Path,
) -> None:
    build_vault(tmp_path, {**FILES, "repos/alpha/index.md": "someone else's hub\n"})
    before = snapshot(tmp_path)

    with pytest.raises(MigrationConflictError) as caught:
        await handler(tmp_path).handle(command(apply=True))

    assert caught.value.metadata["conflicts"] == [
        "company/p/alpha/index.md -> repos/alpha/index.md"
    ]
    assert snapshot(tmp_path) == before


async def test_a_target_with_identical_content_is_taken_as_already_done(tmp_path: Path) -> None:
    build_vault(tmp_path, {**FILES, "repos/alpha/logo.png": b"\x89PNG\x00\xff"})
    result = await handler(tmp_path).handle(command(apply=True))
    assert result.to_write == 6 and not (tmp_path / "company/p/alpha/logo.png").exists()
    assert (tmp_path / "repos/alpha/logo.png").read_bytes() == b"\x89PNG\x00\xff"


async def test_a_source_that_is_missing_everywhere_stops_the_run(tmp_path: Path) -> None:
    build_vault(tmp_path)
    (tmp_path / "company/p/alpha/logo.png").unlink()
    with pytest.raises(InvalidMigrationPlanError, match=r"missing: company/p/alpha/logo\.png"):
        await handler(tmp_path).handle(command(apply=True))


async def test_an_unreadable_yaml_header_is_refused_not_rewritten(tmp_path: Path) -> None:
    broken = "---\nkey: [unclosed\n---\n# Body\n"
    build_vault(tmp_path, {"misc/b.md": broken})
    plan = [
        {
            "old": "misc/b.md",
            "new": "repos/x/concepts/b.md",
            "action": "note",
            "scope": "repo:x",
            "kind": "concept",
        }
    ]
    with pytest.raises(InvalidMigrationPlanError, match="unreadable YAML header"):
        await handler(tmp_path).handle(command(plan, apply=True))
    assert (tmp_path / "misc/b.md").read_text() == broken


async def test_empty_folders_go_but_a_folder_with_anything_stays(tmp_path: Path) -> None:
    files = {**FILES, "company/p/alpha/empty/keepme.txt": "x"}
    build_vault(tmp_path, files)
    result = await handler(tmp_path).handle(command(apply=True))
    assert (tmp_path / "company/p/alpha/empty/keepme.txt").read_text() == "x"
    assert not (tmp_path / "company/p/alpha/empty/deeper").exists()  # empty: goes
    assert not (tmp_path / "company/p/alpha/decisions").exists()
    assert result.dirs_removed == 7


async def test_a_note_in_a_hidden_folder_is_moved_and_its_emptied_folders_go(
    tmp_path: Path,
) -> None:
    build_vault(tmp_path, {"repos/.dot/auto/decisions/d.md": "---\ntype: decision\n---\n# D\n"})
    plan = [
        {
            "old": "repos/.dot/auto/decisions/d.md",
            "new": "repos/dot/decisions/d.md",
            "action": "note",
            "scope": "repo:dot",
            "kind": "decision",
        }
    ]
    await handler(tmp_path).handle(command(plan, apply=True))
    assert not (tmp_path / "repos/.dot").exists()
    assert (tmp_path / "repos/dot/decisions/d.md").is_file()


class Crash(Exception):  # noqa: N818 - a test double for a killed process
    pass


class CrashingVault(IVaultFiles):
    """Fails before the `crash_at`-th change (0-based), as a killed process would."""

    def __init__(self, inner: IVaultFiles, crash_at: int | None) -> None:
        self.inner: IVaultFiles = inner
        self.crash_at: int | None = crash_at
        self.changes: list[str] = []

    def _change(self, what: str) -> None:
        if self.crash_at == len(self.changes):
            raise Crash(what)
        self.changes.append(what)

    async def list_files(self) -> list[str]:
        return await self.inner.list_files()

    async def list_dirs(self) -> list[str]:
        return await self.inner.list_dirs()

    async def read(self, path: str) -> bytes:
        return await self.inner.read(path)

    async def write(self, path: str, data: bytes) -> None:
        self._change(f"write {path}")
        await self.inner.write(path, data)

    async def delete(self, path: str) -> None:
        self._change(f"delete {path}")
        await self.inner.delete(path)

    async def remove_empty_dirs(self, paths: Sequence[str]) -> list[str]:
        self._change("remove_empty_dirs")
        return await self.inner.remove_empty_dirs(paths)


async def test_a_crash_before_any_single_change_is_finished_by_running_again(
    tmp_path: Path,
) -> None:
    clean = build_vault(tmp_path / "clean")
    counter = CrashingVault(FilesystemVaultFilesAdapter(clean), None)
    await handler(clean, counter).handle(command(apply=True))
    expected = snapshot(clean)
    steps = counter.changes
    assert len(steps) == 19  # 7 new files, 4 link rewrites, 7 deletes, the folder sweep
    assert [s.split()[0] for s in steps].count("write") == 11
    assert steps[-1] == "remove_empty_dirs"

    for crash_at in range(len(steps)):
        root = build_vault(tmp_path / f"crash-{crash_at}")
        with pytest.raises(Crash):
            await handler(root, CrashingVault(FilesystemVaultFilesAdapter(root), crash_at)).handle(
                command(apply=True)
            )
        await handler(root).handle(command(apply=True))
        assert snapshot(root) == expected, (
            f"after a crash before change {crash_at}: {steps[crash_at]}"
        )
        assert (await handler(root).handle(command(apply=False))).pending == 0


async def test_nothing_is_deleted_when_a_written_file_fails_verification(tmp_path: Path) -> None:
    class Corrupting(FilesystemVaultFilesAdapter):
        async def write(self, path: str, data: bytes) -> None:
            await super().write(path, data[:-1] if path.endswith("logo.png") else data)

    build_vault(tmp_path)
    with pytest.raises(MigrationVerificationError):
        await handler(tmp_path, Corrupting(tmp_path)).handle(command(apply=True))
    assert (tmp_path / "company/p/alpha/logo.png").read_bytes() == b"\x89PNG\x00\xff"
    assert (tmp_path / "company/p/alpha/decisions/use-x.md").read_text() == LEGACY_NOTE


async def test_the_doctor_counts_notes_and_finds_projects_under_two_roots(tmp_path: Path) -> None:
    files: dict[str, str | bytes] = {
        "repos/beta/gotchas/ok.md": VALID_NOTE,
        "repos/beta/gotchas/plain.md": "# plain\n",
        "repos/beta/gotchas/bad.md": "---\nkey: [unclosed\n---\n",
        "repos/beta/gotchas/badblock.md": "---\nnoesis:\n  id: nope\n---\n",
        "company/p/beta/index.md": "# beta\n",
        "personal/projects/beta/index.md": "# beta\n",
        "company/p/solo/index.md": "# solo\n",
        ".obsidian/x.md": "# hidden\n",
        "logo.png": b"x",
    }
    build_vault(tmp_path, files)
    doctor = DiagnoseVaultHandler(
        vault=FilesystemVaultFilesAdapter(tmp_path),
        manifests=YamlManifestProviderAdapter(None),
        codec=CODEC,
    )

    report = await doctor.handle(DiagnoseVaultQuery(roots=("company/p/", "personal/projects")))

    assert (report.markdown_files, report.with_frontmatter) == (7, 1)
    assert (report.without_frontmatter, report.invalid_frontmatter) == (4, 2)
    assert sorted(report.invalid_paths) == [
        "repos/beta/gotchas/bad.md",
        "repos/beta/gotchas/badblock.md",
    ]
    assert [(d.name, d.roots) for d in report.duplicate_projects] == [
        ("beta", ("company/p", "personal/projects", "repos"))
    ]
    assert (await doctor.handle(DiagnoseVaultQuery())).duplicate_projects == ()


def test_the_dto_adds_up_pending_work() -> None:
    dto = VaultMigrationDto(
        applied=False, notes=0, moves=0, keeps=0, to_write=1, already_done=0, to_delete=2,
        links_rewritten=3, link_files=1, unresolved_before=0, unresolved_after=0, dirs_removed=4,
    )  # fmt: skip
    assert dto.pending == 10
