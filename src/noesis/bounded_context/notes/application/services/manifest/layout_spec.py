"""Path templates that choose where NEW notes go; reading never uses them."""

from pydantic import field_validator

from noesis.bounded_context.notes.domain.value_objects import NoteScopeTypeEnum
from noesis.exceptions import InvalidManifestError
from noesis.utils import FrozenObject


class LayoutSpec(FrozenObject):
    """One template per scope type; `{name}`, `{kind_folder}` and `{slug}` are substituted.

    Attributes:
        repo: Template for the notes of a repository.
        topic: Template for the notes of a learning topic.
    """

    repo: str
    topic: str

    @field_validator("repo", "topic")
    @classmethod
    def _valid_template(cls, template: str) -> str:
        if "{slug}" not in template or not template.endswith(".md") or template.startswith("/"):
            raise InvalidManifestError(
                f"Invalid layout template {template!r}.",
                {"template": template},
                next_steps=["Use a relative template ending in `{slug}.md`."],
            )
        return template

    def template_for(self, scope_type: NoteScopeTypeEnum) -> str:
        """The template of `scope_type`."""
        return self.repo if scope_type is NoteScopeTypeEnum.REPO else self.topic
