"""AC-022: the new Retrieval policies hold no topic vocabulary.

Policies receive text and ids only. A topic word list would make them silently tuned to
today's subjects, so the check is structural rather than a word grep: in each policy
module, no collection literal (set, list, tuple, dict) may hold `MIN_WORDS` or more
string constants, except the grammar stop-word set named in `GRAMMAR_ALLOWLIST`.
Small closed sets of two or three protocol values (a status pair) stay legal; regex
patterns are `re.compile` calls, not collections, and are out of scope. Adding a
second word list, or a list under another name, fails this test.
"""

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.architecture

POLICIES = (
    Path(__file__).resolve().parents[2] / "src/noesis/bounded_context/retrieval/domain/policies"
)
CHECKED = (
    "requirement_extraction_policy.py",
    "coverage_selection_policy.py",
    "load_order_policy.py",
    "endorsement_policy.py",
    "coverage_status_policy.py",
)
MIN_WORDS = 4
GRAMMAR_ALLOWLIST: frozenset[tuple[str, str]] = frozenset(
    {("requirement_extraction_policy.py", "_STOP_WORDS")}
)


def string_collections(tree: ast.AST) -> list[tuple[int, int, str | None]]:
    """(line, string count, assigned name) of each literal collection of strings."""
    names: dict[int, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign | ast.AnnAssign):
            target = node.targets[0] if isinstance(node, ast.Assign) else node.target
            if isinstance(target, ast.Name):
                for child in ast.walk(node.value) if node.value else ():
                    names.setdefault(id(child), target.id)
    found: list[tuple[int, int, str | None]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Set | ast.List | ast.Tuple):
            elements: list[ast.expr] = list(node.elts)
        elif isinstance(node, ast.Dict):
            elements = [key for key in node.keys if key is not None]
        else:
            continue
        count = sum(
            isinstance(item, ast.Constant) and isinstance(item.value, str) for item in elements
        )
        if count:
            found.append((node.lineno, count, names.get(id(node))))
    return found


@pytest.mark.parametrize("module", CHECKED)
def test_policy_defines_no_topic_word_list(module: str) -> None:
    tree = ast.parse((POLICIES / module).read_text())
    offenders = [
        f"{module}:{line} holds {count} string literals"
        for line, count, name in string_collections(tree)
        if count >= MIN_WORDS and (module, name or "") not in GRAMMAR_ALLOWLIST
    ]
    assert not offenders, offenders


def test_guard_detects_a_word_list() -> None:
    tree = ast.parse('TOPICS = frozenset({"python", "docker", "sql", "git"})')
    assert [count for _, count, _ in string_collections(tree)] == [4]
