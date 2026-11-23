"""The `--vault-source` option of the NFR-005 harness (the only place a real vault may be named).

Run it explicitly, naming this folder so pytest loads this conftest before parsing options:

    uv run pytest tests/measurement -m measurement --vault-source <path to a vault>

Without the option the harness skips, so the default run and `make check` never touch a vault.
"""

from pathlib import Path

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register `--vault-source`."""
    parser.addoption(
        "--vault-source",
        action="store",
        default=None,
        help="Path of a vault to measure the import against; only ever read and copied.",
    )
    parser.addoption(
        "--discovery-latency",
        action="store_true",
        default=False,
        help="Also run the NFR-004 overlay latency benchmark (100 sequential processes).",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Skip the harness before any fixture runs, so no container is started for nothing."""
    if config.getoption("--vault-source", default=None) is not None:
        return
    skip = pytest.mark.skip(
        reason="--vault-source was not given; the NFR-005 harness runs on request"
    )
    for item in items:
        if item.get_closest_marker("measurement") is not None:
            item.add_marker(skip)


@pytest.fixture
def vault_source(request: pytest.FixtureRequest) -> Path:
    """The folder given with `--vault-source`; skips the test when it was not given."""
    value: str | None = request.config.getoption("--vault-source", default=None)
    if value is None:
        pytest.skip("--vault-source was not given; the NFR-005 harness only runs on request")
    source: Path = Path(value)
    if not source.is_dir():
        pytest.fail(f"--vault-source is not a folder: {source}")
    return source


@pytest.fixture
def discovery_latency(request: pytest.FixtureRequest) -> None:
    """Skip the NFR-004 latency benchmark unless `--discovery-latency` was given."""
    if not request.config.getoption("--discovery-latency"):
        pytest.skip("--discovery-latency was not given; the NFR-004 benchmark runs on request")
