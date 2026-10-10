"""``POST /api/v1/assistant`` (contract v0.3 section 8) over a scripted model.

The fake model plays back a script of replies: tool calls, then a final
answer. The tools run for real over the in-memory repositories, so what the
builder whitelists is what the tools returned.
"""

import copy
import json
from collections.abc import Iterator
from typing import Any

import pytest
from app.api.deps import get_chat_model, get_chunk_repository, get_embedding_model
from app.gateways.protocols import ModelReply, ModelUnavailableError, ToolCall
from app.main import app
from app.repositories.protocols import ChunkRow
from app.services.assistant.builder import Call, scrub, seen_in
from app.services.assistant.prompt import CAPABILITY_MESSAGE
from fastapi.testclient import TestClient

ASSISTANT = "/api/v1/assistant"


def tool_use(name: str, **args: Any) -> ModelReply:
    """A reply that calls one tool."""
    call = ToolCall(id=f"call-{name}", name=name, input=args)
    return ModelReply(
        text="",
        tool_calls=(call,),
        stop_reason="tool_use",
        content=[{"type": "tool_use", "id": call.id, "name": name, "input": args}],
        input_tokens=100,
        output_tokens=20,
    )


def final(answer: str, **fields: Any) -> ModelReply:
    """A reply that calls final_answer."""
    args = {
        "kind": "answer",
        "answer": answer,
        "venue_ids": [],
        "event_ids": [],
        "actions": [],
        "suggested_questions": [],
    }
    args.update(fields)
    return tool_use("final_answer", **args)


class ScriptedModel:
    """Plays back replies in order and records what it was asked."""

    def __init__(self, replies: list[ModelReply]) -> None:
        self.replies = list(replies)
        self.requests: list[dict[str, Any]] = []

    def complete(self, **kwargs: Any) -> ModelReply:
        self.requests.append(copy.deepcopy(kwargs))  # the loop mutates its message list
        if not self.replies:
            raise ModelUnavailableError("script exhausted")
        return self.replies.pop(0)


class FakeChunks:
    """Two passages about the PlayOn program."""

    def __init__(self) -> None:
        self.last_ratios: dict[tuple[str, int], float] = {}

    def search(
        self, embedding: list[float], question: str, model_id: str, limit: int
    ) -> list[ChunkRow]:
        self.last_ratios = {("aaaplay:25089", 0): 0.6}
        return [
            ChunkRow(
                "aaaplay:25089",
                0,
                "Sessions run on Wednesday evenings from 6:30 pm to 8:00 pm.",
                "DS-09",
                0.71,
                True,
            ),
            ChunkRow("aaaplay:25086", 0, "A cycling program in Geelong.", "DS-09", 0.30, False),
        ]

    def titles(self, program_ids: list[str]) -> dict[str, tuple[str, str | None]]:
        return {"aaaplay:25089": ("PlayOn", "https://aaaplay.org.au/activity/playon/")}


class FakeEmbeddings:
    def embed(self, text: str) -> list[float]:
        return [0.0] * 1024


@pytest.fixture
def scripted(client: TestClient) -> Iterator[ScriptedModel]:
    """Install a scripted model, fake embeddings and a fake chunk index for one test."""
    model = ScriptedModel([])
    app.dependency_overrides[get_chat_model] = lambda: model
    app.dependency_overrides[get_embedding_model] = FakeEmbeddings
    app.dependency_overrides[get_chunk_repository] = FakeChunks
    yield model
    for dep in (get_chat_model, get_embedding_model, get_chunk_repository):
        app.dependency_overrides.pop(dep, None)


def ask(client: TestClient, question: str, **body: Any) -> dict[str, Any]:
    response = client.post(ASSISTANT, json={"question": question, **body})
    assert response.status_code == 200, response.text
    return response.json()


# ---------------------------------------------------------------- the gate
def test_out_of_scope_is_refused_without_a_model_call(client: TestClient, scripted: ScriptedModel):
    body = ask(client, "Can you recommend a good physiotherapist for my knee?")
    assert body["kind"] == "capability" and body["model_called"] is False
    assert body["answer"] == CAPABILITY_MESSAGE
    assert [link["href"] for link in body["links"]] == ["/venues", "/events"]
    assert body["notice"] == "This conversation is not stored."
    assert scripted.requests == []


