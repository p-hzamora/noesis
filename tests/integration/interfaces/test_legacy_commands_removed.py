"""`noesis recall` and `noesis record capture` no longer exist: `search` and `remember` replace them."""

import pytest

from noesis.interfaces.cli import run

pytestmark = pytest.mark.integration


@pytest.mark.parametrize(
    "argv", [["recall", "x"], ["record", "capture"]], ids=["recall", "capture"]
)
def test_legacy_removed(argv: list[str], capsys: pytest.CaptureFixture[str]) -> None:
    assert run(argv) == 2

    err: str = capsys.readouterr().err
    assert "No such command" in err
    assert "Usage:" in err
