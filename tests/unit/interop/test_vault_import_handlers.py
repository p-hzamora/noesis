"""PlanVaultImportHandler and RunVaultImportHandler over scripted fakes (FR-003, 005, 009, 011)."""

from collections.abc import Callable
from typing import Any

import pytest
from tests.support.import_support import K1, K2, K3, K7
from tests.support.interop_support import (
    FakeKnowledgeImporter,
    FakeVaultReader,
    build_plan,
    build_run,
    current_header,
    note,
    outcome,
    plan,
    row,
    run,
)

from noesis.bounded_context.interop.application.handlers import (
    PlanVaultImportQuery,
    RunVaultImportCommand,
)
from noesis.exceptions import AppException, GraphStoreUnavailableError
from noesis.shared_kernel.contracts.knowledge import (
    ImportKnowledgeOutcomeContract,
    ImportKnowledgeRequestContract,
)

pytestmark = pytest.mark.unit

type Script = Callable[[ImportKnowledgeRequestContract], ImportKnowledgeOutcomeContract]

FIVE_NOTES: dict[str, bytes] = {f"n{index}.md": note(f"Body {index}.") for index in range(1, 6)}
ZERO_TOTALS: dict[str, int] = {
    "notes": 0,
    "created": 0,
    "unchanged": 0,
    "changed_in_vault": 0,
    "revised": 0,
    "successor_proposed": 0,
    "skipped_empty": 0,
    "blocked": 0,
}


def _by_file(table: dict[str, ImportKnowledgeOutcomeContract]) -> Script:
    """A script answering by the request's file name (`vault://fixture/<name>`)."""

    def answer(request: ImportKnowledgeRequestContract) -> ImportKnowledgeOutcomeContract:
        return table[request.source_locator.rsplit("/", 1)[-1]]

    return answer


def _created(request: ImportKnowledgeRequestContract) -> ImportKnowledgeOutcomeContract:
    return outcome("created", record_id=request.record_id, revision=1, status="proposed")


def _blocked_for(name: str, reason: str, detail: str | None = None) -> Script:
    def answer(request: ImportKnowledgeRequestContract) -> ImportKnowledgeOutcomeContract:
        if request.source_locator.endswith(f"/{name}"):
            return outcome("blocked", block_reason=reason, detail=detail)
        return _created(request)

    return answer


def _handler_and_action(
    kind: str, files: dict[str, bytes], importer: FakeKnowledgeImporter, **options: bool
) -> tuple[Any, Any]:
    if kind == "plan":
        return build_plan(FakeVaultReader(files), importer), PlanVaultImportQuery(**options)
    return build_run(FakeVaultReader(files), importer), RunVaultImportCommand(**options)


async def test_notes_are_assessed_then_applied_strictly_in_path_order() -> None:
    importer = FakeKnowledgeImporter()
    files: dict[str, bytes] = {name: note(name) for name in ("b.md", "z/a.md", "a.md", "Z.md")}

    await run(files, importer)

    ordered: list[str] = sorted(files)
    assert importer.sequence() == [("assess", f"vault://fixture/{p}") for p in ordered] + [
        ("apply", f"vault://fixture/{p}") for p in ordered
    ]


async def test_apply_is_called_only_for_notes_assessed_created_revised_or_successor() -> None:
    assessed = {
        "n1.md": outcome("created", record_id=K1, revision=1, status="proposed"),
        "n2.md": outcome("unchanged", record_id=K2, revision=1, status="proposed"),
        "n3.md": outcome("changed", record_id=K3, revision=1, status="proposed"),
        "n4.md": outcome("revised", record_id=K3, revision=2, status="proposed"),
        "n5.md": outcome("blocked", block_reason="target_closed"),
    }
    importer = FakeKnowledgeImporter(assess=_by_file(assessed))

    await run(FIVE_NOTES, importer, update=True)

    applied = [loc.rsplit("/", 1)[-1] for kind, loc in importer.sequence() if kind == "apply"]
    assert applied == ["n1.md", "n4.md"]


async def test_the_apply_result_is_the_reported_outcome_not_the_assessed_one() -> None:
    importer = FakeKnowledgeImporter(
        assess=_by_file({"n1.md": outcome("created", record_id=K1, revision=1, status="proposed")}),
        apply=lambda request: outcome("blocked", block_reason="id_conflict"),
    )

    result = await run({"n1.md": note("x")}, importer)

    assert row(result, "n1.md")["outcome"] == "blocked"
    assert row(result, "n1.md")["reason"] == "id_conflict"
    assert result["totals"]["blocked"] == 1
    assert result["blocked_reasons"] == {"id_conflict": 1}
    assert result["complete"] is False


