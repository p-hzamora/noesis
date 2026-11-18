"""Architecture guard: only the link repository writes imported graph edges."""

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit


def test_only_link_repository_mentions_imported_relationship_types() -> None:
    root = (
        Path(__file__).parents[3]
        / "src/noesis/bounded_context/knowledge/infrastructure/outbound/persistence"
    )
    offenders = [
        str(path.relative_to(root))
        for path in root.rglob("*.py")
        if path.name != "neo4j_link_set_repository_adapter.py"
        and any(token in path.read_text() for token in ("LINKS_TO", "EMBEDS", "RELATES_TO"))
    ]
    assert offenders == []


def test_interop_contracts_are_confined_to_port_and_translator() -> None:
    root = Path(__file__).parents[3] / "src/noesis/bounded_context/interop"
    offenders = [
        str(path.relative_to(root))
        for path in root.rglob("*.py")
        if path.name not in {"i_knowledge_importer.py", "knowledge_import_translator.py"}
        and "noesis.shared_kernel.contracts" in path.read_text()
    ]
    assert offenders == []
