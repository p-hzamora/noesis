"""Keeps Obsidian wikilinks pointing at the same files after files move.

Resolution follows Obsidian: a target is a full path, or a path suffix, or a bare file name,
with or without `.md`. A link is rewritten only when it resolved to a moved file before the
move and would not resolve to that same file after it; it is then written as the new full path.
"""

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import PurePosixPath

LINK_PATTERN: re.Pattern[str] = re.compile(
    r"\[\[(?P<target>[^\[\]|#\n]+?)(?P<heading>#[^\[\]|\n]*)?(?P<alias>\\?\|[^\[\]\n]*)?\]\]"
)
NOTE_SUFFIX: str = ".md"


@dataclass(slots=True)
class _Index:
    """Files of one tree, found by exact path and by trailing path segments."""

    files: frozenset[str]
    by_tail: dict[str, list[str]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for path in self.files:
            parts: list[str] = path.split("/")
            for start in range(len(parts)):
                tail: str = "/".join(parts[start:]).casefold()
                self.by_tail.setdefault(tail, []).append(path)
                if path.endswith(NOTE_SUFFIX):
                    self.by_tail.setdefault(tail.removesuffix(NOTE_SUFFIX), []).append(path)

    def find(self, target: str) -> list[str]:
        """Files `target` can mean, exact path first; more than one means ambiguous."""
        key: str = target.strip().strip("/").casefold()
        if target.strip().strip("/") in self.files:
            return [target.strip().strip("/")]
        if f"{target.strip().strip('/')}{NOTE_SUFFIX}" in self.files:
            return [f"{target.strip().strip('/')}{NOTE_SUFFIX}"]
        return sorted(set(self.by_tail.get(key, [])))


class WikilinkRewriter:
    """Rewrites and counts wikilinks for one plan, independent of how far it has been applied.

    Args:
        moves: Old path -> new path of every file that relocates.
        present: Every path involved: files in the vault now, plus every old and new path of
            the plan. The tree before the move drops the new paths; after it, the old ones.
    """

    def __init__(self, moves: Mapping[str, str], present: Iterable[str]) -> None:
        self._moves: dict[str, str] = dict(moves)
        everything: set[str] = set(present) | set(moves) | set(moves.values())
        pre_existing: set[str] = everything - {n for o, n in moves.items() if o != n}
        self._now: _Index = _Index(frozenset(present))
        self._before: _Index = _Index(frozenset(pre_existing))
        self._after: _Index = _Index(frozenset(everything - set(moves)))

    def rewrite(self, text: str) -> tuple[str, int]:
        """`text` with its stale links updated, and how many were."""
        changed: int = 0

        def replace(match: re.Match[str]) -> str:
            nonlocal changed
            replacement: str | None = self._new_target(match.group("target"))
            if replacement is None:
                return match.group(0)
            changed += 1
            return f"[[{replacement}{match.group('heading') or ''}{match.group('alias') or ''}]]"

        return LINK_PATTERN.sub(replace, text), changed

    def count_unresolved(self, text: str, *, after: bool) -> int:
        """Links of `text` whose target is no file: of the tree as it is now, or once the plan is done."""
        index: _Index = self._after if after else self._now
        return sum(1 for m in LINK_PATTERN.finditer(text) if not index.find(m.group("target")))

    def _new_target(self, target: str) -> str | None:
        hits: list[str] = self._before.find(target)
        if len(hits) != 1 or hits[0] not in self._moves:
            return None
        moved: str = self._moves[hits[0]]
        if self._after.find(target) == [moved]:
            return None
        return (
            moved.removesuffix(NOTE_SUFFIX) if PurePosixPath(moved).suffix == NOTE_SUFFIX else moved
        )
