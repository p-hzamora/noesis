"""What `noesis vault doctor` found."""

from noesis.shared_kernel.application.dtos import BaseDto


class DuplicateProjectDto(BaseDto):
    """A project name that exists under more than one root.

    Attributes:
        name: The folder name.
        roots: The roots it exists under.
    """

    name: str
    roots: tuple[str, ...]


class VaultDiagnosisDto(BaseDto):
    """Notes of the vault by whether they carry valid frontmatter, and projects kept twice.

    Attributes:
        markdown_files: Visible Markdown files.
        with_frontmatter: Files with a valid `noesis:` block.
        without_frontmatter: Files with no `noesis:` block.
        invalid_frontmatter: Files whose header or `noesis:` block cannot be read.
        duplicate_projects: Project names found under two roots or more.
        without_paths: Paths of the files without a block.
        invalid_paths: Paths of the files with an invalid header or block.
        misplaced: How many notes are misplaced.
        misplaced_paths: Notes whose folder is not where the layout places their scope, e.g.
            a grouped repository's note under `repos/`.
    """

    markdown_files: int
    with_frontmatter: int
    without_frontmatter: int
    invalid_frontmatter: int
    duplicate_projects: tuple[DuplicateProjectDto, ...]
    without_paths: tuple[str, ...] = ()
    invalid_paths: tuple[str, ...] = ()
    misplaced: int = 0
    misplaced_paths: tuple[str, ...] = ()
