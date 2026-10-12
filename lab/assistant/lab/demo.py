"""Show the full response the frontend would receive: answer, links, trace, sources.

uv run python -m lab.demo
uv run python -m lab.demo --question "..." [--venue-id ID]
"""

import argparse
import json
import sys
import time
from pathlib import Path

from lab import config

if config.LLM_PROVIDER == "anthropic":
    from lab.claude import ask
else:
    from lab.chat import ask

sys.stdout.reconfigure(encoding="utf-8")

QUESTIONS = [
    ("Where can I play basketball near Preston with an accessible toilet?", None),
    ("Is there accessible parking at Olympic Leisure Centre in West Heidelberg?", None),
    ("Which programs mention audible tennis balls?", None),
    ("Is the Sydney Cricket Ground wheelchair accessible?", None),
    (
        "How do I get to this venue from Preston, and is there a toilet on the way?",
        {"venue_id": "DAREBI11808"},
    ),
]


def show(question: str, out: dict) -> None:
    """Print one response the way a reviewer would read it."""
    r = out["response"]
    print(f"\n=== {question}")
    print(
        f"kind={r['kind']}  rounds={out['rounds']}  {out['elapsed_s']} s  final_answer={'yes' if out['final'].get('actions') is not None else 'text fallback'}"
    )
    print("\nANSWER\n" + r["answer"])
    print("\nLINKS")
    for link in r["links"]:
        print(f"  [{link['kind']}] {link['label']}  ->  {link['href']}")
    if not r["links"]:
        print("  (none)")
    print("\nWHAT I CHECKED")
    for t in r["trace"]:
        print(f"  {t['step']}. {t['summary']}" + (f"  ({t['href']})" if t.get("href") else ""))
        for p in t.get("passages", []):
            print(f'       "{p["quote"][:120]}..."  {p["title"]}  {p["href"]}')
    print("\nSOURCES")
    for s in r["sources"]:
        print(
            f"  {s['name']}"
            + (f", publisher date {s['publisher_last_updated']}" if s.get("publisher_last_updated") else "")
        )
    print(f"\nRESULTS: {len(r['results']['venues'])} venue card(s), {len(r['results']['events'])} event card(s)")
    print(f"SUGGESTED: {r['suggested_questions']}")
    b = r["builder"]
    if b["urls_removed_from_answer"] or b["actions_dropped"] or b["ids_not_seen"]:
        print(
            f"BUILDER: removed URLs {b['urls_removed_from_answer']}; dropped actions {[d['action'].get('kind') for d in b['actions_dropped']]}; ids not seen {b['ids_not_seen']}"
        )


def main() -> None:
    """CLI entry point; also saves the raw responses for the contract examples."""
    p = argparse.ArgumentParser()
    p.add_argument("--question")
    p.add_argument("--venue-id")
    args = p.parse_args()
    items = [(args.question, {"venue_id": args.venue_id} if args.venue_id else None)] if args.question else QUESTIONS
    samples = []
    for q, ctx in items:
        out = ask(q, ctx)
        show(q, out)
        samples.append(
            {
                "question": q,
                "context": ctx,
                "final_answer": out["final"],
                "response": out["response"],
                "tools": out["tools"],
            }
        )
    Path("results").mkdir(exist_ok=True)
    path = Path("results") / f"response-samples-{config.LLM_PROVIDER}-{time.strftime('%Y%m%d-%H%M%S')}.json"
    path.write_text(json.dumps(samples, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nsaved {path}")


if __name__ == "__main__":
    main()
