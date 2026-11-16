"""AC-203: windowed passages and instructed queries over a fake tokenizer and session."""

import math

import numpy as np
import pytest
from tests.support.retrieval.fake_embedding import (
    CLS,
    PROFILE,
    SEP,
    HashSession,
    WordTokenizer,
    word_id,
)

from noesis.bounded_context.retrieval.application.ports.embedding import EmbedderUnavailableError
from noesis.bounded_context.retrieval.infrastructure.outbound.embedding.onnx_bge_engine import (
    OnnxBgeEngine,
)

pytestmark = pytest.mark.unit

INSTRUCTION_WORDS: int = len(PROFILE.query_instruction.split())


def engine() -> tuple[OnnxBgeEngine, WordTokenizer, HashSession]:
    tokenizer, session = WordTokenizer(), HashSession()
    return OnnxBgeEngine(tokenizer, session, PROFILE), tokenizer, session


def words(count: int, *, prefix: str = "w") -> str:
    return " ".join(f"{prefix}{i}" for i in range(count))


@pytest.mark.parametrize("count", [511, 512, 513, 3_000])
def test_every_token_of_a_long_passage_is_embedded_within_the_model_maximum(count: int) -> None:
    embedder, _, session = engine()

    passage = embedder.embed_passage(words(count))

    assert passage.token_count == count
    assert passage.chunks[-1].token_end == count
    covered = {t for chunk in passage.chunks for t in range(chunk.token_start, chunk.token_end)}
    assert covered == set(range(count))
    widths = [batch["input_ids"].shape[1] for batch in session.inputs]
    assert max(widths) <= 512


def test_a_passage_gets_no_instruction_and_one_cls_sep_pair_per_window() -> None:
    embedder, tokenizer, session = engine()

    embedder.embed_passage("alpha beta")

    assert all(not special for _, special in tokenizer.calls[1:])  # content tokens only
    row = list(session.inputs[0]["input_ids"][0])
    assert row == [CLS, word_id("alpha"), word_id("beta"), SEP]


def test_a_tail_only_phrase_lands_in_the_last_window() -> None:
    embedder, _, session = engine()
    text = words(1_000) + " needle"

    passage = embedder.embed_passage(text)

    last_rows = session.inputs[-1]["input_ids"]
    assert word_id("needle") in {int(v) for v in last_rows.flatten()}
    assert passage.chunks[-1].token_end == 1_001


def test_an_empty_passage_has_no_chunks_and_runs_no_model() -> None:
    embedder, _, session = engine()

    passage = embedder.embed_passage("   ")

    assert passage.chunks == ()
    assert session.inputs == []


def test_a_query_carries_the_instruction_exactly_once_per_window() -> None:
    embedder, _, session = engine()

    vector = embedder.embed_query("lease renewal")

    row = [int(v) for v in session.inputs[0]["input_ids"][0]]
    instruction = [word_id(w) for w in PROFILE.query_instruction.split()]
    assert row == [CLS, *instruction, word_id("lease"), word_id("renewal"), SEP]
    assert math.isclose(sum(v * v for v in vector), 1.0, rel_tol=1e-6)


def test_a_long_query_is_windowed_averaged_and_renormalised() -> None:
    embedder, _, session = engine()

    vector = embedder.embed_query(words(1_200, prefix="q"))

    rows = [r for batch in session.inputs for r in batch["input_ids"]]
    assert len(rows) >= 3
    instruction_id = word_id(PROFILE.query_instruction.split()[0])
    assert all(int(row[1]) == instruction_id for row in rows)
    assert all(np.count_nonzero(row) <= 512 for row in rows)
    assert math.isclose(sum(v * v for v in vector), 1.0, rel_tol=1e-6)


def test_an_empty_query_is_unavailable() -> None:
    embedder, _, _ = engine()

    with pytest.raises(EmbedderUnavailableError, match="empty"):
        embedder.embed_query(" ")


def test_a_tokenizer_without_special_tokens_is_refused() -> None:
    class NoSpecials(WordTokenizer):
        def token_to_id(self, token: str) -> int | None:
            return None

    with pytest.raises(EmbedderUnavailableError, match="CLS"):
        OnnxBgeEngine(NoSpecials(), HashSession(), PROFILE)


@pytest.mark.parametrize("bad", [np.zeros(384), np.full(384, np.nan), np.ones(10)])
def test_invalid_model_vectors_are_refused(bad: np.ndarray) -> None:
    class BadSession(HashSession):
        def run(self, output_names: object, input_feed: dict[str, object]) -> list[object]:
            ids = input_feed["input_ids"]
            hidden = np.zeros((ids.shape[0], ids.shape[1], bad.shape[0]))  # type: ignore[attr-defined]
            hidden[:, 0, :] = bad
            return [hidden]

    embedder = OnnxBgeEngine(WordTokenizer(), BadSession(), PROFILE)

    with pytest.raises(EmbedderUnavailableError):
        embedder.embed_passage("alpha")


def test_the_engine_reports_its_profile() -> None:
    embedder, _, _ = engine()

    assert embedder.profile == PROFILE
    assert INSTRUCTION_WORDS > 0
