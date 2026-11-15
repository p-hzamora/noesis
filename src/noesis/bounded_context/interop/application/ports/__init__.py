"""Outbound ports of interop."""

from .i_file_reader import IFileReader
from .i_header_parser import IHeaderParser
from .i_knowledge_importer import IKnowledgeImporter
from .i_vault_reader import IVaultReader

__all__ = ["IFileReader", "IHeaderParser", "IKnowledgeImporter", "IVaultReader"]
