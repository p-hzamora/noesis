"""Which header values are valid tags (a copy of Knowledge's `Tag` rule; a unit test checks parity)."""

import re

TAG_PART: re.Pattern[str] = re.compile(r"^\.?[a-z0-9]+(?:[-_][a-z0-9]+)*$")
MAX_SLUG_LENGTH: int = 64
FACET_SEPARATOR: str = ":"


class TagRule:
    """Normalises a tag value and says whether it is acceptable."""

    def normalise(self, value: str) -> str:
        """Trimmed and lowercased, as Knowledge stores it."""
        return value.strip().lower()

    def is_valid(self, value: str) -> bool:
        """Whether the normalised `value` is `name` or `facet:name`, each part a tag part."""
        normalised: str = self.normalise(value)
        parts: list[str] = (
            list(normalised.partition(FACET_SEPARATOR)[::2])
            if FACET_SEPARATOR in normalised
            else [normalised]
        )
        return all(len(part) <= MAX_SLUG_LENGTH and TAG_PART.fullmatch(part) for part in parts)
