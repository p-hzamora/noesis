"""ImportFileHandler over scripted fakes (FR-019, FR-020; AC-025, AC-027)."""

from typing import Any

import pytest
from tests.support.import_support import K1
from tests.support.interop_support import (
    FakeFileReader,
    FakeKnowledgeImporter,
    build_file,
    file_command,
    note,
    outcome,
)

from noesis.exceptions import AppException

pytestmark = pytest.mark.unit

DESIGN = "/work/outside/design.md"
DESIGN_BYTES: bytes = note(
    "# Design\n\nUse [[ports|the ports note]].\n\n## Related\n\n- [[x]]", "title: Ignored by option"
)


async def _import(
    files: dict[str, bytes],
    command_path: str = DESIGN,
    *,
    importer: FakeKnowledgeImporter | None = None,
    links: dict[str, str] | None = None,
    **options: Any,
) -> tuple[dict[str, Any], FakeKnowledgeImporter]:
    importer = importer or FakeKnowledgeImporter()
    handler = build_file(FakeFileReader(files, links), importer)
    result = await handler.handle(file_command(command_path, **options))
    return result.model_dump(mode="json"), importer


async def _refused(
    files: dict[str, bytes], *, importer: FakeKnowledgeImporter | None = None, **options: Any
) -> AppException:
    importer = importer or FakeKnowledgeImporter()
    handler = build_file(FakeFileReader(files), importer)
    with pytest.raises(AppException) as raised:
        await handler.handle(file_command(DESIGN, **options))
    return raised.value


async def test_import_builds_the_request_from_the_file_and_the_options() -> None:
    result, importer = await _import(
        {DESIGN: DESIGN_BYTES}, title="Design notes", project_key="alpha", tags=("area:core",)
    )

    request = importer.requests("apply")[DESIGN].model_dump(mode="json")
    assert request["record_id"] is None
    assert request["origin_tag"] == "origin:imported"
    assert request["title"] == "Design notes"
    assert request["body"] == "# Design\n\nUse the ports note."
    assert (request["subtype"], request["project_key"], request["tags"]) == (
        "note",
        "alpha",
        ["area:core"],
    )
    assert request["header_sources"] == []
    assert request["on_change"] == "update"
    assert request["source_locator"] == DESIGN
    assert request["source_digest"].startswith("sha256:") and len(request["source_digest"]) == 71
    assert [kind for kind, _ in importer.calls] == ["apply"]
    assert result["applied"] is True
    assert result["path"] == DESIGN and result["source_locator"] == DESIGN
    assert "legacy_header" not in result["warnings"]


async def test_title_comes_from_the_header_when_no_option_gives_one() -> None:
    result, _ = await _import({DESIGN: DESIGN_BYTES})

    assert result["title"] == "Ignored by option"


async def test_a_link_to_the_file_resolves_and_the_locator_is_the_target_path() -> None:
    target = "/work/real/design.md"

    result, importer = await _import(
        {target: DESIGN_BYTES}, "/work/link.md", links={"/work/link.md": target}
    )

    assert result["path"] == target
    assert list(importer.requests("apply")) == [target]


async def test_dry_run_assesses_without_applying_and_ends_with_the_command_without_the_flag() -> (
    None
):
    importer = FakeKnowledgeImporter(
        assess=lambda r: outcome("revised", record_id=K1, revision=2, status="proposed")
    )

    result, importer = await _import({DESIGN: DESIGN_BYTES}, importer=importer, dry_run=True)

    assert [kind for kind, _ in importer.calls] == ["assess"]
    assert (result["applied"], result["outcome"], result["revision"]) == (False, "revised", 2)
    steps: list[str] = result["next_steps"]
    assert any(step.startswith("noesis import file") and DESIGN in step for step in steps)
    assert not any("--dry-run" in step for step in steps)


async def test_header_metadata_fills_what_the_options_leave_and_the_header_id_is_never_used() -> (
    None
):
    header = "tags: [x]\nnoesis:\n  id: " + K1 + "\n  scope: repo:beta\n  kind: howto"
    data = note("Body.", header)

    result, importer = await _import({DESIGN: data})
    request = importer.requests("apply")[DESIGN].model_dump(mode="json")

    assert request["record_id"] is None
    assert (request["subtype"], request["project_key"], request["tags"]) == ("howto", "beta", ["x"])
    assert result["record_id"] != K1

    _, importer = await _import(
        {DESIGN: data}, subtype="decision", project_key="alpha", tags=("y",)
    )
    request = importer.requests("apply")[DESIGN].model_dump(mode="json")
    assert (request["subtype"], request["project_key"], request["tags"]) == (
        "decision",
        "alpha",
        ["x", "y"],
    )


