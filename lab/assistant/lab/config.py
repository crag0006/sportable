"""Where the lab talks to. Every address and credential is an environment variable.

Nothing here carries a host, a key or a password. Set the variables in your
shell (or a git-ignored ``.env`` you source) before running any module; a
missing one fails with a sentence naming it, never with a connection error.
"""

import os


def require(name: str) -> str:
    """The value of a required environment variable, or a plain error naming it."""
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"{name} is not set. See lab/assistant/README.md for the variables.")
    return value


# The SportAble API the tools call (a local uvicorn by default).
API_BASE = os.environ.get("API_BASE", "http://127.0.0.1:8000/api/v1")

# openai: any OpenAI-compatible chat server (LLM_BASE, e.g. llama.cpp).
# anthropic: the Anthropic API; ANTHROPIC_API_KEY is read by the SDK itself.
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "openai")
LLM_BASE = os.environ.get("LLM_BASE", "")
LLM_MODEL = os.environ.get("LLM_MODEL", "")  # openai: empty takes the first id from /v1/models
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-haiku-5-5")
# xhigh | medium | low for the Qwen chat template; the Anthropic path ignores it.
REASONING_EFFORT = os.environ.get("REASONING_EFFORT", "medium")
MAX_ROUNDS = int(os.environ.get("MAX_ROUNDS", "3"))
# The final_answer tool input (answer plus actions) needs room: Haiku hit a 900
# token ceiling three times on 10 Oct and returned a truncated tool input.
MAX_TOKENS = int(os.environ.get("MAX_TOKENS", "2048"))

# An OpenAI-compatible /v1/embeddings server (EMBED_BASE), 1024 dimensions.
EMBED_BASE = os.environ.get("EMBED_BASE", "")
# What the request names and how stored rows are tagged.
EMBED_MODEL = os.environ.get("EMBED_MODEL", "bge-m3")
EMBED_MODEL_ID = os.environ.get("EMBED_MODEL_ID", "bge-m3-fp16")
EMBED_DIMENSIONS = 1024

# The PostGIS serving store (programs, venues) and the pgvector store (chunks).
# In production both are one database; the lab keeps them apart.
DATABASE_URL = os.environ.get("DATABASE_URL", "")
VECTOR_DATABASE_URL = os.environ.get("VECTOR_DATABASE_URL", "")

# tool: the model calls search_program_descriptions when it decides to.
# always: the user's words are embedded and the passages injected before the
#         model runs, every turn, and the tool is withdrawn.
# both: injected AND the tool stays available for a refined query.
RETRIEVAL_MODE = os.environ.get("RETRIEVAL_MODE", "tool")
RETRIEVAL_TOP_K = int(os.environ.get("RETRIEVAL_TOP_K", "4"))
# Calibrated for bge-m3 on 2026-10-10: unrelated questions score 0.50 to 0.56
# against this corpus, relevant ones 0.61 to 0.71. Titan needs its own value.
RELEVANCE_FLOOR = float(os.environ.get("RELEVANCE_FLOOR", "0.58"))
# Dense cosine plus a lexical leg, fused by reciprocal rank (see retrieval.py).
RETRIEVAL_HYBRID = os.environ.get("RETRIEVAL_HYBRID", "1") == "1"
# How far below the dense floor a lexical hit may sit and still be returned.
LEXICAL_MARGIN = float(os.environ.get("LEXICAL_MARGIN", "0.05"))
# Which lexical leg: "bm25" (lab.bm25, best in the 10 Oct ablation) or "tsrank".
RETRIEVAL_LEXICAL = os.environ.get("RETRIEVAL_LEXICAL", "bm25")
# A BM25 hit below the dense floor is kept when its score is at least this share
# of the query's maximum attainable score (IDF-weighted), or this softer share
# with the dense similarity within LEXICAL_MARGIN of the floor. Relevant hits
# scored 0.45 to 0.63, off-topic ones 0.10 to 0.29 on the 10 Oct probe set.
BM25_RATIO_FLOOR = float(os.environ.get("BM25_RATIO_FLOOR", "0.40"))
BM25_RATIO_SOFT = float(os.environ.get("BM25_RATIO_SOFT", "0.30"))
