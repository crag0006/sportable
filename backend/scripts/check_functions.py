"""Check two code-quality rules over the backend source tree.

Rules (tutor feedback, Iteration 2 review):

1. No function longer than ``MAX_LINES`` lines, counted from the ``def`` line
   to the last line of the body, signature and docstring included.
2. Every function and method carries a docstring.

Usage::

    uv run python scripts/check_functions.py            # report only
    uv run python scripts/check_functions.py --strict   # exit 1 on any finding

Run from ``backend/``. The script obeys its own rules.
"""

from __future__ import annotations

import argparse
import ast
import sys
from dataclasses import dataclass
from pathlib import Path

MAX_LINES = 40
ROOTS = ("app", "handlers", "scripts")
FunctionNode = ast.FunctionDef | ast.AsyncFunctionDef


@dataclass(frozen=True)
class Finding:
    """One rule violation, printed as ``path:line: message``."""

    path: Path
    line: int
    message: str

    def __str__(self) -> str:
        """Format the finding the way editors and CI logs expect."""
        return f"{self.path.as_posix()}:{self.line}: {self.message}"


def _length(node: FunctionNode) -> int:
    """Lines from the ``def`` line to the end of the body, inclusive."""
    end = node.end_lineno or node.lineno
    return end - node.lineno + 1


def _functions(tree: ast.AST) -> list[FunctionNode]:
    """Every function and method in the module, in source order."""
    return [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)]


def check_file(path: Path, base: Path) -> list[Finding]:
    """Findings for one module: long functions and missing docstrings."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    shown = path.relative_to(base)
    findings: list[Finding] = []
    for node in _functions(tree):
        length = _length(node)
        if length > MAX_LINES:
            findings.append(
                Finding(shown, node.lineno, f"{node.name} is {length} lines (max {MAX_LINES})")
            )
        if ast.get_docstring(node) is None:
            findings.append(Finding(shown, node.lineno, f"{node.name} has no docstring"))
    return findings


def source_files(base: Path) -> list[Path]:
    """The Python files under the checked roots, skipping caches and builds."""
    files: list[Path] = []
    for root in ROOTS:
        files.extend(
            p
            for p in (base / root).rglob("*.py")
            if "__pycache__" not in p.parts and "build" not in p.parts
        )
    return sorted(files)


def main(argv: list[str] | None = None) -> int:
    """Run the checks and return the process exit code."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--strict", action="store_true", help="exit 1 when anything is found")
    args = parser.parse_args(argv)

    base = Path(__file__).resolve().parent.parent
    findings = [f for path in source_files(base) for f in check_file(path, base)]
    for finding in findings:
        print(finding)

    long = sum(1 for f in findings if "lines (max" in f.message)
    bare = len(findings) - long
    print(f"\n{long} functions over {MAX_LINES} lines, {bare} without a docstring")
    return 1 if (args.strict and findings) else 0


if __name__ == "__main__":
    sys.exit(main())
