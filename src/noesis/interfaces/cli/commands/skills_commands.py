"""`noesis skills`: version-matched guides that installed agent skills load at run time."""

from importlib.resources import files
from importlib.resources.abc import Traversable
from typing import Annotated

import typer

from noesis.exceptions import (
    SkillGuideNotFoundError,
)
from noesis.interfaces.cli import output
from noesis.interfaces.cli.options import JsonOption
from noesis.interfaces.cli.responses import SkillGuideListResponse, SkillGuideResponse
from noesis.shared_kernel.domain import (
    JsonValue,
)

GUIDES_PACKAGE: str = "noesis.interfaces.cli.skill_guides"
GUIDE_SUFFIX: str = ".md"

skills_app: typer.Typer = typer.Typer(
    help="Guides for agent skills; the installed skill stub runs `noesis skills get noesis`.",
    no_args_is_help=True,
)


def _guides() -> dict[str, Traversable]:
    return {
        item.name.removesuffix(GUIDE_SUFFIX): item
        for item in files(GUIDES_PACKAGE).iterdir()
        if item.name.endswith(GUIDE_SUFFIX)
    }


def _title(content: str) -> str:
    return next(
        (line.lstrip("# ").strip() for line in content.splitlines() if line.startswith("#")), ""
    )


@skills_app.command("list")
def list_guides(as_json: JsonOption = False) -> None:
    """List the guides this noesis version ships."""
    guides: tuple[SkillGuideResponse, ...] = tuple(
        SkillGuideResponse(name=name, title=_title(item.read_text(encoding="utf-8")))
        for name, item in sorted(_guides().items())
    )
    output.emit(
        SkillGuideListResponse(guides=guides),
        lambda r: "\n".join(f"{g.name}  {g.title}" for g in r.guides),
    )


@skills_app.command("get")
def get_guide(
    name: Annotated[str, typer.Argument(help="Guide name, e.g. `noesis`.")],
    as_json: JsonOption = False,
) -> None:
    """Print a guide (what an agent reads before using noesis)."""
    guides: dict[str, Traversable] = _guides()
    if name not in guides:
        available: list[JsonValue] = []
        available.extend(sorted(guides))  # list[str] is not a list[JsonValue]; extend is covariant
        raise SkillGuideNotFoundError(
            f"No guide named {name!r}.",
            {"available": available},
            next_steps=["Run `noesis skills list`."],
        )
    content: str = guides[name].read_text(encoding="utf-8")
    output.emit(
        SkillGuideResponse(name=name, title=_title(content), content=content),
        lambda guide: guide.content,
    )
