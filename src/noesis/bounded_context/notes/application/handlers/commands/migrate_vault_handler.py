"""Restructure the vault to the manifest layout, from a plan, without ever losing a file."""

import posixpath
from collections.abc import Sequence
from dataclasses import dataclass, field

from noesis.bounded_context.notes.application.dtos import ParsedDocumentDto, VaultMigrationDto
from noesis.bounded_context.notes.application.ports.manifest import IManifestProvider
from noesis.bounded_context.notes.application.ports.vault import IVaultFiles
from noesis.bounded_context.notes.application.services.migration import (
    MigrationActionEnum,
    MigrationEntry,
    MigrationPlan,
    NoteDocumentMigrator,
    WikilinkRewriter,
)
from noesis.bounded_context.notes.domain.value_objects import NoteKind, NoteScope
from noesis.exceptions import (
    InvalidMigrationPlanError,
    MigrationConflictError,
    MigrationVerificationError,
)
from noesis.shared_kernel.application.handlers import IHandler
from noesis.shared_kernel.domain import JsonValue
from noesis.utils import FrozenObject

NOTE_SUFFIX: str = ".md"
MAX_REPORTED: int = 50


class MigrateVaultCommand(FrozenObject):
    """Migrate the vault.

    Attributes:
        plan_text: The plan file's content (JSON).
        apply: Write the changes; without it nothing is written (a dry run).
    """

    plan_text: str
    apply: bool = False


@dataclass(slots=True)
class _Step:
    """One entry that still has something to do, or was found done.

    Attributes:
        entry: The plan line.
        data: Bytes to write at the target, or None when the target is already there.
        old_text: The note's text before the migration (an in-place rewrite loses it from disk).
        delete_old: Whether the old file is still there and goes once the target is verified.
        verify: Whether the target is checked against its source.
    """

    entry: MigrationEntry
    data: bytes | None = None
    old_text: str | None = None
    delete_old: bool = False
    verify: bool = False


@dataclass(slots=True)
class _Assessment:
    steps: list[_Step] = field(default_factory=list)
    done: int = 0
    problems: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)


def _visible(path: str) -> bool:
    return not any(part.startswith(".") for part in path.split("/"))


def _decode(data: bytes) -> str | None:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