async def test_header_sources_are_never_read() -> None:
    header = (
        "noesis:\n  id: " + K1 + '\n  scope: repo:beta\n  kind: howto\n  sources: ["session:s-1"]'
    )

    _, importer = await _import({DESIGN: note("Body.", header)})

    assert importer.requests("apply")[DESIGN].model_dump(mode="json")["header_sources"] == []


async def test_an_invalid_header_scope_is_ignored_with_a_warning_and_never_blocks() -> None:
    header = "noesis:\n  scope: team:core\n  kind: howto"

    result, importer = await _import({DESIGN: note("Body.", header)})

    request = importer.requests("apply")[DESIGN].model_dump(mode="json")
    assert request["project_key"] is None
    assert "ignored_scope" in result["warnings"]
    assert "legacy_header" not in result["warnings"]


async def test_an_older_layout_header_gives_no_legacy_warning_and_its_invalid_tags_are_dropped() -> (
    None
):
    result, importer = await _import({DESIGN: note("Body.", "type: learning\ntags: [ok, not ok]")})

    request = importer.requests("apply")[DESIGN].model_dump(mode="json")
    assert (request["subtype"], request["tags"]) == ("learning", ["ok"])
    assert "legacy_header" not in result["warnings"]
    assert "dropped_tag:not ok" in result["warnings"]


async def test_invalid_option_values_are_not_dropped_but_left_to_knowledge() -> None:
    _, importer = await _import(
        {DESIGN: note("Body.")}, subtype="Big Kind", project_key="bad key", tags=("bad tag",)
    )

    request = importer.requests("apply")[DESIGN].model_dump(mode="json")
    assert request["subtype"] == "Big Kind"
    assert request["project_key"] == "bad key"
    assert request["tags"] == ["bad tag"]


@pytest.mark.parametrize(
    ("data", "reason"),
    [
        pytest.param(b"\xff\xfe\x00\x01", "not_text", id="binary"),
        pytest.param(b"---\ntitle: x\n---\n", "empty_body", id="header-only"),
        pytest.param(b"", "empty_body", id="zero-bytes"),
        pytest.param(
            note("# Index\n\n## P\n\n- [[a]]\n- [[b]]"), "empty_body", id="links-only-hub"
        ),
        pytest.param(b"---\nnoesis: [unclosed\n---\nx", "invalid_header", id="broken-header"),
    ],
)
async def test_a_file_that_cannot_be_imported_raises_import_203_before_any_knowledge_call(
    data: bytes, reason: str
) -> None:
    importer = FakeKnowledgeImporter()

    error = await _refused({DESIGN: data}, importer=importer)

    assert error.error_code == "IMPORT_203_FILE_NOT_IMPORTABLE"
    assert error.metadata["reason"] == reason
    assert error.metadata["path"] == DESIGN
    assert importer.calls == []


@pytest.mark.parametrize("dry_run", [False, True])
async def test_a_blocked_outcome_becomes_import_203_with_reason_and_detail(dry_run: bool) -> None:
    blocked = outcome(
        "blocked", block_reason="invalid_metadata", detail="KNOWLEDGE_002_INVALID_SLUG"
    )
    importer = FakeKnowledgeImporter(assess=lambda r: blocked, apply=lambda r: blocked)

    error = await _refused(
        {DESIGN: note("Body.")}, importer=importer, dry_run=dry_run, subtype="Big Kind"
    )

    assert error.error_code == "IMPORT_203_FILE_NOT_IMPORTABLE"
    assert error.metadata["reason"] == "invalid_metadata"
    assert error.metadata["detail"] == "KNOWLEDGE_002_INVALID_SLUG"


@pytest.mark.parametrize("kind", ["unchanged", "revised", "successor_proposed", "created"])
async def test_every_non_blocked_outcome_succeeds_and_is_reported(kind: str) -> None:
    importer = FakeKnowledgeImporter(
        apply=lambda r: outcome(
            kind,
            record_id=K1,
            revision=2,
            status="proposed",
            target_record_id=K1 if kind == "successor_proposed" else None,
            assertion_id=K1 if kind == "successor_proposed" else None,
        )
    )

    result, _ = await _import({DESIGN: note("Body.")}, importer=importer)

    assert result["outcome"] == kind
    assert result["record_id"] == K1
    assert result["tags"] == ["origin:imported"]
