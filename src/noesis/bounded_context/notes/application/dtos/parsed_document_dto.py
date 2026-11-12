"""A Markdown file split into its frontmatter and body."""

from noesis.bounded_context.notes.domain.value_objects import NoteFrontmatter
from noesis.shared_kernel.application.dtos import BaseDto
from noesis.shared_kernel.domain import JsonValue


class ParsedDocumentDto(BaseDto):
    """What a frontmatter codec found in a file.

    Attributes:
        frontmatter: The `noesis:` block; None when the file has none or it is invalid.
        header: Every key of the file's own YAML header (empty without one), so keys noesis does not
            own survive a rewrite.
        body: Everything after the header block, byte for byte (the whole text when there is
            no header).
        malformed_header: Whether the text opens with a `---` header that cannot be read as a
            YAML mapping (a file rewritten around it would keep two headers or lose one).
    """

    frontmatter: NoteFrontmatter | None
    header: dict[str, JsonValue]
    body: str
    malformed_header: bool = False
