"""The title of a note: header title, first level-1 heading, or the file name."""

from collections.abc import Mapping

from noesis.bounded_context.interop.domain.services.markdown_text import (
    fenced_lines,
    heading_level,
    links_to_text,
)

MARKDOWN_SUFFIX: str = ".md"


class TitleRule:
    """Q-017: header title, else first level-1 heading outside code, else the file stem."""

    def resolve(self, header: Mapping[str, object], body: str, file_name: str) -> str:
        """The title.

        Args:
            header: The parsed header (empty when there is none).
            body: The body after step 0 and before the links-only removal.
            file_name: The note's file name (last path segment).
        """
        declared: object = header.get("title")
        if isinstance(declared, str) and declared.strip():
            return declared.strip()
        heading: str | None = self._first_heading(body)
        if heading:
            return heading
        stem: str = file_name.removesuffix(MARKDOWN_SUFFIX)
        return stem.replace("-", " ").replace("_", " ")

    def _first_heading(self, body: str) -> str | None:
        lines: list[str] = body.split("\n")
        fenced: list[bool] = fenced_lines(lines)
        for index, line in enumerate(lines):
            if not fenced[index] and heading_level(line) == 1:
                text: str = links_to_text(line.lstrip(" ")[1:]).strip()
                return text or None
        return None
