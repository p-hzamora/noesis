"""Relations in the links pass: one replace call per source, classes, gates and the commit Source."""

import pytest
from tests.support.import_support import K1, K2, K3
from tests.support.interop_support import (
    FakeKnowledgeImporter,
    current_header,
    note,
    outcome,
    plan,
    row,
    run,
)

pytestmark = pytest.mark.unit

A = "company/x/repos/r/concepts/a.md"
B = "company/x/repos/r/concepts/b.md"


def related(*entries: tuple[str, str]) -> str:
    return "related:\n" + "\n".join(f"  - {{id: {i}, relation: {w}}}" for i, w in entries)


def header(record_id: str, *extra: str) -> str:
    return "\n".join([*extra, current_header(id=record_id, scope="repo:r", kind="concept")])


def sent(importer, source: str):
    """The replace requests the importer got for one source record."""
    return [
        r for kind, r in importer.link_calls if kind == "replace" and r.source_record_id == source
    ]


def scripted(answers):
    return lambda request: answers[request.source_locator.rsplit("/", 1)[-1]]


async def test_a_resolved_relation_reaches_knowledge_with_the_record_id_of_its_target() -> None:
    importer = FakeKnowledgeImporter()
    result = await run(
        {
            A: note("A", header(K1, related(("r--concept--b", "refines")))),
            B: note("B", header(K2)),
        },
        importer,
    )
    replaced = sent(importer, K1)
    assert len(replaced) == 1
    assert replaced[0].source_record_id == K1
    assert replaced[0].contract_version == 2
    assert [(r.target_record_id, r.relation) for r in replaced[0].relations] == [(K2, "refines")]
    assert replaced[0].links == ()
    assert row(result, A)["relations"]["resolved"] == 1
    assert row(result, A)["relations"]["outcome"] == "created"
    assert result["relations"]["resolved"] == 1
    assert result["link_sets"]["created"] == 1


async def test_relations_never_change_the_wiki_link_report() -> None:
    files = {
        A: note("See [[b]]", header(K1, related(("r--concept--b", "contradicts")))),
        B: note("B", header(K2)),
    }
    with_relations = await run(files, FakeKnowledgeImporter())
    plain = await run(
        {A: note("See [[b]]", header(K1)), B: note("B", header(K2))}, FakeKnowledgeImporter()
    )
    assert with_relations["links"] == plain["links"]
    assert row(with_relations, A)["links"] == row(plain, A)["links"]


async def test_a_target_that_is_both_a_wiki_link_and_a_relation_sends_both() -> None:
    importer = FakeKnowledgeImporter()
    await run(
        {
            A: note("See [[b]]", header(K1, related(("r--concept--b", "extends")))),
            B: note("B", header(K2)),
        },
        importer,
    )
    request = importer.link_calls[0][1]
    assert [link.target_record_id for link in request.links] == [K2]
    assert [r.target_record_id for r in request.relations] == [K2]


async def test_a_relation_only_note_still_gets_its_link_set() -> None:
    importer = FakeKnowledgeImporter()
    result = await run(
        {
            A: note("No wiki links here.", header(K1, related(("r--concept--b", "part_of")))),
            B: note("B", header(K2)),
        },
        importer,
    )
    assert [r.relations[0].target_record_id for r in sent(importer, K1)] == [K2]
    assert result["link_sets"]["created"] == 1


async def test_classes_are_counted_per_note_and_in_totals_and_named_in_the_row() -> None:
    files = {
        A: note(
            "A",
            header(
                K1,
                related(
                    ("r--concept--ghost", "refines"),
                    ("r--concept--twice", "refines"),
                    ("r--concept--a", "refines"),
                    ("r--concept--b", "weird"),
                    ("nonsense", "refines"),
                    ("r--concept--b", "contains"),
                ),
            ),
        ),
        B: note("B", header(K2)),
        "x/twice.md": note("1"),
        "y/twice.md": note("2"),
    }
    result = await run(files, FakeKnowledgeImporter())
    counts = row(result, A)["relations"]
    assert {k: v for k, v in counts.items() if k != "outcome"} == {
        "resolved": 1,
        "dangling": 1,
        "ambiguous": 1,
        "not_imported": 0,
        "self": 1,
        "unknown_relation": 1,
        "invalid_relation": 1,
    }
    named = {(u["classification"], u["target"]): u for u in row(result, A)["unresolved_relations"]}
    assert named[("ambiguous", "r--concept--twice")]["candidates"] == ["x/twice.md", "y/twice.md"]
    assert ("dangling", "r--concept--ghost") in named
    assert not any(c == "resolved" for c, _ in named)
    assert result["relations"] == {k: v for k, v in counts.items() if k != "outcome"}