class MigrateVaultHandler(IHandler[MigrateVaultCommand, VaultMigrationDto]):
    """Writes every target, verifies it, rewrites wikilinks, and only then deletes the sources.

    Each step can be repeated: a run that stopped anywhere is finished by running it again, and
    a target that exists with other content than its source stops everything before any
    write (`MigrationConflictError`).
    """

    def __init__(
        self,
        *,
        vault: IVaultFiles,
        manifests: IManifestProvider,
        migrator: NoteDocumentMigrator,
    ) -> None:
        self._vault: IVaultFiles = vault
        self._manifests: IManifestProvider = manifests
        self._migrator: NoteDocumentMigrator = migrator

    async def handle(self, action: MigrateVaultCommand) -> VaultMigrationDto:
        """Plan the migration and, with `apply`, carry it out.

        Raises:
            InvalidMigrationPlanError: The plan is malformed or does not fit the vault.
            MigrationConflictError: A target exists with different content.
            MigrationVerificationError: A written target does not match its source.
        """
        plan: MigrationPlan = MigrationPlan.parse(action.plan_text)
        plan.validate_against((await self._manifests.load()).catalog())
        present: set[str] = set(await self._vault.list_files())
        moves: dict[str, str] = {e.old: e.target for e in plan.entries if e.relocates}
        rewriter: WikilinkRewriter = WikilinkRewriter(moves, present)
        assessment: _Assessment = await self._assess(plan, present, rewriter)
        self._refuse(assessment)
        unresolved_before: int = await self._unresolved_before(present, rewriter)
        writes: list[_Step] = [step for step in assessment.steps if step.data is not None]
        deletes: list[_Step] = [step for step in assessment.steps if step.delete_old]
        lines: list[str] = [self._line(step) for step in assessment.steps]

        if action.apply:
            await self._write_all(writes)
            await self._verify_all([step for step in assessment.steps if step.verify], rewriter)
            texts: dict[str, str] = await self._texts(
                set(await self._vault.list_files()) - {s.entry.old for s in deletes}, {}
            )
        else:
            after: set[str] = (present - {s.entry.old for s in deletes}) | {
                s.entry.target for s in writes
            }
            virtual: dict[str, bytes] = {
                s.entry.target: s.data for s in writes if s.data is not None
            }
            texts = await self._texts(after, virtual)
        rewritten: dict[str, str] = {}
        unresolved_after: int = 0
        links: int = 0
        for path, text in texts.items():
            new_text, count = rewriter.rewrite(text)
            unresolved_after += rewriter.count_unresolved(new_text, after=True)
            if count:
                rewritten[path] = new_text
                links += count
        remaining: set[str] = (present - {s.entry.old for s in deletes}) | {
            s.entry.target for s in writes
        }
        candidates: list[str] = await self._empty_dir_candidates(plan, remaining)

        removed: int
        if action.apply:
            for path, new_text in rewritten.items():
                await self._vault.write(path, new_text.encode("utf-8"))
            on_disk: set[str] = set(await self._vault.list_files())
            for step in deletes:
                if step.entry.target not in on_disk:
                    raise MigrationVerificationError(
                        f"Refusing to delete {step.entry.old}: its target is missing.",
                        {"old": step.entry.old, "new": step.entry.target},
                    )
                await self._vault.delete(step.entry.old)
            removed = len(await self._vault.remove_empty_dirs(candidates))
        else:
            removed = len(candidates)

        counts: dict[str, int] = plan.counts()
        return VaultMigrationDto(
            applied=action.apply,
            notes=counts[MigrationActionEnum.NOTE.value],
            moves=counts[MigrationActionEnum.MOVE.value],
            keeps=counts[MigrationActionEnum.KEEP.value],
            to_write=len(writes),
            already_done=assessment.done,
            to_delete=len(deletes),
            links_rewritten=links,
            link_files=len(rewritten),
            unresolved_before=unresolved_before,
            unresolved_after=unresolved_after,
            dirs_removed=removed,
            lines=tuple(lines),
        )

    async def _assess(
        self, plan: MigrationPlan, present: set[str], rewriter: WikilinkRewriter
    ) -> _Assessment:
        result: _Assessment = _Assessment()
        for entry in plan.entries:
            if entry.action is MigrationActionEnum.KEEP:
                continue
            if entry.action is MigrationActionEnum.MOVE:
                await self._assess_move(entry, present, rewriter, result)
            else:
                await self._assess_note(entry, present, rewriter, result)
        return result

    async def _assess_move(
        self,
        entry: MigrationEntry,
        present: set[str],
        rewriter: WikilinkRewriter,
        result: _Assessment,
    ) -> None:
        old_here, new_here = entry.old in present, entry.target in present
        if not old_here and not new_here:
            result.problems.append(f"missing: {entry.old}")
        elif not old_here:
            result.done += 1
        elif not new_here:
            result.steps.append(
                _Step(entry, data=await self._vault.read(entry.old), delete_old=True, verify=True)
            )
        elif self._same_bytes(
            await self._vault.read(entry.old), await self._vault.read(entry.target), rewriter, entry
        ):
            result.steps.append(_Step(entry, delete_old=True, verify=True))
        else:
            result.conflicts.append(f"{entry.old} -> {entry.target}")

    @staticmethod
    def _same_bytes(
        old: bytes, new: bytes, rewriter: WikilinkRewriter, entry: MigrationEntry
    ) -> bool:
        if old == new:
            return True
        text: str | None = _decode(old) if entry.old.endswith(NOTE_SUFFIX) else None
        return text is not None and rewriter.rewrite(text)[0].encode("utf-8") == new

    async def _assess_note(
        self,
        entry: MigrationEntry,
        present: set[str],
        rewriter: WikilinkRewriter,
        result: _Assessment,
    ) -> None:
        scope: NoteScope = NoteScope.parse(entry.scope or "")
        kind: NoteKind = NoteKind(value=entry.kind or "")
        in_place: bool = entry.old == entry.target
        old_here, new_here = entry.old in present, entry.target in present
        if not old_here and not new_here:
            result.problems.append(f"missing: {entry.old}")
            return
        if not old_here:
            result.done += 1
            return
        old_text: str | None = _decode(await self._vault.read(entry.old))
        if old_text is None:
            result.problems.append(f"not UTF-8 text: {entry.old}")
            return
        old: ParsedDocumentDto = self._migrator.parse(old_text)
        if old.malformed_header:
            result.problems.append(f"unreadable YAML header: {entry.old}")
            return
        if in_place:
            if self._migrator.is_current(old, scope, kind):
                result.done += 1
            else:
                data: bytes = self._migrator.build(old, scope, kind).encode("utf-8")
                result.steps.append(_Step(entry, data=data, old_text=old_text, verify=True))
        elif not new_here:
            data = self._migrator.build(old, scope, kind).encode("utf-8")
            result.steps.append(
                _Step(entry, data=data, old_text=old_text, delete_old=True, verify=True)
            )
        elif self._note_matches(old_text, await self._vault.read(entry.target), entry, rewriter):
            result.steps.append(_Step(entry, old_text=old_text, delete_old=True, verify=True))
        else:
            result.conflicts.append(f"{entry.old} -> {entry.target}")

    def _note_matches(
        self, old_text: str, new_data: bytes, entry: MigrationEntry, rewriter: WikilinkRewriter
    ) -> bool:
        """Whether `new_data` is `old_text` migrated: same body (up to links), header kept."""
        new_text: str | None = _decode(new_data)
        if new_text is None:
            return False
        old, new = self._migrator.parse(old_text), self._migrator.parse(new_text)
        relinked: ParsedDocumentDto = self._migrator.parse(rewriter.rewrite(old_text)[0])
        scope: NoteScope = NoteScope.parse(entry.scope or "")
        kind: NoteKind = NoteKind(value=entry.kind or "")
        return (
            self._migrator.is_current(new, scope, kind)
            and new.body in {old.body, relinked.body}
            and (
                self._migrator.keeps_header(old, new) or self._migrator.keeps_header(relinked, new)
            )
        )

    @staticmethod
    def _refuse(assessment: _Assessment) -> None:
        if assessment.problems:
            raise InvalidMigrationPlanError(
                f"The plan does not fit the vault ({len(assessment.problems)} problem(s)); "
                f"first: {assessment.problems[0]}",
                {"problems": list[JsonValue](assessment.problems[:MAX_REPORTED])},
                next_steps=["Regenerate the plan from the current vault."],
            )
        if assessment.conflicts:
            raise MigrationConflictError(
                f"{len(assessment.conflicts)} target(s) already exist with different content; "
                "nothing was written.",
                {"conflicts": list[JsonValue](assessment.conflicts[:MAX_REPORTED])},
                next_steps=["Resolve each conflict by hand, then run the migration again."],
            )

    async def _write_all(self, steps: Sequence[_Step]) -> None:
        for step in steps:
            if step.data is not None:
                await self._vault.write(step.entry.target, step.data)

    async def _verify_all(self, steps: Sequence[_Step], rewriter: WikilinkRewriter) -> None:
        for step in steps:
            entry: MigrationEntry = step.entry
            written: bytes = await self._vault.read(entry.target)
            if entry.action is MigrationActionEnum.MOVE:
                good: bool = self._same_bytes(
                    await self._vault.read(entry.old), written, rewriter, entry
                )
            else:
                old_text: str | None = step.old_text
                good = old_text is not None and self._note_matches(
                    old_text, written, entry, rewriter
                )
            if not good:
                raise MigrationVerificationError(
                    f"The written file {entry.target} does not match {entry.old}; "
                    "no file was deleted.",
                    {"old": entry.old, "new": entry.target},
                    next_steps=["Run the migration again after checking the vault."],
                )

    async def _unresolved_before(self, present: set[str], rewriter: WikilinkRewriter) -> int:
        total: int = 0
        for path in sorted(present):
            if path.endswith(NOTE_SUFFIX) and _visible(path):
                text: str | None = _decode(await self._vault.read(path))
                total += rewriter.count_unresolved(text, after=False) if text is not None else 0
        return total

    async def _texts(self, paths: set[str], virtual: dict[str, bytes]) -> dict[str, str]:
        """Text of every visible Markdown file as it stands after the writes."""
        texts: dict[str, str] = {}
        for path in sorted(paths):
            if not (path.endswith(NOTE_SUFFIX) and _visible(path)):
                continue
            text: str | None = _decode(
                virtual[path] if path in virtual else await self._vault.read(path)
            )
            if text is not None:
                texts[path] = text
        return texts

    async def _empty_dir_candidates(self, plan: MigrationPlan, remaining: set[str]) -> list[str]:
        """Folders that hold no file once the migration is done, deepest first.

        Visible folders, and the folders above a moved file, whether or not they are hidden.
        """
        dirs: list[str] = await self._vault.list_dirs()
        sources: set[str] = set()
        for entry in plan.entries:
            if entry.relocates:
                parent: str = posixpath.dirname(entry.old)
                while parent:
                    sources.add(parent)
                    parent = posixpath.dirname(parent)
        occupied: set[str] = set()
        for path in remaining:
            parent = posixpath.dirname(path)
            while parent:
                occupied.add(parent)
                parent = posixpath.dirname(parent)
        alive: set[str] = set(dirs)
        removable: list[str] = []
        for directory in sorted(dirs, key=lambda d: (-d.count("/"), d)):
            wanted: bool = directory not in occupied and (
                _visible(directory) or directory in sources
            )
            if wanted and not any(other.startswith(f"{directory}/") for other in alive):
                removable.append(directory)
                alive.discard(directory)
        return removable

    @staticmethod
    def _line(step: _Step) -> str:
        entry: MigrationEntry = step.entry
        what: str = "write" if step.data is not None else "verify"
        where: str = entry.old if not entry.relocates else f"{entry.old} -> {entry.target}"
        return f"{entry.action.value:<4} {what:<6} {where}"
