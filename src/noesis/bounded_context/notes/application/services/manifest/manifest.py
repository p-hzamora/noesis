"""The `noesis.yaml` manifest as the application sees it, validated."""

from collections import Counter
from typing import Self

from pydantic import ConfigDict, Field, model_validator

from noesis.exceptions import InvalidManifestError
from noesis.shared_kernel.domain import JsonValue
from noesis.utils import FrozenObject

from .group_spec import GroupSpec, check_group_name
from .kind_catalog import KindCatalog
from .kind_spec import KindSpec
from .layout_spec import LayoutSpec
from .source_spec import SourceRoleEnum, SourceSpec, SourceTypeEnum


def _duplicates(names: list[str]) -> list[str]:
    return sorted(name for name, count in Counter(names).items() if count > 1)


class Manifest(FrozenObject):
    """Sources, layout and kinds. Exactly one source is primary.

    Attributes:
        sources: Where notes are read from; exactly one has role `primary`.
        layout: Where new notes go.
        kinds: The kinds of notes that exist.
        groups: Extra roots for the notes of some repositories, by group name.
    """

    model_config = ConfigDict(extra="forbid")

    sources: tuple[SourceSpec, ...]
    layout: LayoutSpec
    kinds: tuple[KindSpec, ...]
    groups: dict[str, GroupSpec] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        primaries: list[SourceSpec] = [s for s in self.sources if s.role is SourceRoleEnum.PRIMARY]
        if len(primaries) != 1:
            raise InvalidManifestError(
                f"The manifest needs exactly one primary source, found {len(primaries)}.",
                {"primary": [source.name for source in primaries]},
                next_steps=["Give exactly one entry of `sources` the role `primary`."],
            )
        if primaries[0].type is SourceTypeEnum.VECTOR:
            raise InvalidManifestError(
                "A vector source cannot be the primary: it is derived and read-only.",
                {"source": primaries[0].name},
            )
        for what, names in (
            ("source", [s.name for s in self.sources]),
            ("kind", [k.name for k in self.kinds]),
            ("kind folder", [k.folder for k in self.kinds]),
        ):
            if repeated := _duplicates(names):
                raise InvalidManifestError(
                    f"The manifest repeats {what} names: {', '.join(repeated)}.",
                    {"duplicates": list[JsonValue](repeated)},
                )
        for name in self.groups:
            check_group_name(name)
        return self

    def primary(self) -> SourceSpec:
        """The one source new notes are written to."""
        return next(s for s in self.sources if s.role is SourceRoleEnum.PRIMARY)

    def catalog(self) -> KindCatalog:
        """The validated kind catalog."""
        return KindCatalog(kinds=self.kinds)