async def test_changed_is_reported_as_changed_in_vault_and_not_applied() -> None:
    importer = FakeKnowledgeImporter(
        assess=lambda request: outcome("changed", record_id=K1, revision=1, status="proposed")
    )

    result = await run({"n1.md": note("x")}, importer)

    assert row(result, "n1.md")["outcome"] == "changed_in_vault"
    assert (row(result, "n1.md")["record_id"], row(result, "n1.md")["revision"]) == (K1, 1)
    assert result["totals"]["changed_in_vault"] == 1
    assert result["complete"] is True
    assert [kind for kind, _ in importer.calls] == ["assess"]
    assert "noesis import run --yes --update" in result["next_steps"]


async def test_a_blocked_note_does_not_stop_the_others() -> None:
    importer = FakeKnowledgeImporter(
        assess=_blocked_for("n2.md", "invalid_metadata", "KNOWLEDGE_002_INVALID_SLUG")
    )

    result = await run(FIVE_NOTES, importer)

    blocked = row(result, "n2.md")
    assert (blocked["outcome"], blocked["reason"], blocked["detail"]) == (
        "blocked",
        "invalid_metadata",
        "KNOWLEDGE_002_INVALID_SLUG",
    )
    assert result["totals"] == {**ZERO_TOTALS, "notes": 5, "created": 4, "blocked": 1}
    assert result["complete"] is False
    assert "noesis import run --verbose" in result["next_steps"]


async def test_connection_lost_on_the_third_apply_propagates_and_stops_the_run() -> None:
    applies: list[str] = []

    def apply(request: ImportKnowledgeRequestContract) -> ImportKnowledgeOutcomeContract:
        applies.append(request.source_locator)
        if len(applies) == 3:
            raise GraphStoreUnavailableError("Neo4j is unreachable.")
        return _created(request)

    importer = FakeKnowledgeImporter(apply=apply)
    handler = build_run(FakeVaultReader(FIVE_NOTES), importer)

    with pytest.raises(GraphStoreUnavailableError):
        await handler.handle(RunVaultImportCommand(update=False, strict=False))

    assert len(applies) == 3
    assert [kind for kind, _ in importer.calls].count("apply") == 3


async def test_a_store_error_while_assessing_stops_before_any_apply() -> None:
    def assess(request: ImportKnowledgeRequestContract) -> ImportKnowledgeOutcomeContract:
        raise GraphStoreUnavailableError("Neo4j is unreachable.")

    importer = FakeKnowledgeImporter(assess=assess)

    with pytest.raises(GraphStoreUnavailableError):
        await run(FIVE_NOTES, importer)

    assert [kind for kind, _ in importer.calls] == ["assess"]


@pytest.mark.parametrize("kind", ["plan", "run"])
async def test_strict_refuses_an_interop_blocked_note_before_any_store_access(kind: str) -> None:
    files = {
        "bad.md": note("x", current_header(id="nope", scope="repo:alpha", kind="concept")),
        "dup-a.md": note("a", current_header(id=K7, scope="repo:alpha", kind="concept")),
        "dup-b.md": note("b", current_header(id=K7, scope="repo:alpha", kind="concept")),
        "fine.md": note("fine"),
    }
    importer = FakeKnowledgeImporter()
    handler, action = _handler_and_action(kind, files, importer, update=True, strict=True)

    with pytest.raises(AppException) as raised:
        await handler.handle(action)

    assert raised.value.error_code == "IMPORT_201_BLOCKING_FINDINGS"
    assert raised.value.metadata["blocked_reasons"] == {"invalid_id": 1, "duplicate_id": 2}
    assert sorted(raised.value.metadata["paths"]) == ["bad.md", "dup-a.md", "dup-b.md"]  # type: ignore[arg-type]
    assert importer.calls == []


@pytest.mark.parametrize("kind", ["plan", "run"])
async def test_strict_refuses_a_note_blocked_by_knowledge_after_assess_and_writes_nothing(
    kind: str,
) -> None:
    importer = FakeKnowledgeImporter(
        assess=_blocked_for("n3.md", "invalid_metadata", "KNOWLEDGE_002_INVALID_SLUG")
    )
    handler, action = _handler_and_action(kind, FIVE_NOTES, importer, update=False, strict=True)

    with pytest.raises(AppException) as raised:
        await handler.handle(action)

    assert raised.value.error_code == "IMPORT_201_BLOCKING_FINDINGS"
    assert raised.value.metadata["blocked_reasons"] == {"invalid_metadata": 1}
    assert {call for call, _ in importer.calls} == {"assess"}


async def test_strict_with_nothing_blocked_runs_normally() -> None:
    result = await run(FIVE_NOTES, strict=True)

    assert result["complete"] is True and result["totals"]["created"] == 5


async def test_duplicate_ids_are_found_over_the_whole_list_before_any_assess() -> None:
    header = current_header(id=K1, scope="repo:alpha", kind="concept")
    files = {"a.md": note("a", header), "m.md": note("m"), "z.md": note("z", header)}
    importer = FakeKnowledgeImporter()

    result = await run(files, importer)

    assert [row(result, p)["reason"] for p in ("a.md", "z.md")] == ["duplicate_id", "duplicate_id"]
    assert importer.sequence() == [
        ("assess", "vault://fixture/m.md"),
        ("apply", "vault://fixture/m.md"),
    ]


