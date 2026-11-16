"""Record outcomes control independent source and target maps in step eight."""

import pytest
from tests.support.import_support import K1, K2, K3
from tests.support.interop_support import (
    FakeKnowledgeImporter,
    current_header,
    note,
    outcome,
    plan,
    run,
)

pytestmark = pytest.mark.unit


def scripted(answers):
    return lambda request: answers[request.source_locator.rsplit("/", 1)[-1]]


@pytest.mark.parametrize("target_outcome", ["changed", "blocked", "successor_proposed"])
async def test_existing_targets_survive_record_refusal_or_successor(target_outcome) -> None:
    answers = {
        "a.md": outcome("unchanged", record_id=K1),
        "b.md": outcome(
            target_outcome,
            record_id=K3 if target_outcome == "successor_proposed" else K2,
            target_record_id=K2 if target_outcome == "successor_proposed" else None,
        ),
    }
    importer = FakeKnowledgeImporter(assess=scripted(answers), apply=scripted(answers))
    result = await run({"a.md": note("Prose [[b]]"), "b.md": note("Prose [[a]]")}, importer)
    request = importer.link_calls[0][1]
    assert request.source_record_id == K1
    assert request.links[0].target_record_id == K2
    assert all(kind == "replace" for kind, _ in importer.link_calls)
    assert result["links"]["resolved"] >= 1
    if target_outcome == "successor_proposed":
        assert importer.link_calls[1][1].source_record_id == K3
    else:
        assert len(importer.link_calls) == 1
        assert result["link_sets"]["deferred" if target_outcome == "changed" else "no_record"] == 1


@pytest.mark.parametrize("kind", ["created", "successor_proposed"])
@pytest.mark.parametrize("declared", [False, True])
async def test_preview_pending_sources_and_targets_never_reach_knowledge(kind, declared) -> None:
    answers = {
        "a.md": outcome("unchanged", record_id=K1),
        "b.md": outcome(
            kind,
            record_id=K2 if declared else None,
            target_record_id=K3 if kind == "successor_proposed" else None,
        ),
    }
    importer = FakeKnowledgeImporter(assess=scripted(answers))
    result = await plan(
        {
            "a.md": note("Prose [[b]]"),
            "b.md": note("Prose [[a]]", current_header(id=K2) if declared else None),
        },
        importer,
    )
    assert result["link_sets"]["planned"] == 2
    if kind == "created":
        assert importer.link_calls == []
    else:
        assert len(importer.link_calls) == 1
        assert importer.link_calls[0][1].links[0].target_record_id == K3
    assert all(
        not link.target_record_id.startswith("pending:")
        for _, request in importer.link_calls
        for link in request.links
    )


async def test_links_only_section_precedes_normalisation_and_skipped_sources() -> None:
    importer = FakeKnowledgeImporter()
    result = await run(
        {
            "a.md": note("Prose.\n\n## See also\n- [[b]]"),
            "b.md": note("Text."),
            "hub.md": note("# Hub\n- [[a]]"),
        },
        importer,
    )
    assert result["links"]["resolved"] == 1
    assert result["link_sets"]["created"] == 1
    assert result["link_sets"]["no_record"] == 1
    assert "See also" not in importer.requests()["vault://fixture/a.md"].body


async def test_link_refusal_does_not_change_complete_or_strict() -> None:
    from noesis.shared_kernel.contracts.knowledge.import_link_set_contract import (
        ImportLinkSetOutcomeContract,
    )

    class Refusing(FakeKnowledgeImporter):
        async def replace_links(self, request):
            return ImportLinkSetOutcomeContract(
                outcome="blocked",
                source_record_id=request.source_record_id,
                edges=0,
                block_reason="target_not_in_space",
            )

    result = await run({"a.md": note("Text [[b]]"), "b.md": note("Text")}, Refusing(), strict=True)
    assert result["complete"] is True
    assert result["link_sets"]["blocked"] == 2
    assert result["notes"][0]["links"]["block_reason"] == "target_not_in_space"
