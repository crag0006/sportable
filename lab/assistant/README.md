# Assistant lab (Epic 6 prototype and test bench)

The prototype behind contract v0.3 section 8, kept as a reference. It is **not part of the backend package**: it has its own `pyproject.toml`, is not imported by `backend/app`, and is not linted or deployed by CI. The production port goes into `backend/app/services/assistant` and the chunk repository, behind the existing handler.

What is here

| Module | What it does |
|---|---|
| `lab/tools.py` | the eight read-only tools as OpenAI-format schemas, each a thin wrapper over the running API, plus `final_answer` |
| `lab/chat.py`, `lab/claude.py` | the same tool loop over an OpenAI-compatible server and over the Anthropic API: scope gate, at most 3 rounds, forced `final_answer` at the cap |
| `lab/builder.py` | the response builder: validates ids and actions against the turn's tool results, builds `links`, `results`, `sources` and the `trace`, removes stray URLs |
| `lab/prompt.py` | the system prompt (rules 0 to 10) |
| `lab/retrieval.py`, `lab/bm25.py` | hybrid retrieval: pgvector cosine plus BM25 in plain SQL, reciprocal rank fusion, the acceptance rule |
| `lab/index_programs.py` | chunk (with `data/derive/chunker.py`) and embed the program descriptions into the vector store |
| `lab/time_hints.py` | the regex layer for clock times in descriptions (contract section 7.7.2) |
| `lab/evaluate.py`, `lab/rescore.py`, `lab/report.py` | the 31-case test set with mechanical checks, re-scoring of saved runs, and the Markdown or HTML report |
| `lab/ablate.py` | the retrieval ablation (dense, dense + ts_rank, dense + BM25) |
| `results/` | every evaluation run (answers, tool calls, payloads), the golden 31 cases, the contract audit |
| `REPORT_2026-10-10.md`, `REPORT_models_2026-10-10.md` | the write-ups of 10 Oct |

Environment variables (no defaults carry a host or a credential)

| Variable | Needed by | Example |
|---|---|---|
| `API_BASE` | the tools | `http://127.0.0.1:8000/api/v1` (default) |
| `LLM_PROVIDER` | the loop | `openai` (default) or `anthropic` |
| `LLM_BASE` | `openai` provider | an OpenAI-compatible `/v1` base URL |
| `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL` | `anthropic` provider | read by the SDK; `claude-haiku-5-5` |
| `EMBED_BASE`, `EMBED_MODEL`, `EMBED_MODEL_ID` | retrieval and indexing | an OpenAI-compatible `/v1` base URL serving a 1024-d model |
| `DATABASE_URL` | tools that read programs directly, `time_hints`, `index_programs` | the PostGIS serving store |
| `VECTOR_DATABASE_URL` | retrieval, `index_programs`, `check_pgvector`, `ablate` | a PostgreSQL with pgvector |
| `RETRIEVAL_MODE`, `RELEVANCE_FLOOR`, `BM25_RATIO_FLOOR` and the others in `lab/config.py` | tuning | see the comments there |

Run

```
cd lab/assistant
uv sync
uv run python -m lab.check_pgvector
uv run python -m lab.index_programs
uv run python -m lab.evaluate --label qwen-tool
LLM_PROVIDER=anthropic ANTHROPIC_MODEL=claude-haiku-5-5 uv run python -m lab.evaluate --label haiku-tool
uv run python -m lab.rescore "results/eval-*.json"
uv run python -m lab.report --out REPORT.md --html REPORT.html results/eval-qwen-final-*.json results/eval-haiku-final-*.json
uv run python -m lab.demo
uv run python -m lab.ablate
uv run python -m lab.time_hints --show 20
```

Privacy and cost notes: the lab never stores or logs a question beyond the local `results/` files you choose to keep; the model answers in `results/` are from the test questions only. The Anthropic key is never written to a file.
