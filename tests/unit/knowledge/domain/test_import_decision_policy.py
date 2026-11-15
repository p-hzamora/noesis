"""ImportDecisionPolicy: every row of the decision table, target selection and orderings."""

from datetime import UTC, datetime, timedelta

import pytest

from noesis.bounded_context.knowledge.domain.services import ImportDecisionPolicy
from noesis.bounded_context.knowledge.domain.value_objects import (
    ContentHash,
    GraphContent,
    ImportCandidate,
    ImportDecision,
    RecordId,
    RecordStatusEnum,
)

pytestmark = pytest.mark.unit

T0: datetime = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
INCOMING: GraphContent = GraphContent(title="Title", body="Incoming body.")
OLD: GraphContent = GraphContent(title="Title", body="Old body.")
DIGEST: ContentHash = ContentHash(value="sha256:" + "a" * 64)
OTHER_DIGEST: ContentHash = ContentHash(value="sha256:" + "b" * 64)


def _id(number: int) -> RecordId:
    return RecordId(value=f"01JCKMNP{number:018d}")


def _candidate(
    number: int,
    status: RecordStatusEnum = RecordStatusEnum.PROPOSED,
    *,
    content: GraphContent | None = OLD,
    created: datetime = T0,
    digests: tuple[ContentHash, ...] = (OTHER_DIGEST,),
    head_revision: int = 1,
) -> ImportCandidate:
    return ImportCandidate(
        id=_id(number),
        status=status,
        created_at=created,
        head_revision=head_revision,
        head_content=content,
        head_file_digests=digests,
        holds_record_id=False,
    )


def _decide(
    candidates: tuple[ImportCandidate, ...] = (),
    *,
    id_holder: str = "none",
    on_change: str = "update",
    can_link: bool = False,
    content: GraphContent = INCOMING,
    digest: ContentHash = DIGEST,
) -> ImportDecision:
    return ImportDecisionPolicy().decide(
        candidates=candidates,
        id_holder=id_holder,
        content=content,
        digest=digest,
        on_change=on_change,
        can_link_successor=can_link,
    )


def _kind(decision: ImportDecision) -> str:
    return str(decision.kind)


@pytest.mark.parametrize("candidates", [(), (_candidate(1),)])
def test_row_1_an_id_held_by_another_record_type_is_an_id_conflict(
    candidates: tuple[ImportCandidate, ...],
) -> None:
    decision = _decide(candidates, id_holder="other")

    assert _kind(decision) == "id_conflict"
    assert decision.target is None


def test_row_1_wins_over_unchanged_content() -> None:
    decision = _decide((_candidate(1, content=INCOMING),), id_holder="other")

    assert _kind(decision) == "id_conflict"


@pytest.mark.parametrize("id_holder", ["none", "graph_knowledge"])
def test_row_2_no_candidate_creates(id_holder: str) -> None:
    decision = _decide((), id_holder=id_holder)

    assert _kind(decision) == "create"
    assert decision.target is None


def test_row_3_equal_title_and_body_is_unchanged_with_the_target() -> None:
    decision = _decide((_candidate(1, content=INCOMING),), on_change="update")

    assert _kind(decision) == "unchanged"
    assert decision.target is not None and decision.target.id == _id(1)


def test_row_3_ignores_the_digest_and_the_status() -> None:
    decision = _decide(
        (_candidate(1, RecordStatusEnum.RETRACTED, content=INCOMING, digests=()),),
        on_change="report",
    )

    assert _kind(decision) == "unchanged"


def test_row_3_does_not_match_when_only_the_title_differs() -> None:
    other_title = GraphContent(title="Other", body=INCOMING.body)

    decision = _decide((_candidate(1, content=other_title),), on_change="report")

    assert _kind(decision) == "changed"


def test_row_4_a_digest_cited_by_the_head_is_unchanged_whatever_the_text() -> None:
    decision = _decide((_candidate(1, content=OLD, digests=(OTHER_DIGEST, DIGEST)),))

    assert _kind(decision) == "unchanged"
    assert decision.target is not None and decision.target.id == _id(1)


def test_row_4_matches_a_file_owned_head_that_has_no_text() -> None:
    decision = _decide((_candidate(1, content=None, digests=(DIGEST,)),))

    assert _kind(decision) == "unchanged"


def test_row_3_does_not_match_a_head_without_graph_content() -> None:
    decision = _decide((_candidate(1, content=None),), on_change="report")

    assert _kind(decision) == "changed"


def test_row_5_report_mode_reports_a_change_for_every_open_status() -> None:
    for status in RecordStatusEnum:
        decision = _decide((_candidate(1, status),), on_change="report")

        assert _kind(decision) == "changed", status


def test_row_5_wins_over_row_9_so_a_closed_target_is_only_reported() -> None:
    decision = _decide((_candidate(1, RecordStatusEnum.RETRACTED),), on_change="report")

    assert _kind(decision) == "changed"


