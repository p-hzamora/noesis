"""`noesis config show` output."""

from noesis.shared_kernel.domain import JsonObject

from .i_renderable_response import IRenderableResponse


class ConfigShowResponse(IRenderableResponse):
    """`noesis config show`: the effective configuration of this invocation.

    Attributes:
        env_file: The `.env` file that was read.
        env_file_exists: Whether that file exists.
        settings: Every setting, grouped by concern.
    """

    env_file: str
    env_file_exists: bool
    settings: JsonObject

    def render(self) -> str:
        lines: list[str] = [
            f"env file: {self.env_file} ({'found' if self.env_file_exists else 'missing'})"
        ]
        for concern, values in self.settings.items():
            lines.append(f"[{concern}]")
            if isinstance(values, dict):
                lines += [f"  {key} = {value}" for key, value in values.items()]
        return "\n".join(lines)
