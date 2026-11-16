"""Briefing limits use only the new retrieval settings namespace."""

import pytest
from pydantic import ValidationError

from noesis.core.configurations.retrieval_settings import RetrievalSettings

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "field",
    [
        "retrieval_briefing_timeout_seconds",
        "retrieval_briefing_max_budget_usd",
        "retrieval_briefing_max_evidence_chars",
    ],
)
@pytest.mark.parametrize("value", [0, -1])
def test_limits_must_be_positive(field: str, value: int) -> None:
    with pytest.raises(ValidationError):
        RetrievalSettings.model_validate({field: value})


def test_defaults_and_new_environment_names(monkeypatch: pytest.MonkeyPatch) -> None:
    defaults = RetrievalSettings()
    assert defaults.retrieval_briefing_timeout_seconds == 60
    assert defaults.retrieval_briefing_max_budget_usd == 0.5
    assert defaults.retrieval_briefing_max_evidence_chars == 24000
    monkeypatch.setenv("NOESIS_RETRIEVAL_BRIEFING_MAX_EVIDENCE_CHARS", "1200")
    monkeypatch.setenv("NOESIS_RECALL_TIMEOUT_SECONDS", "1")
    changed = RetrievalSettings()
    assert changed.retrieval_briefing_max_evidence_chars == 1200
    assert changed.retrieval_briefing_timeout_seconds == 60
