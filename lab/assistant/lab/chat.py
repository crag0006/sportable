"""Drive the local model through the tool loop and print what happened.

uv run python -m lab.chat --question "Where can I play basketball near Preston?"
uv run python -m lab.chat --gold            # the built-in question set
uv run python -m lab.chat --question "..." --venue-id BANYUL12841
"""

import argparse
import json
import sys
import time

from openai import OpenAI

from lab import config
from lab.builder import build_response
from lab.prompt import system_prompt
from lab.tools import FINAL_TOOL, TOOLS, run_tool

sys.stdout.reconfigure(encoding="utf-8")  # the Windows console otherwise mangles the model's dashes

GOLD = [
    "Where can I play basketball near Preston with an accessible toilet?",
    "Is there accessible parking at Olympic Leisure Centre in West Heidelberg?",
    "What is on in Darebin on Saturdays?",
    "Which swimming programs are there for adults with a disability near Geelong?",
    "Can you recommend a good physiotherapist for my knee?",
    "Is netball played anywhere near Prestn?",
]


def _client() -> tuple[OpenAI, str]:
    """The OpenAI-compatible client and the model id to send."""
    client = OpenAI(base_url=config.require("LLM_BASE"), api_key="local")
    model = config.LLM_MODEL or client.models.list().data[0].id
    return client, model


def _final_from_text(text: str) -> dict:
    """A final_answer dict from plain text; the local model sometimes writes the JSON as content."""
    stripped = text.strip()
    if stripped.startswith("{") and '"answer"' in stripped:
        try:
            parsed = json.loads(stripped)
            if isinstance(parsed, dict) and "answer" in parsed:
                parsed.setdefault("kind", "answer")
                for key in ("venue_ids", "event_ids", "actions", "suggested_questions"):
                    parsed.setdefault(key, [])
                return parsed
        except json.JSONDecodeError:
            pass
    return {
        "kind": "answer",
        "answer": text,
        "venue_ids": [],
        "event_ids": [],
        "actions": [],
        "suggested_questions": [],
    }


def _assistant_message(msg) -> dict:
    """The assistant turn as a dict the server accepts back, reasoning kept."""
    out: dict = {"role": "assistant", "content": msg.content or ""}
    if msg.tool_calls:
        out["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.function.name, "arguments": tc.function.arguments},
            }
            for tc in msg.tool_calls
        ]
    reasoning = getattr(msg, "reasoning_content", None) or getattr(msg, "reasoning", None)
    if reasoning:
        out["reasoning_content"] = reasoning
    return out


def ask(question: str, context: dict | None = None, history: list[dict] | None = None) -> dict:
    """One assistant request: the loop, capped at MAX_ROUNDS tool rounds."""
    client, model = _client()
    started = time.perf_counter()
    tools_called: list[str] = []
    tool_payloads: list[str] = []
    passages: list[dict] | None = None
    tools = TOOLS
    if config.RETRIEVAL_MODE in ("always", "both"):
        # Passive retrieval: the user's own words, embedded, before the model runs.
        from lab.retrieval import search_chunks

        found = search_chunks(question)
        passages = found["passages"]
        tool_payloads.append(json.dumps(found, ensure_ascii=False))
        tools_called.append(f"[passive]search_chunks({len(passages)} passages)")
        if config.RETRIEVAL_MODE == "always":
            tools = [t for t in TOOLS if t["function"]["name"] != "search_program_descriptions"]
    messages: list[dict] = [{"role": "system", "content": system_prompt(context, passages=passages)}]
    messages.extend(history or [])
    messages.append({"role": "user", "content": question})

    tools = [*tools, FINAL_TOOL]
    rounds = 0
    final: dict | None = None
    text_answer = ""
    while True:
        # At the cap the model may only call final_answer. llama.cpp accepts a
        # named function in tool_choice; if it does not, fall back to plain text.
        capped = rounds >= config.MAX_ROUNDS
        choice: str | dict = {"type": "function", "function": {"name": "final_answer"}} if capped else "auto"
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=messages,
                tools=tools,
                tool_choice=choice,
                temperature=0.2,
                max_tokens=config.MAX_TOKENS,
                extra_body={"reasoning_effort": config.REASONING_EFFORT},
            )
        except Exception:
            if not capped:
                raise
            resp = client.chat.completions.create(
                model=model,
                messages=messages,
                tools=tools,
                tool_choice="none",
                temperature=0.2,
                max_tokens=config.MAX_TOKENS,
                extra_body={"reasoning_effort": config.REASONING_EFFORT},
            )
        msg = resp.choices[0].message
        messages.append(_assistant_message(msg))
        finals = [tc for tc in (msg.tool_calls or []) if tc.function.name == "final_answer"]
        if finals:
            try:
                final = json.loads(finals[0].function.arguments)
            except json.JSONDecodeError:
                final = {"kind": "answer", "answer": finals[0].function.arguments}
            break
        if not msg.tool_calls or capped:
            text_answer = msg.content or ""
            break
        rounds += 1
        for tc in msg.tool_calls:
            result = run_tool(tc.function.name, tc.function.arguments)
            tools_called.append(f"{tc.function.name}({tc.function.arguments})")
            tool_payloads.append(result)
            print(f"   -> {tc.function.name} {tc.function.arguments}  [{len(result)} chars]")
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})
    if final is None:
        final = _final_from_text(text_answer)
    response = build_response(final, tools_called, tool_payloads)
    return {
        "answer": response["answer"],
        "raw_answer": final.get("answer", ""),
        "final": final,
        "response": response,
        "rounds": rounds,
        "tools": tools_called,
        "tool_payloads": tool_payloads,
        "elapsed_s": round(time.perf_counter() - started, 1),
        # The local server reports a file path; the family name is enough for any report.
        "model": "qwen3.8-flash-next-local" if "qwen" in model.lower() else model,
        "retrieval_mode": config.RETRIEVAL_MODE,
    }


def main() -> None:
    """CLI entry point."""
    p = argparse.ArgumentParser()
    p.add_argument("--question")
    p.add_argument("--gold", action="store_true")
    p.add_argument("--venue-id")
    p.add_argument("--event-id")
    p.add_argument("--location")
    args = p.parse_args()
    context = {
        k: v
        for k, v in {
            "venue_id": args.venue_id,
            "event_id": args.event_id,
            "location": args.location,
        }.items()
        if v
    }
    questions = GOLD if args.gold else [args.question or GOLD[0]]
    for q in questions:
        print(f"\n=== Q: {q}")
        out = ask(q, context or None)
        print(f"--- {out['rounds']} round(s), {out['elapsed_s']} s, tools: {len(out['tools'])}")
        print(out["answer"])
    print()


if __name__ == "__main__":
    main()
