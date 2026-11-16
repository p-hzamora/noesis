"""Parse vault body links before the normaliser removes links-only sections."""

import re
from urllib.parse import unquote

from noesis.bounded_context.interop.domain.services.markdown_text import (
    LINK_TOKEN,
    fenced_lines,
    inline_spans,
)
from noesis.bounded_context.interop.domain.value_objects.vault_link import VaultLink

MARKDOWN_LINK: re.Pattern[str] = re.compile(
    r'\[[^\]]*\]\(\s*(<[^>\n]+>|[^)\s]+)(?:\s+"[^"]*")?\s*\)'
)


class LinkParser:
    """Extract wiki links, embeds and relative Markdown note links outside code."""

    def parse(self, body: str) -> tuple[VaultLink, ...]:
        """Return occurrences; anchors retain their block-marker caret."""
        links: list[VaultLink] = []
        lines: list[str] = body.splitlines()
        for line, fenced in zip(lines, fenced_lines(lines), strict=True):
            if fenced:
                continue
            for start, end in reversed(inline_spans(line)):
                line = line[:start] + " " * (end - start) + line[end:]
            for match in LINK_TOKEN.finditer(line):
                parts: list[str] = re.split(r"\\?\|", match.group(1), maxsplit=1)
                target, _, anchor = parts[0].strip().partition("#")
                links.append(
                    VaultLink(
                        target=target,
                        anchor=anchor,
                        alias=parts[1] if len(parts) > 1 else "",
                        embed=match.group().startswith("!"),
                    )
                )
            for match in MARKDOWN_LINK.finditer(line):
                url: str = unquote(match.group(1).removeprefix("<").removesuffix(">"))
                target, _, anchor = url.partition("#")
                if "://" in url or url.lower().startswith("mailto:"):
                    continue
                if not target.lower().endswith(".md"):
                    continue
                links.append(VaultLink(target=target, anchor=anchor, markdown=True))
        return tuple(links)
