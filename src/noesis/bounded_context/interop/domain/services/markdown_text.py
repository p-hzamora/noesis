"""Line-level Markdown analysis shared by the normaliser and the title rule.

Code regions (fenced blocks and inline spans) are never searched for links or headings.
"""

import re

FENCE_OPEN: re.Pattern[str] = re.compile(r"^ {0,3}(`{3,}|~{3,})")
HEADING: re.Pattern[str] = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]+.*)?$")
LINK_TOKEN: re.Pattern[str] = re.compile(r"!?\[\[([^\[\]\n]+)\]\]")
BACKTICK_RUN: re.Pattern[str] = re.compile(r"`+")
BLANK: re.Pattern[str] = re.compile(r"^[ \t]*$")
LINK_ONLY_REMAINDER: re.Pattern[str] = re.compile(
    r"^[ \t]*(?:(?:[-*+]|[0-9]{1,9}[.)])(?:[ \t]+|$))?[ \t,;·|]*$"
)
ESCAPED_PIPE: str = "\\|"
MARKDOWN_SUFFIX: str = ".md"


def fenced_lines(lines: list[str]) -> list[bool]:
    """For each line, whether it is part of a fenced block (opening and closing lines included)."""
    flags: list[bool] = []
    closing: re.Pattern[str] | None = None
    for line in lines:
        if closing is None:
            opening: re.Match[str] | None = FENCE_OPEN.match(line)
            if opening is None:
                flags.append(False)
                continue
            fence: str = opening.group(1)
            closing = re.compile(rf"^ {{0,3}}{re.escape(fence[0])}{{{len(fence)},}}[ \t]*$")
            flags.append(True)
        else:
            flags.append(True)
            if closing.match(line):
                closing = None
    return flags


def inline_spans(line: str) -> list[tuple[int, int]]:
    """Ranges `[start, end)` of the inline code spans of `line`."""
    spans: list[tuple[int, int]] = []
    runs: list[re.Match[str]] = list(BACKTICK_RUN.finditer(line))
    index: int = 0
    while index < len(runs):
        size: int = len(runs[index].group())
        partner: int | None = next(
            (later for later in range(index + 1, len(runs)) if len(runs[later].group()) == size),
            None,
        )
        if partner is None:
            index += 1
            continue
        spans.append((runs[index].start(), runs[partner].end()))
        index = partner + 1
    return spans


def _link_text(inner: str) -> str:
    """The text a link token stands for (step 1)."""
    if ESCAPED_PIPE in inner:
        target, _, alias = inner.partition(ESCAPED_PIPE)
    else:
        target, _, alias = inner.partition("|")
    if alias.strip():
        return alias.strip()
    path, _, suffix = target.partition("#")
    if path.strip():
        segment: str = path.split("/")[-1]
        if segment.lower().endswith(MARKDOWN_SUFFIX):
            segment = segment[: -len(MARKDOWN_SUFFIX)]
        return segment.strip()
    return "" if suffix.startswith("^") else suffix.strip()


def _outside_spans(line: str) -> list[tuple[str, bool]]:
    """`line` cut into `(text, is_code)` pieces."""
    pieces: list[tuple[str, bool]] = []
    position: int = 0
    for start, end in inline_spans(line):
        pieces.append((line[position:start], False))
        pieces.append((line[start:end], True))
        position = end
    pieces.append((line[position:], False))
    return pieces


def links_to_text(line: str) -> str:
    """`line` with every link token outside inline code replaced by its text."""
    return "".join(
        text if is_code else LINK_TOKEN.sub(lambda match: _link_text(match.group(1)), text)
        for text, is_code in _outside_spans(line)
    )


def without_links(line: str) -> tuple[str, int]:
    """`line` with every link token outside inline code deleted, and the number deleted."""
    kept: list[str] = []
    count: int = 0
    for text, is_code in _outside_spans(line):
        if is_code:
            kept.append(text)
            continue
        remainder, number = LINK_TOKEN.subn("", text)
        kept.append(remainder)
        count += number
    return "".join(kept), count


def is_link_only(line: str) -> bool:
    """Whether a line outside code is blank or holds only link tokens and separators."""
    if BLANK.match(line):
        return True
    remainder, count = without_links(line)
    return count > 0 and LINK_ONLY_REMAINDER.match(remainder) is not None


def heading_level(line: str) -> int | None:
    """The level of an ATX heading line, or None."""
    match: re.Match[str] | None = HEADING.match(line)
    return len(match.group(1)) if match else None
