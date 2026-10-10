## 0. Summary and verdict

The Access Assistant was evaluated on 31 questions against two models driving the same tool loop, the same eight tools over the live local API, the same retrieval (dense cosine plus BM25, fused) and the same prompt: **Qwen3.8 Flash-Next** running locally on llama.cpp, and **Claude Haiku 5.5** through the Anthropic API. The local model is in the comparison for one reason: to see whether a model that is not tuned to refuse will still decline to answer from its own knowledge when the prompt and the tools give it nothing. It did.

| | Qwen3.8 Flash-Next (local) | Claude Haiku 5.5 |
|---|---|---|
| Passed | 31 / 31 | 31 / 31 |
| Median latency per question | 20.1 s | 4.9 s |
| Slowest | 34.1 s | 8.7 s |
| Mean tool rounds | 1.39 | 1.61 |
| Answers ending with the structured `final_answer` | 31 / 31 | 31 / 31 |
| Own-knowledge leaks (group D trap phrases) | 0 | 0 |
| Links or distances in an answer that no tool returned | 0 | 0 |
| Links built by the server from tool results | 54 | 36 |
| Tokens for the whole set (input / output / cache reads) | not metered | 81.6k / 25.5k / 292k |

Each model's run is a single pass over the 31 cases, with a small number of cases re-run after three defects found in the first pass were fixed (section 0.2): Qwen A2, F1, G1; Haiku A2, F2, G1, H2. Nothing else was re-run, and no answer was edited. The first-pass files are kept beside the final ones in `results/`.

### 0.1 What the 31 cases cover

| Group | Cases | Tools exercised | What it proves |
|---|---|---|---|
| A discovery | 5 | resolve_location, search_venues, search_events | place resolution, typo handling, venue search with a facility band, event search |
| B venue | 4 | find_venue, get_venue | venue by name, page context instead of search, "no published information" said as such, unrecorded hours |
| C retrieval | 6 | search_program_descriptions | questions only the publishers' descriptions answer, quoted and attributed |
| D knowledge leak | 6 | find_venue, get_venue, search_events | interstate ground, sport rules, phone number, prices, tram routes, a publisher's website: the model must say nothing is published rather than answer from memory |
| E scope | 4 | none, or one failing lookup | refusal without a model round trip, prompt injection, a council name, an unknown id |
| F vocabulary | 2 | list_sports | a misspelt sport ("badmington") and a nickname ("footy") |
| G event detail | 2 | get_event | `event_id` page context: price and registration, weekday and the venue's toilet |
| H grouping | 2 | search_venues | the `not_available` group named correctly; the 1000 m band applied instead of the default |

Every tool is exercised by at least two cases. Checks are mechanical where they can be: every link and every "N m" distance in an answer must appear in a tool result; required and forbidden phrases per case; expected tools called; for G1 the registration link must be in the structured response (links or event card), since answer text carries no URLs by design.

### 0.2 Defects found and fixed during the run

1. **Haiku truncated its structured answer three times.** The `final_answer` tool input (answer plus actions) hit the 900-token ceiling and came back as a partial object (`stop_reason: max_tokens`), leaving an empty answer on F2 and H2 and a cut sentence on A2. Fix: 2048 tokens, and one automatic retry with double the room when `max_tokens` is the stop reason. On Bedrock the same setting is `max_output_tokens` in `ASSISTANT_CONFIG`; 500 (the current default) is too small for this response shape.
2. **Qwen wrote the final JSON as text twice** instead of calling the tool (A2, F1). The loop now parses a JSON object in the content as the final answer. Haiku never did this.
3. **Both models misread the facility band as a venue radius** at least once ("none is within 250 m of the centre of Reservoir"). The tool description and prompt rule 7 now state that `distance_m` is how close a public facility must be to the venue and that venues up to 10 km are always returned. Both models answered correctly on re-run.
4. **Two checker corrections**, not model errors: a negated phrase ("cannot say whether it has an accessible toilet") matched a forbidden phrase; and G1 expected a URL in the answer text after the design had moved every URL out of the text.

### 0.3 What the server now guarantees, independent of the model

- The model's final output is a tool call (`final_answer`) that names venue and event ids and page intents (`actions`); it has no URL field. The server builds `links[]` only from ids it saw in a tool result this turn and from searches it actually ran, labels them, and removes any URL the model still wrote into the text. Across 62 answers, zero links came from the model.
- `trace[]` ("what I checked") is written by the server from each tool call and its counts; retrieval steps quote the passages with their program link, so the user sees the publisher's words the answer drew on.
- `sources[]` are collected from the tool payloads, never from the prose: the local model misspelt a dataset name while quoting it, which the source chips do not inherit.
- Event cards carry their registration and publisher links as buttons, so "how do I register" is answered with a button rather than a URL in a sentence.

### 0.4 Model comparison

- **Grounding is equal.** Neither model stated a facility status, distance, price, phone number, route or rule that a tool had not returned. The no-knowledge rule in the prompt (rule 0) holds on a model that was not trained to refuse.
- **Haiku is four times faster** (4.9 s against 20.1 s median) and writes shorter answers. It also calls one more tool on average, usually `list_sports` before a search, which is harmless.
- **Haiku follows the scope sentence literally.** In the first evaluation it refused a playground question as out of scope; after the scope was widened to "any activity the publisher lists, search before refusing" it answered correctly (C2). Qwen needed no such change.
- **Haiku needs room for structured output**: see defect 1. Qwen never hit the ceiling but sometimes emitted the JSON as text.
- **Cost of the Haiku run**: 81.6k input tokens, 25.5k output tokens and 292k cached-prompt reads for 31 questions, about 2.6k fresh input and 0.8k output per question with the system prompt and tool list cached.

### 0.5 Decisions

1. Production model: Claude Haiku 5.5 on Bedrock, tool mode, `max_output_tokens` 2048, at most 3 tool rounds and 18 s.
2. Retrieval: dense cosine (HNSW) plus BM25 in SQL, reciprocal rank fusion; the cosine floor is measured per embedding model (0.58 for bge-m3 in the lab, Titan v2 to be measured on staging); BM25 acceptance at 40 percent of the query's maximum score.
3. The response contract of API_CONTRACT_v0.3 section 8: `answer` without URLs, `results`, `links`, `sources`, `trace`, `suggested_questions`, `notice`, `model_called`, `partial`.
4. Two API additions for the assistant: venue lookup by name (`GET /venues?q=`) and council names in `/locations/resolve`.
5. This 31-case set is the regression gate: any prompt, tool description or retrieval change is followed by one full run on Haiku before it ships.

### 0.6 Limits of this evaluation

Local data covers Greater Melbourne only (574 suburbs, 317 programs); staging and production hold all of Victoria (529 programs). One pass per model at temperature 0.2 (Qwen) or the API default (Haiku); the numbers are indicative, not statistics. Latency for the local model reflects a 177B mixture-of-experts model at 35 tokens per second on one machine and says nothing about Bedrock. Wording quality was judged by reading all 62 answers (section 6).
