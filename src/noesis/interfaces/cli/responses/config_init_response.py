"""`noesis config init` output."""

from .i_renderable_response import IRenderableResponse


class ConfigInitResponse(IRenderableResponse):
    """`noesis config init`: what was written.

    Attributes:
        env_file: The file that was written.
        vault_dir: The vault folder written into it, if one was given.
    """

    env_file: str
    vault_dir: str | None

    def render(self) -> str:
        return f"wrote {self.env_file}"
