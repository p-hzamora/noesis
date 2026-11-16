"""Deterministic token windows that cover a whole text (Q-203)."""

from ..value_objects.token_window import TokenWindow

WINDOW_TOKENS: int = 448
OVERLAP_TOKENS: int = 64
MODEL_MAX_TOKENS: int = 512
SPECIAL_TOKENS: int = 2
CHUNK_POLICY_VERSION: str = "token-windows-448-overlap-64-v1"
QUERY_POLICY_VERSION: str = "instruction-once-windowed-mean-v1"


class TokenWindowPolicy:
    """Splits a token sequence into overlapping windows; every token falls in some window.

    Windows hold at most `window` content tokens and start every `window - overlap` tokens; the
    last window ends at the last token, so a long body's tail is never dropped. The window plus
    the special tokens fits the model's maximum input.

    Args:
        window: Content tokens per window.
        overlap: Tokens shared by two consecutive windows.
    """

    def __init__(self, window: int = WINDOW_TOKENS, overlap: int = OVERLAP_TOKENS) -> None:
        if window <= 0 or not 0 <= overlap < window:
            raise ValueError("a window needs a positive size and an overlap below it")
        self._window: int = window
        self._overlap: int = overlap

    @property
    def window(self) -> int:
        """Content tokens per window."""
        return self._window

    def windows(self, token_count: int) -> tuple[TokenWindow, ...]:
        """The windows of a text of `token_count` content tokens; none for an empty text."""
        if token_count <= 0:
            return ()
        stride: int = self._window - self._overlap
        found: list[TokenWindow] = []
        start: int = 0
        while True:
            end: int = min(start + self._window, token_count)
            found.append(TokenWindow(index=len(found), start=start, end=end))
            if end >= token_count:
                return tuple(found)
            start += stride
