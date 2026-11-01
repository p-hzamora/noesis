"""The contract of every command output: one object for both JSON and text."""

from abc import ABC, abstractmethod

from noesis.utils import FrozenObject


class IRenderableResponse(FrozenObject, ABC):
    """A command response that knows its human-readable form.

    With `--json` the object is serialised as the envelope's `result`; without it, `render()`
    produces the text. Both views come from the same object, so they cannot drift apart.
    `render()` is a method, not a field: it never appears in the JSON contract.
    """

    @abstractmethod
    def render(self) -> str:
        """Text for people; may change between releases (automation reads `--json`)."""
