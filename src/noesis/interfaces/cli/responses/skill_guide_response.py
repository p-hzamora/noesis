"""`noesis skills` output."""

from .i_renderable_response import IRenderableResponse


class SkillGuideResponse(IRenderableResponse):
    """`noesis skills get`: one packaged guide (also an entry of the listing).

    Attributes:
        name: Guide name (what `skills get` takes).
        title: First heading of the guide.
        content: Full Markdown (empty in listings).
    """

    name: str
    title: str
    content: str = ""

    def render(self) -> str:
        return self.content


class SkillGuideListResponse(IRenderableResponse):
    """`noesis skills list`: every packaged guide.

    Attributes:
        guides: The guides, by name.
    """

    guides: tuple[SkillGuideResponse, ...]

    def render(self) -> str:
        return "\n".join(f"{guide.name}  {guide.title}" for guide in self.guides)
