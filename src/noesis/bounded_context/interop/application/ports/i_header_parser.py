"""Parses the text of a note header."""

import abc
from collections.abc import Mapping


class IHeaderParser(abc.ABC):
    """Turns header text into a mapping with a safe parser."""

    @abc.abstractmethod
    def parse(self, text: str) -> Mapping[str, object] | None:
        """The header as a mapping (empty for an empty header); None when it cannot be parsed
        or is not a mapping."""
        ...
