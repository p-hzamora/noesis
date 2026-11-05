# Contributing to noesis

Thanks for helping. This guide gets you from a fresh clone to a pull request.

## Before you start

- Read `README.md` for what noesis does, `CONTEXT.md` for the vocabulary, and
  `docs/architecture.md` plus `docs/adr/` for the design and the decisions behind it.
- For anything bigger than a small fix, open an issue first so we can agree on the
  approach before you spend time on it.
- Be kind. This project follows the [Code of Conduct](CODE_OF_CONDUCT.md).

## Set up

Requirements: Python 3.14+, [uv](https://docs.astral.sh/uv/), and git. The curator needs
the `claude` CLI only if you run it for real; tests use a fake.

```bash
git clone https://github.com/p-hzamora/noesis.git
cd noesis
make init        # uv sync: venv + dev dependencies
make check       # everything CI runs
```

`make` alone lists every target. Useful ones:

| Target | What it does |
|--------|--------------|
| `make check` | lint, format check, mypy --strict, import-linter, tests with the coverage gate |
| `make test` | tests only |
| `make format-fix` | apply ruff format and safe fixes |
| `make run ARGS="doctor --json"` | run the CLI from the source tree |
| `make sandbox` | create `.sandbox/` with its own vault, state and config |

The sandbox never touches your real config, vault, or Claude settings. Use it to try
the hooks and curator by hand.

## Architecture rules

noesis uses DDD, CQRS and hexagonal architecture. The layer rules are enforced by
import-linter (`make imports`) and `tests/architecture/test_layers.py`, so a violation
fails CI.

- Bounded contexts (`capture`, `notes`) never import each other; they share only
  `shared_kernel/contracts/`.
- Dependencies point inward: infrastructure -> application -> domain.
- Application code does no I/O. Ports live in `application/ports/`, adapters in
  `infrastructure/`.
- Nothing below `interfaces/` imports it. Configuration is read only through
  `noesis.core`.
- Delivery code (`interfaces/cli`) holds no business logic: argv, formatting, exit codes.

When a change alters a boundary or adds a context, add or amend an ADR in `docs/adr/`.

## Code style

- Python 3.14, full type hints, `mypy --strict` clean.
- `ruff` for lint and format, line length 100. Run `make format-fix` before committing.
- Imports go through package barrels (`from noesis.exceptions import ...`).
- Tests mirror the source tree under `tests/unit` and `tests/integration`. New behavior
  needs a test; a bug fix needs a test that fails without the fix.

## Commits and pull requests

- Use [Conventional Commits](https://www.conventionalcommits.org/):
  `type(scope): subject` with types `feat`, `fix`, `test`, `refactor`, `docs`, `chore`,
  `style`, `perf`. Example: `fix(capture): ignore commits outside the session worktree`.
- Keep a commit to one concern. Tests go in their own commit or next to the code they cover.
- Branch from `main`, keep your branch rebased on it, and open the PR against `main`.
- Fill in the pull request template. CI (`make check`) must pass.
- Keep PRs small and focused; unrelated cleanups belong in their own PR.

## Reporting bugs and ideas

Use the issue templates. For a bug, include the output of `noesis doctor --json`, the
command you ran, what you expected, and what happened. Remove secrets and private note
content first.

Security problems: do not open a public issue. See [SECURITY.md](SECURITY.md).

## License

By contributing you agree that your contributions are licensed under the [MIT License](LICENSE).
