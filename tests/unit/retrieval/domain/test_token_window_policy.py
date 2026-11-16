"""Q-203 / AC-203: windows of 448 content tokens, 64 overlap, covering every token."""

import pytest

from noesis.bounded_context.retrieval.domain.policies.token_window_policy import (
    MODEL_MAX_TOKENS,
    SPECIAL_TOKENS,
    TokenWindowPolicy,
)

pytestmark = pytest.mark.unit


def covered(token_count: int) -> set[int]:
    return {
        token
        for window in TokenWindowPolicy().windows(token_count)
        for token in range(window.start, window.end)
    }


def test_an_empty_text_has_no_window() -> None:
    assert TokenWindowPolicy().windows(0) == ()


@pytest.mark.parametrize("count", [1, 447, 448, 449, 511, 512, 513, 832, 833, 5_000, 12_345])
def test_every_token_is_covered_and_windows_fit_the_model(count: int) -> None:
    windows = TokenWindowPolicy().windows(count)

    assert covered(count) == set(range(count))
    assert all(window.size + SPECIAL_TOKENS <= MODEL_MAX_TOKENS for window in windows)
    assert windows[-1].end == count
    assert [window.index for window in windows] == list(range(len(windows)))


def test_consecutive_windows_overlap_by_64_and_stride_384() -> None:
    windows = TokenWindowPolicy().windows(1_000)

    assert [(w.start, w.end) for w in windows] == [(0, 448), (384, 832), (768, 1_000)]


def test_a_text_of_one_window_has_exactly_one_window() -> None:
    assert [(w.start, w.end) for w in TokenWindowPolicy().windows(448)] == [(0, 448)]


def test_the_policy_is_deterministic() -> None:
    assert TokenWindowPolicy().windows(3_000) == TokenWindowPolicy().windows(3_000)


@pytest.mark.parametrize(("window", "overlap"), [(0, 0), (10, 10), (10, -1)])
def test_invalid_sizes_are_rejected(window: int, overlap: int) -> None:
    with pytest.raises(ValueError, match="window"):
        TokenWindowPolicy(window=window, overlap=overlap)


def test_custom_window_exposes_its_size() -> None:
    assert TokenWindowPolicy(window=10, overlap=2).window == 10
