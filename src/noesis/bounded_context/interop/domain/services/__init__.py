"""Interop domain services: pure rules over note text and headers."""

from .header_source_rule import HeaderSourceResult, HeaderSourceRule
from .note_mapper import NoteMapper
from .note_splitter import NoteSplitter
from .tag_rule import TagRule
from .text_normaliser import TextNormaliser
from .title_rule import TitleRule

__all__ = [
    "HeaderSourceResult",
    "HeaderSourceRule",
    "NoteMapper",
    "NoteSplitter",
    "TagRule",
    "TextNormaliser",
    "TitleRule",
]