async def test_preview_never_applies_and_ends_with_the_exact_apply_command() -> None:
    importer = FakeKnowledgeImporter()

    result = await plan(FIVE_NOTES, importer)
    with_update = await plan(FIVE_NOTES, importer, update=True)

    assert {kind for kind, _ in importer.calls} == {"assess"}
    assert result["applied"] is False and result["update"] is False
    assert "noesis import run --yes" in result["next_steps"]
    assert with_update["update"] is True
    assert "noesis import run --yes --update" in with_update["next_steps"]


async def test_apply_result_header_fields() -> None:
    result = await run(FIVE_NOTES)

    assert result["applied"] is True and result["update"] is False
    assert result["vault_key"] == "fixture"
    assert result["complete"] is True
    assert result["totals"] == {**ZERO_TOTALS, "notes": 5, "created": 5}
    assert result["blocked_reasons"] == {}
    assert result["warnings"] == {"legacy_header": 0, "dropped_tag": 0, "ignored_field": 0}
    assert result["sources_skipped"] == 0
    assert not {"noesis import run --yes --update", "noesis import run --verbose"} & set(
        result["next_steps"]
    )


async def test_totals_warnings_and_rows_add_up_for_a_mixed_vault() -> None:
    files = {
        "a.md": note("x", current_header(id=K1, scope="repo:alpha", kind="concept")),
        "b.md": note("Legacy.", "type: learning\ntags: [ok, not ok]"),
        "c.md": note("# Index\n\n- [[a]]", "type: index"),
        "d.md": b"",
        "e.md": b"\xff\xfe\x00\x01",
        "f.md": note("x", "noesis: text"),
    }

    result = await run(files)

    totals = result["totals"]
    assert totals["notes"] == 6
    assert (totals["created"], totals["skipped_empty"], totals["blocked"]) == (2, 2, 2)
    assert sum(value for key, value in totals.items() if key != "notes") == totals["notes"]
    assert result["blocked_reasons"] == {"not_text": 1, "invalid_header": 1}
    assert result["warnings"] == {"legacy_header": 2, "dropped_tag": 1, "ignored_field": 0}
    assert [item["path"] for item in result["notes"]] == sorted(files)
    assert result["complete"] is False


async def test_row_carries_the_outcome_fields_of_the_note() -> None:
    importer = FakeKnowledgeImporter(
        apply=lambda request: outcome(
            "created",
            record_id=K1,
            revision=1,
            status="proposed",
            target_record_id=K2,
            reason="assertions unavailable: target not linked",
        )
    )
    header = "tags: [b, a]\n" + current_header(id=K1, scope="repo:alpha", kind="concept")

    result = await run({"p.md": note("# Ports\n\nText.", header)}, importer)

    assert row(result, "p.md") == {
        "path": "p.md",
        "outcome": "created",
        "record_id": K1,
        "revision": 1,
        "status": "proposed",
        "title": "Ports",
        "subtype": "concept",
        "project_key": "alpha",
        "tags": ["a", "b", "origin:migrated"],
        "target_record_id": K2,
        "assertion_id": None,
        "reason": "assertions unavailable: target not linked",
        "detail": None,
        "warnings": [],
        "ambiguous": [],
        "links": {
            "resolved": 0,
            "dangling": 0,
            "ambiguous": 0,
            "non_note": 0,
            "not_imported": 0,
            "self": 0,
            "outcome": None,
        },
    }


async def test_an_empty_vault_reports_zero_counts_and_is_complete() -> None:
    result = await run({})

    assert result["totals"] == ZERO_TOTALS
    assert result["complete"] is True and result["notes"] == []


async def test_a_read_failure_stops_before_any_knowledge_call() -> None:
    class Failing(FakeVaultReader):
        def read(self, relative_path: str) -> bytes:
            raise AppException(f"cannot read {relative_path}")

    importer = FakeKnowledgeImporter()
    handler = build_run(Failing({"a.md": b"x"}), importer)

    with pytest.raises(AppException, match=r"cannot read a\.md"):
        await handler.handle(RunVaultImportCommand(update=False, strict=False))

    assert importer.calls == []


async def test_successor_proposed_is_counted_and_keeps_its_assertion() -> None:
    importer = FakeKnowledgeImporter(
        assess=lambda r: outcome(
            "successor_proposed", revision=1, status="proposed", target_record_id=K1
        ),
        apply=lambda r: outcome(
            "successor_proposed",
            record_id=K2,
            revision=1,
            status="proposed",
            target_record_id=K1,
            assertion_id=K3,
        ),
    )

    result = await run({"n1.md": note("x")}, importer, update=True)

    assert result["totals"]["successor_proposed"] == 1
    assert (row(result, "n1.md")["target_record_id"], row(result, "n1.md")["assertion_id"]) == (
        K1,
        K3,
    )
