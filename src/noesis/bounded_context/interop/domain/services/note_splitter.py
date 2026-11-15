"""Step 0: decode a note's bytes and split the header from the body."""

import re

from noesis.bounded_context.interop.domain.value_objects import NoteBlockReasonEnum, SplitNote

BOM: str = "﻿"
HEADER_FENCE: str = "---"
HEADER_CLOSE: re.Pattern[str] = re.compile(r"^---[ \t]*$")


class NoteSplitter:
    """Strict UTF-8, LF newlines, then the exact header rule."""

    def split(self, data: bytes) -> SplitNote:
        """Decode and split `data`; a failure is reported in the result, never raised."""
        try:
            text: str = data.decode("utf-8")
        except UnicodeDecodeError:
            return SplitNote(failure=NoteBlockReasonEnum.NOT_TEXT)
        text = text.removeprefix(BOM).replace("\r\n", "\n").replace("\r", "\n")
        lines: list[str] = text.split("\n")
        if lines[0] != HEADER_FENCE:
            return SplitNote(body=text)
        for index in range(1, len(lines)):
            if HEADER_CLOSE.match(lines[index]):
                return SplitNote(
                    header_text="\n".join(lines[1:index]), body="\n".join(lines[index + 1 :])
                )
        return SplitNote(failure=NoteBlockReasonEnum.INVALID_HEADER)
