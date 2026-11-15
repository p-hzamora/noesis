"""An extra Source cited by a note's header."""

from noesis.shared_kernel.domain.value_objects import ValueObject


class HeaderSource(ValueObject):
    """One mappable entry of the header's `noesis.sources`.

    Attributes:
        kind: A Knowledge Source kind other than `file_version`.
        locator: Where to find it.
    """

    kind: str
    locator: str
