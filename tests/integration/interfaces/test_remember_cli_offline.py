"""`remember` usage errors exit 2 before any settings or connection; an outage fails closed."""

import pytest
from tests.support.knowledge_cli_support import COMMIT_SOURCE, run_json, use_closed_store

from noesis.interfaces.cli import run

pytestmark = pytest.mark.integration

KNOWLEDGE = [
    "remember",
    "--as",
    "knowledge",
    "--title",
    "T",
    "--subtype",
    "decision",
    "--body",
    "b",
]
EXPERIENCE = ["remember", "--as", "experience", "--body", "It failed."]
SOURCE = ["--source", COMMIT_SOURCE]


@pytest.mark.parametrize(
    "argv",
    [
        pytest.param([*KNOWLEDGE], id="no-source"),
        pytest.param([*KNOWLEDGE, *SOURCE, "--space-wide", "--project", "demo"], id="two-scopes"),
        pytest.param([*EXPERIENCE, *SOURCE, "--title", "T"], id="experience-title"),
        pytest.param([*EXPERIENCE, *SOURCE, "--tag", "a:b"], id="experience-tag"),
        pytest.param([*EXPERIENCE, *SOURCE, "--supersedes", "X"], id="experience-supersedes"),
        pytest.param(["remember", "--as", "knowledge", *SOURCE, "--body", "b"], id="no-title"),
    ],
)
def test_usage_errors_exit_2(argv: list[str]) -> None:
    assert run([*argv, "--json"]) == 2


def test_an_unreachable_store_fails_closed(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    use_closed_store(monkeypatch)

    code, envelope = run_json(capsys, [*KNOWLEDGE, *SOURCE, "--project", "demo"])

    assert code == 1
    assert envelope["error"]["code"] == "INTEGRATION_103_GRAPH_STORE_UNAVAILABLE"  # type: ignore[index]
