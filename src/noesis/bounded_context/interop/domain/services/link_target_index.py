"""Pure, case-insensitive Obsidian path resolution over the scanned notes."""

import unicodedata
from pathlib import PurePosixPath

from noesis.bounded_context.interop.domain.value_objects.vault_link import ResolvedLink, VaultLink


def _fold(path: str) -> str:
    return unicodedata.normalize("NFC", path).casefold()


def _note(path: str) -> str:
    return path if path.endswith(".md") else f"{path}.md"


def _relative(source: str, target: str) -> str | None:
    parts: list[str] = source.split("/")[:-1]
    if target.startswith("/"):
        return None
    for part in target.split("/"):
        if part == "..":
            if not parts:
                return None
            parts.pop()
        elif part not in {"", "."}:
            parts.append(part)
    return "/".join(parts)


class LinkTargetIndex:
    """Resolve against paths only; header aliases never participate."""

    def __init__(self, paths: list[str]) -> None:
        self._paths: tuple[str, ...] = tuple(sorted(paths))
        self._exact: dict[str, list[str]] = {}
        self._bases: dict[str, list[str]] = {}
        for path in self._paths:
            folded: str = _fold(path)
            self._exact.setdefault(folded, []).append(path)
            self._bases.setdefault(folded.rsplit("/", 1)[-1], []).append(path)

    def resolve(self, link: VaultLink, *, source: str) -> ResolvedLink:
        """Classify one occurrence, never escaping the vault root or guessing ties."""
        target: str = _fold(link.target)
        candidates: list[str] = []
        if not target:
            return ResolvedLink(link=link, classification="self")
        relative: bool = link.markdown or target.startswith(("./", "../"))
        if relative:
            path: str | None = _relative(_fold(source), target)
            candidates = self._exact.get(_note(path), []) if path is not None else []
        elif "/" in target:
            candidates = self._exact.get(_note(target), [])
            if not candidates:
                candidates = [p for p in self._paths if _fold(p).endswith(f"/{_note(target)}")]
        else:
            candidates = self._bases.get(_note(target), [])
            if len(candidates) > 1:
                folder: str = _fold(str(PurePosixPath(source).parent))
                nearby: list[str] = [
                    p for p in candidates if _fold(str(PurePosixPath(p).parent)) == folder
                ]
                if len(nearby) == 1:
                    candidates = nearby
        if len(candidates) == 1:
            return ResolvedLink(
                link=link,
                classification="self" if candidates[0] == source else "resolved",
                path=candidates[0],
            )
        if candidates:
            return ResolvedLink(
                link=link, classification="ambiguous", candidates=tuple(sorted(candidates))
            )
        extension: str = PurePosixPath(target).suffix
        return ResolvedLink(
            link=link,
            classification="non_note"
            if not relative and extension and extension != ".md"
            else "dangling",
        )
