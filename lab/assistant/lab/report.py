"""Render one or more evaluation runs as a Markdown report with a fixed layout.

    uv run python -m lab.report results/eval-qwen-tool-*.json results/eval-qwen-always-*.json
    uv run python -m lab.report --out REPORT_haiku.md results/eval-haiku-tool-*.json

Same sections every time, so a Qwen run and a Haiku run can be read side by side:
  1 setup, 2 summary per run, 3 results by group, 4 case table, 5 knowledge-leak
  detail, 6 answers in full (appendix).
"""

import argparse
import glob
import json
import statistics
import time
from pathlib import Path

KEYS = ("grounded_hrefs", "grounded_numbers", "must_contain", "must_not_contain", "tools_expected")


def model_name(raw: str) -> str:
    """A display name for a model id: the local GGUF path becomes its family name."""
    low = (raw or "").lower()
    if "qwen" in low and "flash-next" in low:
        return "Qwen3.8 Flash-Next (local, llama.cpp, IQ4_XS)"
    if low.startswith("claude-"):
        return raw
    return raw.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]


def load(paths: list[str]) -> list[dict]:
    """The run payloads, oldest first; a bare list (older format) is wrapped."""
    runs = []
    for pattern in paths:
        for p in sorted(glob.glob(pattern)):
            data = json.loads(Path(p).read_text(encoding="utf-8"))
            if isinstance(data, list):
                data = {
                    "run": {
                        "label": Path(p).stem,
                        "timestamp": "",
                        "provider": "?",
                        "model": data[0]["result"].get("model", "?") if data else "?",
                        "retrieval_mode": data[0]["result"].get("retrieval_mode", "?") if data else "?",
                    },
                    "records": data,
                }
            data["path"] = p
            runs.append(data)
    return runs


def _why(checks: dict) -> str:
    """The failing checks of one record as a short phrase."""
    bits = []
    if checks.get("ungrounded_hrefs"):
        bits.append("link not in tool results: " + ", ".join(checks["ungrounded_hrefs"]))
    if checks.get("ungrounded_numbers"):
        bits.append("distance not in tool results: " + ", ".join(checks["ungrounded_numbers"]))
    if checks.get("missing"):
        bits.append("missing: " + ", ".join(checks["missing"]))
    if checks.get("leaked"):
        bits.append("own-knowledge phrase: " + ", ".join(checks["leaked"]))
    if not checks.get("tools_expected", True):
        bits.append("tools: " + ", ".join(checks.get("tools_called", [])) or "none")
    return "; ".join(bits)


def summary_rows(run: dict) -> dict:
    """The headline numbers of one run."""
    recs = run["records"]
    el = [r["result"]["elapsed_s"] for r in recs]
    words = [len(r["result"]["answer"].split()) for r in recs]
    groups: dict[str, list[int]] = {}
    for r in recs:
        g = groups.setdefault(r["case"]["group"], [0, 0])
        g[0] += bool(r["pass"])
        g[1] += 1
    return {
        "passed": sum(bool(r["pass"]) for r in recs),
        "total": len(recs),
        "median_s": statistics.median(el) if el else 0,
        "mean_s": statistics.mean(el) if el else 0,
        "max_s": max(el) if el else 0,
        "rounds": statistics.mean(r["result"]["rounds"] for r in recs) if recs else 0,
        "words": statistics.median(words) if words else 0,
        "leaks": sum(1 for r in recs if r["checks"].get("leaked")),
        "ungrounded": sum(
            1 for r in recs if r["checks"].get("ungrounded_hrefs") or r["checks"].get("ungrounded_numbers")
        ),
        "groups": groups,
    }


