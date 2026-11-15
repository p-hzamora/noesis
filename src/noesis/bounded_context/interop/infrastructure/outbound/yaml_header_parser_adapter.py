"""`IHeaderParser` over YAML with the safe loader."""

from collections.abc import Mapping

import yaml

from noesis.bounded_context.interop.application.ports import IHeaderParser


class YamlHeaderParserAdapter(IHeaderParser):
    """A header that does not parse, or is not a mapping, is reported as None."""

    def parse(self, text: str) -> Mapping[str, object] | None:
        """The header mapping; empty for an empty header."""
        try:
            loaded: object = yaml.safe_load(text)
        except yaml.YAMLError:
            return None
        if loaded is None:
            return {}
        if not isinstance(loaded, dict):
            return None
        return {str(key): value for key, value in loaded.items()}
