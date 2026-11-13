"""The manifest: sources, layout and kinds, and what is derived from them."""

from .group_spec import GroupMatch, GroupSpec
from .kind_catalog import KindCatalog
from .kind_spec import KindSpec
from .layout_spec import LayoutSpec
from .manifest import Manifest
from .manifest_merger import merge_manifest_data
from .note_path_resolver import NotePathResolver
from .source_spec import SourceRoleEnum, SourceSpec, SourceTypeEnum

__all__ = [
    "GroupMatch",
    "GroupSpec",
    "KindCatalog",
    "KindSpec",
    "LayoutSpec",
    "Manifest",
    "NotePathResolver",
    "SourceRoleEnum",
    "SourceSpec",
    "SourceTypeEnum",
    "merge_manifest_data",
]
