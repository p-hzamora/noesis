"""Who authored a revision or an experience."""

from pydantic import field_validator

from noesis.bounded_context.knowledge.domain.value_objects.enums import ActorKindEnum
from noesis.exceptions import InvalidRecordError
from noesis.shared_kernel.domain.value_objects import ValueObject


class Actor(ValueObject):
    """A user or an agent, with a name and, for agents, the session it ran in.

    Attributes:
        kind: `user` or `agent`.
        name: Display name; not blank.
        session: Harness session id, when known.
    """

    kind: ActorKindEnum
    name: str
    session: str | None = None

    @field_validator("name")
    @classmethod
    def _named(cls, value: str) -> str:
        stripped: str = value.strip()
        if not stripped:
            raise InvalidRecordError("An actor needs a name.", next_steps=["Provide a name."])
        return stripped
