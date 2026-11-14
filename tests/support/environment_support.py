"""Keep the user's own noesis settings out of every test (NFR-004)."""

import os

import pytest


def drop_noesis_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove every `NOESIS_*` variable, `NOESIS_NEO4J_*` included, for the current test."""
    for name in [name for name in os.environ if name.startswith("NOESIS_")]:
        monkeypatch.delenv(name)
