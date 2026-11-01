"""`noesis config show` output."""

from noesis.shared_kernel.domain import JsonObject
from noesis.utils import FrozenObject


class ConfigShowResponse(FrozenObject):
    """`noesis config show`: the effective configuration of this invocation.

    Attributes:
        env_file: The `.env` file that was read.
        env_file_exists: Whether that file exists.
        settings: Every setting, grouped by concern.
    """

    env_file: str
    env_file_exists: bool
    settings: JsonObject
