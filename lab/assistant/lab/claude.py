"""The same tool loop over the Anthropic Messages API (Claude Haiku 5.5 and friends).

Mirrors lab.chat.ask: one system prompt (cached), the tools converted from the
OpenAI shape to Anthropic's ``input_schema`` shape, tool_use blocks executed
through lab.tools.run_tool, every tool_result returned in ONE user message, at
most MAX_ROUNDS tool rounds, then a final call with tool_choice none.
"""

import json
import time

from lab import config
from lab.builder import build_response
from lab.prompt import system_prompt
from lab.tools import FINAL_TOOL, TOOLS, run_tool


def anthropic_tools(tools: list[dict]) -> list[dict]:
    """OpenAI function definitions as Anthropic tool definitions."""
    return [
        {
            "name": t["function"]["name"],
            "description": t["function"]["description"],
            "input_schema": t["function"]["parameters"],
        }
        for t in tools
    ]


def ask(question: str, context: dict | None = None, history: list[dict] | None = None) -> dict:
    """One assistant request through Anthropic; same return shape as lab.chat.ask."""
    import anthropic

    client = anthropic.Anthropic()
    started = time.perf_counter()
    tools_called: list[str] = []
    tool_payloads: list[str] = []
    passages: list[dict] | None = None
    tools = TOOLS
    if config.RETRIEVAL_MODE in ("always", "both"):
        from lab.retrieval import search_chunks

        found = search_chunks(question)
        passages = found["passages"]
        tool_payloads.append(json.dumps(found, ensure_ascii=False))
        tools_called.append(f"[passive]search_chunks({len(passages)} passages)")
        if config.RETRIEVAL_MODE == "always":
            tools = [t for t in TOOLS if t["function"]["name"] != "search_program_descriptions"]
    system = [
        {
            "type": "text",
            "text": system_prompt(context, passages=passages),
            "cache_control": {"type": "ephemeral"},
        }
    ]
    messages: list[dict] = [*(history or []), {"role": "user", "content": question}]
    defs = anthropic_tools([*tools, FINAL_TOOL])

    rounds = 0
    final: dict | None = None
    text_answer = ""
    stops: list[str] = []
    usage = {"input": 0, "output": 0, "cache_read": 0}
    while True:
        capped = rounds >= config.MAX_ROUNDS
        choice = {"type": "tool", "name": "final_answer"} if capped else {"type": "auto"}
        resp = client.messages.create(
            model=config.ANTHROPIC_MODEL,
            max_tokens=config.MAX_TOKENS,
            system=system,
            messages=messages,
            tools=defs,
            tool_choice=choice,
        )
        if resp.stop_reason == "max_tokens":
            # A truncated tool input is unusable; one retry with double the room.
            resp = client.messages.create(
                model=config.ANTHROPIC_MODEL,
                max_tokens=config.MAX_TOKENS * 2,
                system=system,
                messages=messages,
                tools=defs,
                tool_choice=choice,
            )
        messages.append(
            {
                "role": "assistant",
                "content": [b.model_dump(exclude_none=True) for b in resp.content],
            }
        )
        stops.append(resp.stop_reason or "")
        usage["input"] += resp.usage.input_tokens
        usage["output"] += resp.usage.output_tokens
        usage["cache_read"] += getattr(resp.usage, "cache_read_input_tokens", 0) or 0
        uses = [b for b in resp.content if b.type == "tool_use"]
        finals = [b for b in uses if b.name == "final_answer"]
        if finals:
            final = dict(finals[0].input)
            break
        if not uses or capped:
            text_answer = "".join(b.text for b in resp.content if b.type == "text")
            break
        rounds += 1
        results = []
        for b in uses:
            arguments = json.dumps(b.input)
            result = run_tool(b.name, arguments)
            tools_called.append(f"{b.name}({arguments})")
            tool_payloads.append(result)
            print(f"   -> {b.name} {arguments}  [{len(result)} chars]")
            results.append({"type": "tool_result", "tool_use_id": b.id, "content": result})
        messages.append({"role": "user", "content": results})
    if final is None:
        final = {
            "kind": "answer",
            "answer": text_answer,
            "venue_ids": [],
            "event_ids": [],
            "actions": [],
            "suggested_questions": [],
        }
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
        "model": config.ANTHROPIC_MODEL,
        "retrieval_mode": config.RETRIEVAL_MODE,
        "stop_reasons": stops,
        "usage": usage,
    }
