"""`noesis skills` output."""

from noesis.utils import FrozenObject


class SkillGuideResponse(FrozenObject):
    """`noesis skills get`: one packaged guide (also an entry of the listing).

    Attributes:
        name: Guide name (what `skills get` takes).
        title: First heading of the guide.
        content: Full Markdown (empty in listings).
    """

    name: str
    title: str
    content: str = ""


class SkillGuideListResponse(FrozenObject):
    """`noesis skills list`: every packaged guide.

    Attributes:
        guides: The guides, by name.
    """

    guides: tuple[SkillGuideResponse, ...]