def test_request_validation(client: TestClient, scripted: ScriptedModel):
    assert client.post(ASSISTANT, json={}).status_code == 422
    assert client.post(ASSISTANT, json={"question": "x" * 501}).status_code == 422
    too_long = client.post(
        ASSISTANT, json={"question": "hi", "history": [{"role": "user", "content": "a"}] * 7}
    )
    assert too_long.status_code == 422 and too_long.json()["error"]["code"] == "validation_error"
    bad = client.post(ASSISTANT, content="[]", headers={"content-type": "application/json"})
    assert bad.status_code == 422


# ---------------------------------------------------------------- the loop
def test_search_turn_builds_links_cards_trace_and_sources(
    client: TestClient, scripted: ScriptedModel
):
    scripted.replies = [
        tool_use("resolve_location", query="Preston"),
        tool_use(
            "search_venues",
            sport="Basketball",
            location="Preston",
            facilities=["accessible_toilet"],
            distance_m=None,
        ),
        final(
            "Three basketball venues near Preston have an accessible toilet. "
            "See /venues/10432 and https://evil.example/x.",
            kind="results",
            venue_ids=["10432", "11876", "not-seen"],
            actions=[
                {"kind": "venue", "venue_id": "10432"},
                {
                    "kind": "search_venues",
                    "sport": "Basketball",
                    "location": "Preston",
                    "facilities": ["accessible_toilet"],
                    "distance_m": 500,
                },
                {"kind": "venue", "venue_id": "not-seen"},
                {"kind": "directions", "venue_id": "10432", "from": "Preston"},
            ],
            suggested_questions=["Which have parking?", "a", "b", "c"],
        ),
    ]
    body = ask(client, "Where can I play basketball near Preston with an accessible toilet?")
    assert body["kind"] == "results" and body["model_called"] is True and body["partial"] is False
    # the model's own URL and the foreign one are gone; the tool-returned path stays
    assert "evil.example" not in body["answer"] and "/venues/10432" in body["answer"]
    assert [v["id"] for v in body["results"]["venues"]] == ["10432", "11876"]
    assert body["results"]["venues"][0]["facilities"][0]["message"].startswith(
        "Public accessible toilet"
    )
    hrefs = [link["href"] for link in body["links"]]
    assert hrefs == [
        "/venues/10432",
        "/venues?sport=Basketball&suburb=Preston&facilities=accessible_toilet&distance_m=500",
        "/venues/10432/directions?from=Preston",
    ]
    assert body["links"][1]["label"].startswith("See all 3 Basketball venues near Preston")
    assert [t["tool"] for t in body["trace"]] == ["resolve_location", "search_venues"]
    assert body["trace"][0]["summary"] == 'Resolved "Preston" to the centre of Preston.'
    assert "3 found" in body["trace"][1]["summary"] and body["trace"][1]["href"] == hrefs[1]
    assert {s["name"] for s in body["sources"]} >= {"National Public Toilet Map"}
    assert body["suggested_questions"] == ["Which have parking?", "a", "b"]
    # the tool result went back to the model as one user message with one tool_result block
    second = scripted.requests[1]["messages"]
    assert second[-1]["role"] == "user" and second[-1]["content"][0]["type"] == "tool_result"
    assert json.loads(second[-1]["content"][0]["content"])["outcome"] == "resolved"


