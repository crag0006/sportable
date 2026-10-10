"""Re-judge saved runs with the current cases and checks, in place.

    uv run python -m lab.rescore results/eval-qwen-tool-*.json results/eval-haiku-tool-*.json

Answers and tool payloads are never touched; only ``checks`` and ``pass`` are
rewritten, so every run in a report is judged by the same rules.
"""

import glob
import json
import sys
from pathlib import Path

from lab.evaluate import CASES, KEYS_PASS, check

CASE_BY_ID = {c.id: c for c in CASES}


def rescore(path: Path) -> tuple[int, int]:
    """Rewrite one results file; returns (passed, total)."""
    data = json.loads(path.read_text(encoding="utf-8"))
    records = data["records"] if isinstance(data, dict) else data
    passed = 0
    for r in records:
        case = CASE_BY_ID.get(r["case"]["id"])
        if case is None or case.question != r["case"]["question"]:
            continue  # the case changed since this run; leave its verdict alone
        r["checks"] = check(case, r["result"])
        r["pass"] = all(r["checks"][k] for k in KEYS_PASS)
        r["case"] = case.__dict__
        passed += r["pass"]
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return passed, len(records)


def main() -> None:
    """CLI entry point."""
    for pattern in sys.argv[1:]:
        for p in sorted(glob.glob(pattern)):
            passed, total = rescore(Path(p))
            print(f"{p}: {passed}/{total}")


if __name__ == "__main__":
    main()
