"""Constitution principle 2: no cross-imports between compilers.

Asked by agenteco-needs-compiler-import-guard-v0_1 (operator accepted,
2026-11-13). Reads the source of every Python file under src/rbac_compiler
and fails if any import names another compiler. No shared code.
"""

import ast
from pathlib import Path

SRC = Path(__file__).parent.parent / "src" / "rbac_compiler"
FORBIDDEN = ("sync_compiler", "agent_compile", "image_compile")


def _imported_names(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name
        elif isinstance(node, ast.ImportFrom) and node.module:
            yield node.module


def test_no_other_compiler_is_imported():
    files = sorted(SRC.rglob("*.py"))
    # A moved src/ folder must not read as a pass while checking nothing.
    assert files, f"no Python files found under {SRC} — guard checked nothing"
    offenders = []
    for py in files:
        for name in _imported_names(py):
            root = name.split(".")[0]
            if root in FORBIDDEN:
                offenders.append(f"{py.relative_to(SRC.parent.parent)}: imports {name}")
    assert not offenders, (
        "cross-compiler import (constitution principle 2 — promote shared "
        "logic to a library instead):\n" + "\n".join(offenders)
    )
