"""Knowledge repository ports."""

from .i_experience_repository import IExperienceRepository
from .i_knowledge_repository import IKnowledgeRepository
from .i_knowledge_space_repository import IKnowledgeSpaceRepository
from .i_project_repository import IProjectRepository
from .i_source_repository import ISourceRepository

__all__ = [
    "IExperienceRepository",
    "IKnowledgeRepository",
    "IKnowledgeSpaceRepository",
    "IProjectRepository",
    "ISourceRepository",
]