async def test_dangling_relations_never_block_strict_and_create_no_record() -> None:
    importer = FakeKnowledgeImporter()
    result = await run(
        {A: note("A", header(K1, related(("r--concept--ghost", "refines"))))},
        importer,
        strict=True,
    )
    assert result["complete"] is True
    assert result["relations"]["dangling"] == 1
    assert [request.source_locator for _, request in importer.calls] == [
        f"vault://fixture/{A}",
        f"vault://fixture/{A}",
    ]
    assert all(not request.relations for _, request in importer.link_calls)
    assert row(result, A)["relations"]["outcome"] is None


async def test_a_target_note_without_a_record_is_not_imported() -> None:
    answers = {"a.md": outcome("created", record_id=K1), "b.md": outcome("blocked", reason="x")}
    importer = FakeKnowledgeImporter(assess=scripted(answers), apply=scripted(answers))
    result = await run(
        {
            "repos/r/a.md": note("A", header(K1, related(("r--concept--b", "refines")))),
            "repos/r/b.md": note("B", header(K2)),
        },
        importer,
    )
    assert row(result, "repos/r/a.md")["relations"]["not_imported"] == 1
    assert all(not request.relations for _, request in importer.link_calls)


async def test_a_note_with_no_record_reports_no_record() -> None:
    result = await run(
        {
            A: note("", header(K1, related(("r--concept--b", "refines")))),
            B: note("B", header(K2)),
        },
        FakeKnowledgeImporter(),
    )
    assert row(result, A)["outcome"] == "skipped_empty"
    assert row(result, A)["relations"]["outcome"] == "no_record"
    assert result["link_sets"]["no_record"] == 1


async def test_a_changed_note_defers_its_relations_with_its_links() -> None:
    answers = {"a.md": outcome("changed", record_id=K1), "b.md": outcome("unchanged", record_id=K2)}
    importer = FakeKnowledgeImporter(assess=scripted(answers), apply=scripted(answers))
    result = await run(
        {
            "repos/r/a.md": note("A", header(K1, related(("r--concept--b", "refines")))),
            "repos/r/b.md": note("B", header(K2)),
        },
        importer,
    )
    assert row(result, "repos/r/a.md")["relations"]["outcome"] == "deferred"
    assert sent(importer, K1) == []


async def test_a_related_only_change_keeps_the_record_unchanged_and_replaces_the_link_set() -> None:
    answers = {
        "a.md": outcome("unchanged", record_id=K1),
        "b.md": outcome("unchanged", record_id=K2),
    }
    importer = FakeKnowledgeImporter(assess=scripted(answers), apply=scripted(answers))
    result = await run(
        {
            "repos/r/a.md": note("A", header(K1, related(("r--concept--b", "supersedes")))),
            "repos/r/b.md": note("B", header(K2)),
        },
        importer,
    )
    assert row(result, "repos/r/a.md")["outcome"] == "unchanged"
    assert row(result, "repos/r/a.md")["relations"]["outcome"] == "created"
    assert importer.link_calls[0][1].relations[0].relation == "supersedes"


async def test_preview_plans_a_relation_to_a_pending_record_without_calling_knowledge() -> None:
    answers = {"a.md": outcome("unchanged", record_id=K1), "b.md": outcome("created")}
    importer = FakeKnowledgeImporter(assess=scripted(answers))
    result = await plan(
        {
            "repos/r/a.md": note("A", header(K1, related(("r--concept--b", "refines")))),
            "repos/r/b.md": note("B"),
        },
        importer,
    )
    assert row(result, "repos/r/a.md")["relations"]["outcome"] == "planned"
    assert importer.link_calls == []
    assert result["link_sets"]["planned"] == 1


async def test_a_note_without_related_reports_zero_relations_and_no_outcome() -> None:
    result = await run({A: note("A", header(K3))}, FakeKnowledgeImporter())
    assert result["relations"] == {
        "resolved": 0,
        "dangling": 0,
        "ambiguous": 0,
        "not_imported": 0,
        "self": 0,
        "unknown_relation": 0,
        "invalid_relation": 0,
    }
    assert row(result, A)["relations"]["outcome"] is None
