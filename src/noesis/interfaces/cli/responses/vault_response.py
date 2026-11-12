"""`noesis vault` output."""

from noesis.utils import FrozenObject

from .i_renderable_response import IRenderableResponse


class DuplicateProjectResponse(FrozenObject):
    """A project name found under more than one root.

    Attributes:
        name: The folder name.
        roots: The roots it exists under.
    """

    name: str
    roots: tuple[str, ...]


class VaultDoctorResponse(IRenderableResponse):
    """`noesis vault doctor`: notes by frontmatter state and projects kept twice.

    Attributes:
        markdown_files: Visible Markdown files.
        with_frontmatter: Files with a valid `noesis:` block.
        without_frontmatter: Files with no `noesis:` block.
        invalid_frontmatter: Files whose header or `noesis:` block cannot be read.
        duplicate_projects: Project names found under two roots or more.
        without_paths: Files without a block (only with `--verbose`).
        invalid_paths: Files with an invalid header or block (only with `--verbose`).
    """

    markdown_files: int
    with_frontmatter: int
    without_frontmatter: int
    invalid_frontmatter: int
    duplicate_projects: tuple[DuplicateProjectResponse, ...]
    without_paths: tuple[str, ...] = ()
    invalid_paths: tuple[str, ...] = ()

    def render(self) -> str:
        lines: list[str] = [
            f"markdown files: {self.markdown_files}",
            f"with noesis frontmatter: {self.with_frontmatter}",
            f"without noesis frontmatter: {self.without_frontmatter}",
            f"invalid frontmatter: {self.invalid_frontmatter}",
            f"projects under two roots: {len(self.duplicate_projects)}",
        ]
        lines += [f"  {p.name}: {', '.join(p.roots)}" for p in self.duplicate_projects]
        lines += [f"without: {path}" for path in self.without_paths]
        lines += [f"invalid: {path}" for path in self.invalid_paths]
        return "\n".join(lines)


class VaultMigrationResponse(IRenderableResponse):
    """`noesis vault migrate`: what the plan did, or would do on a dry run.

    Attributes:
        applied: Whether files were written.
        notes: Plan entries with action `note`.
        moves: Plan entries with action `move`.
        keeps: Plan entries with action `keep`.
        to_write: Target files not yet written.
        already_done: Targets already in place.
        to_delete: Old files waiting to be deleted.
        links_rewritten: Wikilinks rewritten.
        link_files: Files that held rewritten links.
        unresolved_before: Wikilinks pointing at no file before the migration.
        unresolved_after: Wikilinks pointing at no file after it.
        dirs_removed: Empty folders removed.
        pending: Work a dry run still finds; zero means the vault matches the plan.
        lines: One line per entry with work (only with `--verbose`).
    """

    applied: bool
    notes: int
    moves: int
    keeps: int
    to_write: int
    already_done: int
    to_delete: int
    links_rewritten: int
    link_files: int
    unresolved_before: int
    unresolved_after: int
    dirs_removed: int
    pending: int
    lines: tuple[str, ...] = ()

    def render(self) -> str:
        done: str = "applied" if self.applied else "dry run (nothing written; use --apply)"
        head: list[str] = [
            done,
            f"plan: {self.notes} note, {self.moves} move, {self.keeps} keep",
            f"files written: {self.to_write}" if self.applied else f"to write: {self.to_write}",
            f"already in place: {self.already_done}",
            f"old files deleted: {self.to_delete}"
            if self.applied
            else f"old files to delete: {self.to_delete}",
            f"wikilinks rewritten: {self.links_rewritten} in {self.link_files} file(s)"
            if self.applied
            else f"wikilinks to rewrite: {self.links_rewritten} in {self.link_files} file(s)",
            f"unresolved wikilinks: {self.unresolved_before} before, {self.unresolved_after} after",
            f"empty folders removed: {self.dirs_removed}"
            if self.applied
            else f"empty folders to remove: {self.dirs_removed}",
        ]
        return "\n".join(head + list(self.lines))
