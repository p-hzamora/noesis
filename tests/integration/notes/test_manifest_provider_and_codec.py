"""The YAML manifest provider (packaged default + user file) and the frontmatter codec."""

from datetime import date
from pathlib import Path

import pytest

from noesis.bounded_context.notes.domain.value_objects import (
    NoteFrontmatter,
    NoteId,
    NoteKind,
    NoteOriginEnum,
    NoteScope,
    NoteSourceRef,
)
from noesis.bounded_context.notes.infrastructure.outbound.frontmatter import (
    YamlFrontmatterCodecAdapter,
)
from noesis.bounded_context.notes.infrastructure.outbound.manifest import (
    YamlManifestProviderAdapter,
)
from noesis.exceptions import InvalidManifestError

pytestmark = pytest.mark.integration

ULID: str = "01ARZ3NDEKTSV4RRFFQ69G5FAV"


async def test_packaged_default_is_the_single_source_of_kind_knowledge(tmp_path: Path) -> None:
    manifest = await YamlManifestProviderAdapter(tmp_path).load()
    catalog = manifest.catalog()
    assert catalog.names() == (
        "decision", "gotcha", "howto", "concept", "run", "glossary", "drift", "dependency",
    )  # fmt: skip
    assert catalog.recall_weights() == {
        "decision": 1.0, "gotcha": 1.0, "howto": 0.8, "concept": 0.8, "run": 0.6, "glossary": 0.8,
        "drift": 0.8, "dependency": 0.6,
    }  # fmt: skip
    decision = catalog.require(NoteKind(value="decision"))
    assert decision.folder == "decisions" and decision.description
    assert decision.sections == ("Decision", "Rationale", "Consequences", "Alternatives rejected")
    assert manifest.layout.repo == "repos/{name}/{kind_folder}/{slug}.md"
    assert manifest.layout.topic == "learning/{name}/{kind_folder}/{slug}.md"
    assert [s.name for s in manifest.sources] == ["vault"]


async def test_user_noesis_yaml_at_the_source_root_is_merged_on_the_default(tmp_path: Path) -> None:
    (tmp_path / "noesis.yaml").write_text(
        "kinds:\n"
        "  - {name: decision, folder: adr, description: Architecture decisions}\n"
        "  - {name: recipe, folder: recipes, description: Cooking}\n"
        "layout:\n  topic: 'topics/{name}/{slug}.md'\n",
        encoding="utf-8",
    )
    manifest = await YamlManifestProviderAdapter(tmp_path).load()
    catalog = manifest.catalog()
    assert catalog.names() == (
        "decision",
        "gotcha",
        "howto",
        "concept",
        "run",
        "glossary",
        "drift",
        "dependency",
        "recipe",
    )
    assert catalog.require(NoteKind(value="decision")).folder == "adr"
    assert manifest.layout.topic == "topics/{name}/{slug}.md"
    assert manifest.layout.repo == "repos/{name}/{kind_folder}/{slug}.md"


async def test_a_user_manifest_with_two_primaries_is_refused(tmp_path: Path) -> None:
    (tmp_path / "noesis.yaml").write_text(
        "sources:\n"
        "  - {name: a, type: filesystem, path: /a, role: primary}\n"
        "  - {name: b, type: filesystem, path: /b, role: primary}\n",
        encoding="utf-8",
    )
    with pytest.raises(InvalidManifestError):
        await YamlManifestProviderAdapter(tmp_path).load()


async def test_no_vault_means_the_default_alone() -> None:
    manifest = await YamlManifestProviderAdapter(None).load()
    assert len(manifest.kinds) == 8


def test_frontmatter_round_trip() -> None:
    codec = YamlFrontmatterCodecAdapter()
    frontmatter = NoteFrontmatter(
        id=NoteId(value=ULID),
        scope=NoteScope.parse("topic:rust"),
        kind=NoteKind(value="howto"),
        origin=NoteOriginEnum.AUTO,
        sources=(NoteSourceRef(value="commit:8e6d3b5f"), NoteSourceRef(value="session:abcd1234")),
        updated=date(2026, 11, 11),
    )
    body = "\n# Title\n\n## Goal\n\nBody with --- inside.\n"
    text = codec.render(frontmatter, body)
    assert text.startswith("---\nnoesis:\n  id: 01ARZ3NDEKTSV4RRFFQ69G5FAV\n  scope: topic:rust\n")
    parsed = codec.parse(text)
    assert parsed.frontmatter == frontmatter
    assert parsed.body == body
    assert codec.render(parsed.frontmatter, parsed.body) == text  # type: ignore[arg-type]


def test_a_file_without_a_noesis_block_has_no_frontmatter() -> None:
    codec = YamlFrontmatterCodecAdapter()
    plain = codec.parse("# Just a note\n\ntext\n")
    assert plain.frontmatter is None and plain.body == "# Just a note\n\ntext\n"
    legacy = codec.parse("---\ntype: decision\nid: auto-decision-x\ndate: 2026-10-30\n---\n\n# X\n")
    assert legacy.frontmatter is None
    assert legacy.header["type"] == "decision" and legacy.header["date"] == "2026-10-30"
    assert legacy.body == "\n# X\n"
    broken = codec.parse("---\nnoesis:\n  id: nope\n---\n# X\n")
    assert broken.frontmatter is None


def test_render_keeps_extra_keys_before_the_noesis_block_and_dates_as_dates() -> None:
    codec = YamlFrontmatterCodecAdapter()
    frontmatter = NoteFrontmatter(
        id=NoteId(value=ULID),
        scope=NoteScope.parse("topic:rust"),
        kind=NoteKind(value="howto"),
        origin=NoteOriginEnum.AUTO,
        updated=date(2026, 11, 11),
    )
    original = "---\ntags: [a, b]\ncreated: 2026-01-02\nnoesis:\n  id: stale\n---\nbody\n"
    header = codec.parse(original).header
    text = codec.render(frontmatter, "body\n", header)
    assert text.startswith("---\ntags:\n- a\n- b\ncreated: 2026-01-02\nnoesis:\n  id: " + ULID)
    assert text.count("noesis:") == 1


async def test_drift_and_dependency_kinds_have_their_folders_and_sections() -> None:
    catalog = (await YamlManifestProviderAdapter(None).load()).catalog()
    drift = catalog.require(NoteKind(value="drift"))
    dependency = catalog.require(NoteKind(value="dependency"))
    assert (drift.folder, dependency.folder) == ("drift", "dependencies")
    assert "diverg" in drift.description and "reconcile" in drift.description
    assert "depends on" in dependency.description
    assert drift.sections and dependency.sections


def test_codec_flags_a_header_it_cannot_read_instead_of_hiding_it() -> None:
    codec = YamlFrontmatterCodecAdapter()
    assert codec.parse("---\nkey: [unclosed\n---\nbody\n").malformed_header
    assert codec.parse("---\n- a list\n---\nbody\n").malformed_header
    assert codec.parse("---\nno closing line\n").malformed_header
    assert not codec.parse("---\ntags: [a]\n---\nbody\n").malformed_header
    assert not codec.parse("# no header\n").malformed_header
