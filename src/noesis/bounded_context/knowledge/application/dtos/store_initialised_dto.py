"""Result of initialising the store."""

from noesis.shared_kernel.application.dtos import BaseDto


class SpaceDto(BaseDto):
    """A knowledge space.

    Attributes:
        id: Space id.
        key: Space key.
        name: Display name.
        created: True when this call created it.
    """

    id: str
    key: str
    name: str
    created: bool


class StoreInitialisedDto(BaseDto):
    """What `store init` did.

    Attributes:
        applied_steps: Steps this call applied.
        already_applied_steps: Steps that were applied before.
        default_space: The configured default space.
    """

    applied_steps: tuple[str, ...]
    already_applied_steps: tuple[str, ...]
    default_space: SpaceDto
