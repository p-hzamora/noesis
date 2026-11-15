"""Steps 1..3 of the note text rules: links to text, links-only sections out, assemble."""

from noesis.bounded_context.interop.domain.services.markdown_text import (
    BLANK,
    fenced_lines,
    heading_level,
    is_link_only,
    links_to_text,
)


class TextNormaliser:
    """Turns a note body into the text stored as a record body.

    Deterministic and pure: the same text gives the same result on every machine.
    """

    def normalise(self, body: str) -> str:
        """The normalised body (no trailing newline; empty when nothing is left).

        Args:
            body: The body after step 0 (LF newlines, header removed).
        """
        lines: list[str] = body.split("\n")
        fenced: list[bool] = fenced_lines(lines)
        alive: list[bool] = self._surviving_lines(lines, fenced)
        kept: list[str] = [
            line if fenced[index] else links_to_text(line)
            for index, line in enumerate(lines)
            if alive[index]
        ]
        start: int = 0
        end: int = len(kept)
        while start < end and BLANK.match(kept[start]):
            start += 1
        while end > start and BLANK.match(kept[end - 1]):
            end -= 1
        return "\n".join(kept[start:end])

    def _surviving_lines(self, lines: list[str], fenced: list[bool]) -> list[bool]:
        """Step 2: drop every links-only section, bottom-up so a parent can follow its children."""
        alive: list[bool] = [True] * len(lines)
        levels: dict[int, int] = {
            index: level
            for index, line in enumerate(lines)
            if not fenced[index] and (level := heading_level(line)) is not None
        }
        for heading in sorted(levels, reverse=True):
            content: list[int] = []
            for index in range(heading + 1, len(lines)):
                if not alive[index]:
                    continue
                if index in levels and levels[index] <= levels[heading]:
                    break
                content.append(index)
            if all(
                not fenced[index] and index not in levels and is_link_only(lines[index])
                for index in content
            ):
                alive[heading] = False
                for index in content:
                    alive[index] = False
        return alive
