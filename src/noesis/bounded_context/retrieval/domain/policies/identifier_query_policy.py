"""Whether a query names an identifier, so lexical order must win (Q-205, F-5)."""

import re

_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"`[^`\s][^`]*`"),  # a backtick-delimited token
    re.compile(r"(?<![\w-])--[A-Za-z][\w-]*"),  # a long flag: --require-semantic
    re.compile(r"\S+[/\\]\S+"),  # a path: src/noesis, C:\x
    re.compile(r"\b[A-Za-z_]\w+\.[A-Za-z_]\w+\b"),  # a dotted name or file extension
    re.compile(r"\b[a-z0-9]+(?:_[a-z0-9]+)+\b", re.IGNORECASE),  # snake_case
    re.compile(r"\b[a-z]+[A-Z][A-Za-z0-9]*\b"),  # camelCase
    re.compile(r"\b[A-Z][a-z0-9]+[A-Z][A-Za-z0-9]*\b"),  # PascalCase with an inner capital
    re.compile(
        r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.IGNORECASE
    ),  # a UUID
    re.compile(r"\b[A-Z][A-Z0-9]*-\d+\b"),  # an issue key: NOE-12, K-001
)


class IdentifierQueryPolicy:
    """Deterministic classifier: a query is identifier-like when one token predicate matches.

    The predicates: a backtick-delimited token, a `--flag`, a token holding a slash or a
    backslash (so `and/or` counts too), a dotted qualified name or file extension whose
    parts have two characters or more (`os.path`, `README.md`; not `e.g.`), snake_case, camelCase (or
    PascalCase with an inner capital), a UUID, or an uppercase key followed by `-<number>`.
    Prose with only sentence punctuation is not identifier-like.
    """

    def is_identifier(self, text: str) -> bool:
        """True when any token predicate matches `text`."""
        return any(pattern.search(text) for pattern in _PATTERNS)
