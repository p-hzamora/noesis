"""Recall ranking: engine rank position combined with kind, recency and origin."""

from datetime import date, timedelta

import pytest
from pydantic import ValidationError
from tests.support.notes_support import default_catalog

from noesis.bounded_context.notes.domain.policies import RecallRankingPolicy
from noesis.bounded_context.notes.domain.value_objects import (
    NoteKind,
    NoteOriginEnum,
    RecallCandidate,
    RecallWeights,
)

pytestmark = pytest.mark.unit

TODAY: date = date(2026, 11, 5)
WEIGHTS = RecallWeights(kind_weights=default_catalog().recall_weights())


def _kind(name: str) -> NoteKind:
    return NoteKind(value=name)


DECISION: NoteKind = _kind("decision")


def _candidate(
    path: str,
    *,
    rank: int = 0,
    kind: NoteKind | None = DECISION,
    origin: NoteOriginEnum = NoteOriginEnum.MANUAL,
    updated: date | None = TODAY,
) -> RecallCandidate:
    return RecallCandidate(path=path, kind=kind, origin=origin, updated=updated, rank=rank)


def _rank(*candidates: RecallCandidate) -> tuple[str, ...]:
    return RecallRankingPolicy(WEIGHTS).rank(candidates, today=TODAY)


def test_engine_order_stands_when_everything_else_is_equal() -> None:
    assert _rank(_candidate("b", rank=1), _candidate("a", rank=0), _candidate("c", rank=2)) == (
        "a",
        "b",
        "c",
    )


def test_gotcha_and_decision_outrank_glossary_and_run_at_the_same_rank() -> None:
    ranked = _rank(
        _candidate("run", rank=0, kind=_kind("run")),
        _candidate("glossary", rank=0, kind=_kind("glossary")),
        _candidate("decision", rank=0, kind=_kind("decision")),
        _candidate("gotcha", rank=0, kind=_kind("gotcha")),
    )

    assert set(ranked[:2]) == {"decision", "gotcha"}
    assert ranked[2:] == ("glossary", "run")


def test_gotcha_and_decision_weigh_the_same() -> None:
    weights = WEIGHTS

    assert weights.kind_weight(_kind("gotcha")) == weights.kind_weight(_kind("decision"))
    assert weights.kind_weight(_kind("decision")) > weights.kind_weight(_kind("glossary"))
    assert weights.kind_weight(_kind("glossary")) > weights.kind_weight(_kind("run"))


def test_unknown_kind_is_neutral_between_the_extremes() -> None:
    weights = WEIGHTS

    assert (
        weights.kind_weight(_kind("run"))
        <= weights.kind_weight(None)
        <= weights.kind_weight(_kind("gotcha"))
    )
    assert _rank(_candidate("none", kind=None), _candidate("gotcha", kind=_kind("gotcha"))) == (
        "gotcha",
        "none",
    )


def test_manual_outranks_auto_at_the_same_rank() -> None:
    assert _rank(
        _candidate("auto", origin=NoteOriginEnum.AUTO),
        _candidate("manual", origin=NoteOriginEnum.MANUAL),
    ) == ("manual", "auto")


def test_newer_outranks_older() -> None:
    assert _rank(
        _candidate("old", updated=TODAY - timedelta(days=180)),
        _candidate("new", updated=TODAY - timedelta(days=5)),
    ) == ("new", "old")


def test_recency_halves_every_ninety_days_down_to_the_floor() -> None:
    weights = WEIGHTS

    assert weights.recency_weight(0) == 1.0
    assert weights.recency_weight(90) == pytest.approx(0.5)
    assert weights.recency_weight(45) == pytest.approx(0.5**0.5)
    assert weights.recency_weight(180) == weights.recency_floor
    assert weights.recency_weight(10_000) == weights.recency_floor
    assert weights.recency_weight(-30) == 1.0
    assert weights.recency_weight(None) == weights.recency_floor


def test_an_old_run_is_down_weighted_but_never_dropped() -> None:
    ranked = _rank(
        _candidate("run", rank=0, kind=_kind("run"), updated=TODAY - timedelta(days=3650)),
        _candidate("decision", rank=1),
    )

    assert ranked == ("decision", "run")


def test_a_note_outside_the_preferred_area_is_down_weighted_but_kept() -> None:
    inside: RecallCandidate = _candidate("repos/a/inside.md", rank=1)
    outside: RecallCandidate = _candidate("repos/b/outside.md", rank=0).model_copy(
        update={"preferred": False}
    )

    ranked = RecallRankingPolicy(WEIGHTS).rank([outside, inside], today=TODAY)

    assert ranked == ("repos/a/inside.md", "repos/b/outside.md")


def test_every_candidate_comes_back() -> None:
    candidates = [
        _candidate(f"p{i}", rank=i, kind=_kind("run"), updated=None, origin=NoteOriginEnum.AUTO)
        for i in range(30)
    ]

    assert sorted(_rank(*candidates)) == sorted(c.path for c in candidates)


def test_a_much_better_engine_rank_beats_a_better_kind() -> None:
    assert _rank(
        _candidate("strong", rank=0, kind=_kind("run")),
        _candidate("weak", rank=14, kind=_kind("gotcha")),
    ) == ("strong", "weak")


def test_ties_break_by_rank_then_path() -> None:
    weights = RecallWeights(rank_decay=0.0)
    policy = RecallRankingPolicy(weights)

    ranked = policy.rank(
        [_candidate("b", rank=1), _candidate("c", rank=0), _candidate("a", rank=1)],
        today=TODAY,
    )

    assert ranked == ("c", "a", "b")


def test_ranking_is_deterministic_and_takes_today_as_a_parameter() -> None:
    candidates = [_candidate("a", updated=date(2026, 6, 1)), _candidate("b", rank=1)]
    policy = RecallRankingPolicy(WEIGHTS)

    assert policy.rank(candidates, today=TODAY) == policy.rank(candidates, today=TODAY)
    far = TODAY + timedelta(days=5000)
    assert policy.rank([_candidate("a", updated=TODAY), _candidate("b", rank=1)], today=far) == (
        "a",
        "b",
    )


def test_weights_reject_out_of_range_values() -> None:
    with pytest.raises(ValidationError):
        RecallWeights(recency_floor=1.5)
    with pytest.raises(ValidationError):
        RecallWeights(recency_half_life_days=0)


def test_a_candidate_rank_is_never_negative() -> None:
    with pytest.raises(ValidationError):
        _candidate("x", rank=-1)
