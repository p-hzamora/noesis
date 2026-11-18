"""Pure resolution of `<repo>--<kind>--<slug>` vault ids to note paths."""

import unicodedata

from noesis.bounded_context.interop.domain.value_objects.vault_relation import RelationResolution

SEPARATOR: str = "--"


def _fold(text: str) -> str:
    return unicodedata.normalize("NFC", text).casefold()


def _stem(path: str) -> str:
    name: str = path.rsplit("/", 1)[-1]
    return name.removesuffix(".md") if name.endswith(".md") else name


class RelationTargetIndex:
    """Slug under `repos/<repo>/` first; the same slug elsewhere only when unique vault-wide."""

    def __init__(self, paths: list[str]) -> None:
        self._by_stem: dict[str, list[str]] = {}
        for path in sorted(paths):
            self._by_stem.setdefault(_fold(_stem(path)), []).append(path)

    def resolve(self, target_key: str) -> RelationResolution:
        """Classify one vault id; ties are never guessed and nothing is created."""
        repo, _, rest = target_key.partition(SEPARATOR)
        _, separator, slug = rest.partition(SEPARATOR)
        repo, slug = repo.strip(), slug.strip()
        if not separator or not repo or not slug:
            return RelationResolution(classification="invalid_relation")
        matches: list[str] = self._by_stem.get(_fold(slug), [])
        folder: str = f"/repos/{_fold(repo)}/"
        inside: list[str] = [path for path in matches if folder in f"/{_fold(path)}"]
        for candidates in (inside, matches):
            if len(candidates) == 1:
                return RelationResolution(classification="resolved", path=candidates[0])
            if candidates:
                return RelationResolution(classification="ambiguous", candidates=tuple(candidates))
        return RelationResolution(classification="dangling")