def render(runs: list[dict], title: str) -> str:
    """The whole report as Markdown."""
    out = [
        f"# {title}",
        "",
        f"Generated {time.strftime('%Y-%m-%d %H:%M')} by `lab.report`. Checks are mechanical: every link and distance in an answer must appear in a tool result; required and forbidden phrases per case; expected tools. See `lab/evaluate.py` for the cases.",
        "",
    ]
    out += [
        "## 1. Setup",
        "",
        "| Run | Provider | Model | Effort | Retrieval mode | Lexical leg | Dense floor | BM25 ratio floor | Embedding | Max rounds |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for run in runs:
        m = run["run"]
        out.append(
            f"| {m.get('label')} | {m.get('provider')} | {model_name(m.get('model', ''))} | {m.get('reasoning_effort', '')} | {m.get('retrieval_mode')} | {m.get('retrieval_lexical', '')} | {m.get('relevance_floor', '')} | {m.get('bm25_ratio_floor', '')} | {m.get('embedding_model', '')} | {m.get('max_rounds', '')} |"
        )
    out += [
        "",
        "## 2. Summary",
        "",
        "| Run | Passed | Median s | Mean s | Slowest s | Mean tool rounds | Median words | Own-knowledge leaks | Ungrounded links or distances |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    sums = {run["run"]["label"]: summary_rows(run) for run in runs}
    for run in runs:
        s = sums[run["run"]["label"]]
        out.append(
            f"| {run['run']['label']} | {s['passed']} / {s['total']} | {s['median_s']:.1f} | {s['mean_s']:.1f} | {s['max_s']:.1f} | {s['rounds']:.2f} | {s['words']:.0f} | {s['leaks']} | {s['ungrounded']} |"
        )
    groups = sorted({g for s in sums.values() for g in s["groups"]})
    out += [
        "",
        "## 3. Results by group",
        "",
        "| Group | " + " | ".join(run["run"]["label"] for run in runs) + " |",
        "|---|" + "---|" * len(runs),
    ]
    for g in groups:
        out.append(
            f"| {g} | "
            + " | ".join(
                f"{sums[run['run']['label']]['groups'].get(g, [0, 0])[0]} / {sums[run['run']['label']]['groups'].get(g, [0, 0])[1]}"
                for run in runs
            )
            + " |"
        )
    out += ["", "## 4. Cases", ""]
    for run in runs:
        out += [
            f"### {run['run']['label']}",
            "",
            "| Case | Group | Question | Verdict | Rounds | s | Tools | Why |",
            "|---|---|---|---|---|---|---|---|",
        ]
        for r in run["records"]:
            c, res, ch = r["case"], r["result"], r["checks"]
            tools = ", ".join(sorted({t.split("(", 1)[0] for t in res["tools"]}))
            out.append(
                f"| {c['id']} | {c['group']} | {c['question']} | {'pass' if r['pass'] else 'FAIL'} | {res['rounds']} | {res['elapsed_s']} | {tools} | {_why(ch)} |"
            )
        out.append("")
    out += ["## 5. Knowledge-leak and scope detail", ""]
    for run in runs:
        out.append(f"### {run['run']['label']}")
        out.append("")
        for r in run["records"]:
            if r["case"]["group"] in ("knowledge", "scope"):
                first = r["result"]["answer"].strip().split("\n")[0][:220]
                out.append(
                    f'- **{r["case"]["id"]}** {r["case"]["question"]} -> {"pass" if r["pass"] else "FAIL"}; tools {sorted({t.split("(", 1)[0] for t in r["result"]["tools"]})}; opens: "{first}"'
                )
        out.append("")
    out += ["## 6. Answers in full", ""]
    for run in runs:
        out.append(f"### {run['run']['label']}")
        out.append("")
        for r in run["records"]:
            out.append(f"**{r['case']['id']} {r['case']['question']}**  ")
            out.append(f"tools: {r['result']['tools'] or 'none'}  ")
            out.append("")
            out.append(r["result"]["answer"].strip() or "(empty)")
            out.append("")
    return "\n".join(out)


def main() -> None:
    """CLI entry point."""
    p = argparse.ArgumentParser()
    p.add_argument("paths", nargs="+")
    p.add_argument("--out", default="")
    p.add_argument("--title", default="SportAble assistant evaluation")
    p.add_argument(
        "--intro",
        default="",
        help="a Markdown file inserted after the title (hand-written analysis)",
    )
    p.add_argument("--html", default="", help="also write this HTML file")
    args = p.parse_args()
    runs = load(args.paths)
    text = render(runs, args.title)
    if args.intro:
        head, rest = text.split("\n## 1. Setup", 1)
        text = head + "\n" + Path(args.intro).read_text(encoding="utf-8").strip() + "\n\n## 1. Setup" + rest
    out = Path(args.out or f"REPORT_{'_'.join(r['run']['label'] for r in runs)}.md")
    out.write_text(text, encoding="utf-8")
    print(f"wrote {out} ({len(text.split())} words, {len(runs)} run(s))")
    if args.html:
        Path(args.html).write_text(to_html(text, args.title), encoding="utf-8")
        print(f"wrote {args.html}")


CSS = """
body{font-family:Segoe UI,Helvetica,Arial,sans-serif;max-width:1100px;margin:2rem auto;padding:0 1rem;color:#1b1b1b;line-height:1.5}
h1{font-size:1.8rem;border-bottom:2px solid #0B3D66;padding-bottom:.3rem}h2{color:#0B3D66;margin-top:2.2rem}h3{margin-top:1.6rem}
table{border-collapse:collapse;width:100%;margin:1rem 0;font-size:.92rem}th,td{border:1px solid #d0d7de;padding:.4rem .6rem;vertical-align:top;text-align:left}
th{background:#eef3f8}tr:nth-child(even) td{background:#fafbfc}
code{background:#f3f4f6;padding:0 .25rem;border-radius:3px;font-size:.9em}
pre{background:#f3f4f6;padding:.8rem;overflow-x:auto;border-radius:4px}
blockquote{border-left:4px solid #B3541E;margin:0;padding:.2rem 1rem;color:#444}
td:has(> :first-child):empty{background:#fff}
"""


def to_html(markdown_text: str, title: str) -> str:
    """The Markdown report as a standalone HTML page (tables, code, lists)."""
    import markdown

    body = markdown.markdown(markdown_text, extensions=["tables", "fenced_code", "sane_lists"])
    body = body.replace("<td>FAIL</td>", '<td style="color:#b00020;font-weight:600">FAIL</td>').replace(
        "<td>pass</td>", '<td style="color:#1b6e3a">pass</td>'
    )
    head = f'<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{title}</title>'
    return f'<!doctype html><html lang="en"><head>{head}<style>{CSS}</style></head><body>{body}</body></html>'


if __name__ == "__main__":
    main()
