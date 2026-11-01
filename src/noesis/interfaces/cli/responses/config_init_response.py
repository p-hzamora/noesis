"""`noesis config init` output."""

from noesis.utils import FrozenObject


class ConfigInitResponse(FrozenObject):
    """`noesis config init`: what was written.

    Attributes:
        env_file: The file that was written.
        vault_dir: The vault folder written into it, if one was given.
    """

    env_file: str
    vault_dir: str | None
