"""The assistant use case: a bounded tool loop between the model and the services (section 8).

The loop: system prompt plus the question in, ``tool_use`` out, the tool
runs over the services, its result goes back, at most ``max_rounds`` rounds
and ``time_budget_s`` seconds, then a forced ``final_answer``. The builder
turns that final answer and the tool results into the response. Out-of-scope
questions the gate recognises are answered without a model call. Nothing a
user typed is logged: counts and categories only.
"""

import json
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.core.config import Settings
from app.gateways.protocols import ChatModel, ModelReply, ModelUnavailableError, ToolCall
from app.schemas.assistant import AssistantRequest, AssistantResponse, LinkOut
from app.services.assistant.builder import Call, build_response
from app.services.assistant.prompt import CAPABILITY_MESSAGE, system_prompt
from app.services.assistant.tools import FINAL_TOOL, TOOL_DEFS, ToolRunner

log = logging.getLogger("sportable.assistant")

SEARCH_LINKS = [
    LinkOut(kind="search", label="Search venues", href="/venues"),
    LinkOut(kind="search", label="Browse events", href="/events"),
]
UNAVAILABLE_MESSAGE = (
    "The assistant is not available right now. The venue search and the events pages still work."
)
# The gate: questions no tool can answer, refused before any model call (AC6.3.1).
# Conservative on purpose; the model refuses the rest with the same sentence.
OUT_OF_SCOPE = re.compile(
    r"\b(?:physio\w*|doctor|gp|medic\w*|diagnos\w*|prescri\w*|lawyer|legal advice|sue|"
    r"insurance claim|book(?:ing)? (?:a |an |me )|reserve a court|weather|tell me a joke|"
    r"write (?:me )?(?:a )?(?:poem|story|essay)|recipe)\b",
    re.I,
)


def _gate(question: str) -> bool:
    """Whether the question is out of scope without asking the model."""
    return bool(OUT_OF_SCOPE.search(question))


def _final_from(reply: ModelReply) -> dict[str, Any] | None:
    """The ``final_answer`` input when the model called it, else None."""
    for call in reply.tool_calls:
        if call.name == "final_answer":
            return dict(call.input)
    return None


def _text_final(text: str) -> dict[str, Any]:
    """A final answer from plain text (the model answered without the tool, or hit the cap)."""
    stripped = text.strip()
    if stripped.startswith("{") and '"answer"' in stripped:
        try:
            parsed = json.loads(stripped)
            if isinstance(parsed, dict) and "answer" in parsed:
                return {
                    "kind": "answer",
                    "venue_ids": [],
                    "event_ids": [],
                    "actions": [],
                    "suggested_questions": [],
                    **parsed,
                }
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


@dataclass
class Loop:
    """The state of one conversation turn."""

    messages: list[dict[str, Any]]
    calls: list[Call] = field(default_factory=list)
    rounds: int = 0
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass(frozen=True)
class AssistantService:
    """``POST /api/v1/assistant`` over the model gateway and the tool runner."""

    model: ChatModel
    tools: ToolRunner
    settings: Settings
    now: datetime

    def ask(self, request: AssistantRequest) -> AssistantResponse:
        """One turn: gate, loop, build. Never raises for a model failure."""
        if _gate(request.question):
            log.info(
                json.dumps({"event": "ASSISTANT_REFUSED", "reason": "gate", "model_called": False})
            )
            return AssistantResponse(
                kind="capability", answer=CAPABILITY_MESSAGE, links=SEARCH_LINKS, model_called=False
            )
        loop = Loop(
            messages=[
                *({"role": t.role, "content": t.content} for t in request.history),
                {"role": "user", "content": request.question},
            ]
        )
        system = system_prompt(request.context, self.now.date())
        started = time.monotonic()
        try:
            final, partial = self._run(loop, system, started)
        except ModelUnavailableError:
            log.info(
                json.dumps(
                    {
                        "event": "ASSISTANT_UNAVAILABLE",
                        "rounds": loop.rounds,
                        "tools": len(loop.calls),
                    }
                )
            )
            return AssistantResponse(
                kind="unavailable",
                answer=UNAVAILABLE_MESSAGE,
                links=SEARCH_LINKS,
                model_called=True,
                partial=True,
            )
        response = build_response(final, loop.calls, model_called=True, partial=partial)
        self._log(loop, response, started)
        return response

    def _run(self, loop: Loop, system: str, started: float) -> tuple[dict[str, Any], bool]:
        """The bounded loop; returns the final answer and whether a cap cut it short."""
        cfg = self.settings.assistant
        tools = [*TOOL_DEFS, FINAL_TOOL]
        while True:
            capped = loop.rounds >= cfg.max_rounds or time.monotonic() - started > cfg.time_budget_s
            reply = self.model.complete(
                system=system,
                messages=loop.messages,
                tools=tools,
                tool_choice={"type": "tool", "name": "final_answer"}
                if capped
                else {"type": "auto"},
                max_tokens=cfg.max_output_tokens,
            )
            loop.input_tokens += reply.input_tokens
            loop.output_tokens += reply.output_tokens
            loop.messages.append({"role": "assistant", "content": reply.content})
            final = _final_from(reply)
            if final is not None:
                return final, capped
            work = [c for c in reply.tool_calls if c.name != "final_answer"]
            if not work or capped:
                return _text_final(reply.text), capped
            loop.rounds += 1
            loop.messages.append({"role": "user", "content": self._results(work, loop)})

    def _results(self, calls: list[ToolCall], loop: Loop) -> list[dict[str, Any]]:
        """Run every tool call of a round; one ``tool_result`` block each, in one user message."""
        blocks: list[dict[str, Any]] = []
        for call in calls:
            result = self.tools.run(call.name, call.input)
            loop.calls.append(Call(name=call.name, args=dict(call.input), result=result))
            blocks.append(
                {
                    "type": "tool_result",
                    "tool_use_id": call.id,
                    "content": json.dumps(result, ensure_ascii=False),
                }
            )
        return blocks

    def _log(self, loop: Loop, response: AssistantResponse, started: float) -> None:
        """Counts and categories only (AC6.3.5): never the question, never the answer."""
        log.info(
            json.dumps(
                {
                    "event": "ASSISTANT_ANSWERED",
                    "kind": response.kind,
                    "rounds": loop.rounds,
                    "tools": [c.name for c in loop.calls],
                    "elapsed_ms": round((time.monotonic() - started) * 1000),
                    "input_tokens": loop.input_tokens,
                    "output_tokens": loop.output_tokens,
                    "partial": response.partial,
                    "links": len(response.links),
                }
            )
        )