def test_page_context_reaches_the_prompt_and_get_event_carries_the_calendar(
    client: TestClient, scripted: ScriptedModel
):
    scripted.replies = [
        tool_use("get_event", event_id="aaaplay:25089"),
        final(
            "PlayOn runs on Wednesday evenings; the publisher's description says "
            "6:30 pm to 8:00 pm.",
            event_ids=["aaaplay:25089"],
            actions=[{"kind": "calendar_add", "event_ids": ["aaaplay:25089", "aaaplay:25086"]}],
        ),
    ]
    body = ask(
        client,
        "Add this one to my calendar",
        context={
            "page": "event",
            "event_id": "aaaplay:25089",
            "recent_event_ids": ["aaaplay:25089"],
        },
    )
    assert "event_id aaaplay:25089" in scripted.requests[0]["system"]
    proposal = body["calendar_proposal"]
    # 25086 was never seen this turn, so it is silently dropped
    assert {i["event_id"] for i in proposal["items"]} | {
        n["event_id"] for n in proposal["not_exportable"]
    } == {"aaaplay:25089"}
    detail = client.get("/api/v1/events/aaaplay:25089").json()
    if "calendar" in detail:  # once the calendar block (section 7.7) is merged
        item = proposal["items"][0]
        assert (
            item["calendar"]["exportable"] is True
            and item["calendar"]["time_hint"]["start_local"] == "18:30"
        )
        kinds = [link["kind"] for link in item["links"]]
        assert kinds.count("google_template") == 2 and kinds[-1] == "ics"
        assert proposal["download_all"]["href"] == "/api/v1/events/calendar.ics?ids=aaaplay:25089"
    else:  # before it lands, the proposal says plainly that no entry can be built
        assert (
            proposal["not_exportable"][0]["message"] == "This event cannot be added to a calendar."
        )
        assert "download_all" not in proposal
    # the event card carries its registration and publisher buttons
    assert {link["kind"] for link in body["links"]} >= {"registration", "publisher"}


def test_retrieval_tool_applies_the_floor_and_the_trace_quotes_the_passage(
    client: TestClient, scripted: ScriptedModel
):
    scripted.replies = [
        tool_use(
            "search_program_descriptions", question="Which programs run on Wednesday evenings?"
        ),
        final(
            "The publisher, AAA Play, writes that PlayOn runs on Wednesday evenings.",
            event_ids=["aaaplay:25089"],
        ),
    ]
    body = ask(client, "Which programs run on Wednesday evenings?")
    step = body["trace"][0]
    assert step["summary"] == "Read 1 passage(s) from AAA Play program descriptions."
    assert (
        step["passages"][0]["program_id"] == "aaaplay:25089"
        and step["passages"][0]["href"] == "/events/aaaplay:25089"
    )
    assert {s["name"] for s in body["sources"]} == {"AAA Play activity finder"}
    assert body["results"]["events"][0]["id"] == "aaaplay:25089"
    sent = json.loads(scripted.requests[1]["messages"][-1]["content"][0]["content"])
    assert [p["program_id"] for p in sent["passages"]] == [
        "aaaplay:25089"
    ]  # the 0.30 passage failed the 0.35 floor


def test_round_cap_forces_a_final_answer_and_marks_partial(
    client: TestClient, scripted: ScriptedModel
):
    scripted.replies = [tool_use("list_sports", query="basket")] * 3 + [
        final("Here is what I have.")
    ]
    body = ask(client, "basketball?")
    assert body["partial"] is True and body["answer"] == "Here is what I have."
    assert scripted.requests[-1]["tool_choice"] == {"type": "tool", "name": "final_answer"}
    assert len(body["trace"]) == 3


def test_model_failure_is_kind_unavailable_not_a_500(client: TestClient, scripted: ScriptedModel):
    body = ask(
        client, "Where can I swim near Preston?"
    )  # the script is empty: the model is unreachable
    assert (
        body["kind"] == "unavailable" and body["model_called"] is True and body["partial"] is True
    )
    assert [link["href"] for link in body["links"]] == ["/venues", "/events"]


def test_tool_errors_go_back_to_the_model_as_data(client: TestClient, scripted: ScriptedModel):
    scripted.replies = [
        tool_use("get_venue", venue_id="ZZZ", distance_m=None),
        final("No venue with that id."),
    ]
    ask(client, "Is there a toilet at ZZZ?")
    sent = json.loads(scripted.requests[1]["messages"][-1]["content"][0]["content"])
    assert sent == {"error": "venue_not_found", "message": "No venue with id 'ZZZ'."}


# --------------------------------------------------------------- the builder
def test_scrub_and_seen_in_are_the_link_whitelist():
    calls = [
        Call(
            "get_venue",
            {"venue_id": "1"},
            {"id": "1", "name": "A", "href": "/venues/1", "facilities": []},
        )
    ]
    seen = seen_in(calls)
    assert set(seen.venues) == {"1"} and seen.links == {"/venues/1"}
    text, removed = scrub("Open /venues/1 or /venues/2 or https://x.y/z.", seen.links)
    assert text == "Open /venues/1 or  or ." and removed == ["/venues/2", "https://x.y/z"]
