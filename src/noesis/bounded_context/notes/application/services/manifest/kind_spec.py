"""One kind of note, as the manifest declares it."""

from pydantic import Field

from noesis.utils import FrozenObject


class KindSpec(FrozenObject):
    """Everything noesis knows about a kind; nothing about kinds lives in code.

    Attributes:
        name: Kind name written in frontmatter.
        folder: Folder name `{kind_folder}` expands to.
        description: What belongs in a note of this kind; fed to the curator.
        sections: Headings every note of this kind has, in order.
        recall_weight: Multiplier of the recall score, in (0, 1].
    """

    name: str
    folder: str
    description: str = ""
    sections: tuple[str, ...] = ()
    recall_weight: float = Field(default=0.8, gt=0, le=1)
