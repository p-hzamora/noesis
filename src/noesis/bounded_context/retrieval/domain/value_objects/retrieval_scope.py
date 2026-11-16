"""Which records of a space a search may return."""

from collections.abc import Collection

from noesis.shared_kernel.domain.value_objects import ValueObject

from ..enums import ProjectScopeEnum


class RetrievalScope(ValueObject):
    """The space, the project rule and the required tags of one search.

    A scope narrows results; it is not access control.

    Attributes:
        space_id: The active space; records of any other space are never admitted.
        project_id: The resolved project, else null.
        all_projects: Admit records of every project.
        tags: Labels a record must all carry.
    """

    space_id: str
    project_id: str | None = None
    all_projects: bool = False
    tags: tuple[str, ...] = ()

    @property
    def kind(self) -> ProjectScopeEnum:
        """`all_projects`, `project`, or `space_wide_only` when no project resolved."""
        if self.all_projects:
            return ProjectScopeEnum.ALL_PROJECTS
        if self.project_id is not None:
            return ProjectScopeEnum.PROJECT
        return ProjectScopeEnum.SPACE_WIDE_ONLY

    def admits(self, *, project_id: str | None, tags: Collection[str]) -> bool:
        """Whether a record of this project and with these tags is inside the scope."""
        if not self.all_projects and project_id is not None and project_id != self.project_id:
            return False
        return all(tag in tags for tag in self.tags)