@pytest.mark.parametrize("can_link", [False, True])
def test_row_6_a_proposed_target_is_revised(can_link: bool) -> None:
    decision = _decide((_candidate(1, head_revision=3),), can_link=can_link)

    assert _kind(decision) == "revise"
    assert decision.target is not None and decision.target.head_revision == 3


def test_row_7_an_accepted_target_with_a_proposer_gets_a_linked_successor() -> None:
    decision = _decide((_candidate(1, RecordStatusEnum.ACCEPTED),), can_link=True)

    assert _kind(decision) == "successor_linked"
    assert decision.target is not None and decision.target.id == _id(1)


def test_row_8_an_accepted_target_without_a_proposer_gets_an_unlinked_successor() -> None:
    decision = _decide((_candidate(1, RecordStatusEnum.ACCEPTED),), can_link=False)

    assert _kind(decision) == "successor_unlinked"
    assert decision.target is not None and decision.target.id == _id(1)


@pytest.mark.parametrize("status", [RecordStatusEnum.SUPERSEDED, RecordStatusEnum.RETRACTED])
def test_row_9_a_closed_target_blocks(status: RecordStatusEnum) -> None:
    decision = _decide((_candidate(1, status),))

    assert _kind(decision) == "target_closed"
    assert decision.target is not None


def test_a_closed_target_with_equal_content_is_unchanged_not_blocked() -> None:
    decision = _decide((_candidate(1, RecordStatusEnum.RETRACTED, content=INCOMING),))

    assert _kind(decision) == "unchanged"


def test_rows_3_and_4_win_over_row_5_and_row_3_wins_over_row_4() -> None:
    by_text = _decide((_candidate(1, content=INCOMING, digests=()),), on_change="report")
    by_digest = _decide((_candidate(1, content=OLD, digests=(DIGEST,)),), on_change="report")
    by_both = _decide((_candidate(1, content=INCOMING, digests=(DIGEST,)),), on_change="report")
    neither = _decide((_candidate(1, content=OLD, digests=(OTHER_DIGEST,)),), on_change="report")

    assert [_kind(d) for d in (by_text, by_digest, by_both, neither)] == [
        "unchanged",
        "unchanged",
        "unchanged",
        "changed",
    ]


def test_target_is_the_newest_live_candidate() -> None:
    older = _candidate(1, created=T0)
    newer = _candidate(2, created=T0 + timedelta(hours=1))

    decision = _decide((newer, older))

    assert decision.target is not None and decision.target.id == _id(2)


def test_a_newer_proposed_successor_is_preferred_over_the_accepted_record_it_replaces() -> None:
    accepted = _candidate(1, RecordStatusEnum.ACCEPTED, created=T0)
    successor = _candidate(2, RecordStatusEnum.PROPOSED, created=T0 + timedelta(hours=1))

    decision = _decide((accepted, successor))

    assert _kind(decision) == "revise"
    assert decision.target is not None and decision.target.id == _id(2)


def test_creation_time_ties_are_broken_by_the_greatest_id() -> None:
    decision = _decide((_candidate(1), _candidate(3), _candidate(2)))

    assert decision.target is not None and decision.target.id == _id(3)


def test_a_live_candidate_is_preferred_over_a_newer_closed_one() -> None:
    live = _candidate(1, RecordStatusEnum.PROPOSED, created=T0)
    closed = _candidate(2, RecordStatusEnum.RETRACTED, created=T0 + timedelta(days=1))

    decision = _decide((closed, live))

    assert _kind(decision) == "revise"
    assert decision.target is not None and decision.target.id == _id(1)


def test_with_only_closed_candidates_the_newest_of_any_status_is_the_target() -> None:
    old = _candidate(1, RecordStatusEnum.SUPERSEDED, created=T0)
    new = _candidate(2, RecordStatusEnum.RETRACTED, created=T0 + timedelta(hours=1))

    decision = _decide((old, new))

    assert _kind(decision) == "target_closed"
    assert decision.target is not None and decision.target.id == _id(2)


def test_a_retracted_record_found_by_locator_is_never_silently_recreated() -> None:
    decision = _decide((_candidate(1, RecordStatusEnum.RETRACTED),), on_change="update")

    assert _kind(decision) != "create"


def test_the_choice_does_not_depend_on_the_order_of_the_candidates() -> None:
    candidates = (
        _candidate(1, RecordStatusEnum.ACCEPTED, created=T0),
        _candidate(2, RecordStatusEnum.PROPOSED, created=T0 + timedelta(hours=1)),
        _candidate(3, RecordStatusEnum.SUPERSEDED, created=T0 + timedelta(hours=2)),
    )

    forward = _decide(candidates)
    backward = _decide(tuple(reversed(candidates)))

    assert forward.target == backward.target
    assert forward.target is not None and forward.target.id == _id(2)
