"""A reference to a catalog entry by kind and name (`kind:name`)."""

from noesis.bounded_context.knowledge.domain.value_objects.catalog_name import CatalogEntryName
from noesis.bounded_context.knowledge.domain.value_objects.enums import CatalogEntryKindEnum
from noesis.exceptions import InvalidCatalogNameError, InvalidCatalogPrerequisiteError
from noesis.shared_kernel.domain.value_objects import ValueObject


class CatalogRef(ValueObject):
    """The kind and name of a catalog entry; the text form is `kind:name`.

    Attributes:
        kind: Entry kind.
        name: Entry name.
    """

    kind: CatalogEntryKindEnum
    name: CatalogEntryName

    @classmethod
    def parse(cls, text: str) -> CatalogRef:
        """Parse `kind:name`, splitting on the first colon (kinds contain none).

        Raises:
            InvalidCatalogPrerequisiteError: No colon, an unknown kind, or an invalid name.
        """
        kind_text, separator, name_text = text.partition(":")
        problem: str = f"Invalid catalog reference {text!r}."
        hint: str = "Write it as <kind>:<name> with a kind of skill, agent, cli_tool or mcp_server."
        if not separator:
            raise InvalidCatalogPrerequisiteError(problem, {"ref": text}, next_steps=[hint])
        try:
            kind: CatalogEntryKindEnum = CatalogEntryKindEnum(kind_text)
            name: CatalogEntryName = CatalogEntryName(value=name_text)
        except (ValueError, InvalidCatalogNameError) as error:
            raise InvalidCatalogPrerequisiteError(
                problem, {"ref": text}, next_steps=[hint]
            ) from error
        return cls(kind=kind, name=name)

    def as_text(self) -> str:
        """`kind:name`."""
        return f"{self.kind.value}:{self.name.value}"

    def __str__(self) -> str:
        return self.as_text()
