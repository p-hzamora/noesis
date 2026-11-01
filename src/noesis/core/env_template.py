"""The documented `.env` template every noesis configuration starts from.

The single source is `.env.example` at the repository root. Wheels carry a copy inside this
package (hatch `force-include`, see pyproject.toml); a source checkout reads the root file.
"""

from importlib.resources import files
from importlib.resources.abc import Traversable
from pathlib import Path

from noesis.exceptions import (
    ConfigTemplateMissingError,
)

PACKAGED_NAME: str = "env.example"
SOURCE_NAME: str = ".env.example"
REPOSITORY_ROOT: Path = Path(__file__).resolve().parents[3]  # core/noesis/src/<root>
VAULT_LINE_PREFIX: str = "NOESIS_VAULT_DIR="


def env_example_text() -> str:
    """The template's text, from the installed package or the source tree.

    Raises:
        ConfigTemplateMissingError: Neither copy exists (a broken installation).
    """
    packaged: Traversable = files("noesis.core").joinpath(PACKAGED_NAME)
    candidates: tuple[Traversable | Path, ...] = (packaged, REPOSITORY_ROOT / SOURCE_NAME)
    for candidate in candidates:
        if candidate.is_file():
            return candidate.read_text(encoding="utf-8")
    raise ConfigTemplateMissingError(
        "The configuration template `.env.example` is missing from this installation.",
        next_steps=["Reinstall noesis (`uv tool install --force <repo>`)."],
    )


def write_env_file(target: Path, *, vault_dir: Path | None = None) -> None:
    """Write the commented configuration template to `target`.

    Args:
        target: Destination `.env` file; missing parent folders are created. An existing file
            is replaced, so callers decide whether that is allowed.
        vault_dir: Value to write into the `NOESIS_VAULT_DIR` line, when given.

    Raises:
        ConfigTemplateMissingError: The template is missing from this installation.
    """
    template: str = env_example_text()
    if vault_dir is not None:
        template = (
            "\n".join(
                f"{VAULT_LINE_PREFIX}{vault_dir}" if line.startswith(VAULT_LINE_PREFIX) else line
                for line in template.splitlines()
            )
            + "\n"
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(template, encoding="utf-8")
