"""Retrieval ablation, no chat model involved: dense only, dense + ts_rank, dense + BM25.

    uv run python -m lab.ablate

Two views per method:
  ranking    on the relevant probes, with no acceptance rule: hit@1, hit@4, MRR
             at program level over the fused top 12
  acceptance with the acceptance rule of lab.retrieval: recall on the relevant
             probes and how many passages the off-topic probes still return
"""

import statistics
import time

from lab import config
from lab.bm25 import bm25_candidates
from lab.retrieval import _keep, _matched, embed, lexical_query, vector_literal, vector_store

# (question, substring of the expected program title)
RELEVANT = [
    ("Which programs mention audible tennis balls?", "Blind Tennis"),
    ("Is there a tennis program for people who are blind or have low vision?", "Blind Tennis"),
    (
        "Is there a playground with Braille and Auslan signs that kids in wheelchairs can use?",
        "Brimbank Park",
    ),
    ("Do any of the Reclink footy programs provide transport to away games?", "Reclink Footy"),
    ("Is there a unified football program run with Melbourne Victory?", "Unified Football"),
    (
        "Is there a gym session with the lights dimmed and the volume turned down for people with sensory conditions?",
        "Quiet hour",
    ),
    ("Where can I try para table tennis?", "Para Table Tennis"),
    ("Is there a free social boccia program on Mondays?", "Boccia"),
    ("Which program lists its 2026 term dates?", "Expression and Movement"),
    ("Is there a non-contact boxing class for people with Parkinson's?", "Parkinson"),
    ("Is there football for people who have had a stroke or a brain injury?", "Para Football"),
    ("Can I do a free trial session of wheelchair tennis?", "Wheelchair Tennis"),
    ("Is there a team sport for people who use a power wheelchair?", "Powerchair"),
    ("Can I go sailing on Wednesdays and Fridays during school terms?", "Sailability"),
    ("Is there goalball for people with low vision?", "Goalball"),
    ("Are there horse-riding events for people with disability?", "Equestrian"),
    ("Is there a surf lifesaving program for kids with disability at Hampton?", "Nippers"),
    ("Is there a chair pilates class in Warburton?", "Pilates"),
]
OFF_TOPIC = [
    "Where can I play basketball near Preston with an accessible toilet?",
    "Is there accessible parking here, and does the toilet need a key?",
    "Is the Sydney Cricket Ground wheelchair accessible?",
    "Can you recommend a good physiotherapist for my knee?",
    "What is on in Rosebud on Mondays?",
    "What is the phone number of Darebin Community Sports Stadium?",
    "What will the weather be in Melbourne tomorrow?",
    "How do I renew my car registration in Victoria?",
]

SQL_DENSE = """
SELECT chunk_id, program_id, chunk_text, 1 - (embedding <=> %(q)s::vector) AS sim,
       row_number() OVER (ORDER BY embedding <=> %(q)s::vector) AS rnk
  FROM program_chunk WHERE embedding_model_id = %(model)s
 ORDER BY embedding <=> %(q)s::vector LIMIT %(cand)s
"""
SQL_TSRANK = """
SELECT chunk_id, ts_rank_cd(to_tsvector('english', chunk_text), to_tsquery('english', %(tsq)s)) AS lex,
       row_number() OVER (ORDER BY ts_rank_cd(to_tsvector('english', chunk_text), to_tsquery('english', %(tsq)s)) DESC) AS rnk
  FROM program_chunk
 WHERE embedding_model_id = %(model)s AND to_tsvector('english', chunk_text) @@ to_tsquery('english', %(tsq)s)
 LIMIT %(cand)s
"""
SQL_CHUNK = "SELECT chunk_id, program_id, chunk_text, 1 - (embedding <=> %(q)s::vector) FROM program_chunk WHERE chunk_id = ANY(%(ids)s)"
SQL_TITLE = "SELECT program_id FROM program_chunk WHERE chunk_id = %(id)s"
CAND = 12


def _fuse(dense: dict, lexical: dict) -> list[int]:
    """Reciprocal rank fusion of two {chunk_id: rank} maps; returns chunk ids best first."""
    ids = set(dense) | set(lexical)
    score = {
        i: (1 / (60 + dense[i]) if i in dense else 0) + (1 / (60 + lexical[i]) if i in lexical else 0) for i in ids
    }
    return sorted(ids, key=lambda i: -score[i])


def run_method(conn, method: str, question: str, titles: dict) -> tuple[list[dict], float]:
    """Fused candidate list for one method: dicts with program, sim, lexical, matched; plus ms."""
    q = vector_literal(embed(question))
    t_embed = time.perf_counter()
    dense_rows = conn.execute(SQL_DENSE, {"q": q, "model": config.EMBED_MODEL_ID, "cand": CAND}).fetchall()
    dense = {r[0]: r[4] for r in dense_rows}
    info = {r[0]: {"program": r[1], "text": r[2], "sim": float(r[3])} for r in dense_rows}
    lexical: dict = {}
    matched: dict = {}
    ratios: dict = {}
    if method == "tsrank":
        tsq = lexical_query(question)
        if tsq:
            for r in conn.execute(SQL_TSRANK, {"tsq": tsq, "model": config.EMBED_MODEL_ID, "cand": CAND}).fetchall():
                lexical[r[0]] = r[2]
    elif method == "bm25":
        for cid, _score, m, rnk, ratio in bm25_candidates(conn, question, CAND):
            lexical[cid] = rnk
            matched[cid] = m
            ratios[cid] = ratio
    order = _fuse(dense, lexical) if method != "dense" else [r[0] for r in dense_rows]
    missing = [i for i in order if i not in info]
    if missing:
        for r in conn.execute(SQL_CHUNK, {"q": q, "ids": missing}).fetchall():
            info[r[0]] = {"program": r[1], "text": r[2], "sim": float(r[3])}
    out = []
    for cid in order:
        d = info[cid]
        if method == "tsrank" and cid in lexical:
            matched[cid] = _matched(lexical_query(question).split(" | "), d["text"])
        out.append(
            {
                **d,
                "lexical": cid in lexical,
                "matched": matched.get(cid, 0),
                "ratio": ratios.get(cid, 0.0),
                "title": titles.get(d["program"], ""),
            }
        )
    return out, (time.perf_counter() - t_embed) * 1000


def keep(method: str, c: dict) -> bool:
    """Acceptance: the retrieval rule, except BM25 judges a lexical hit by its normalised score."""
    if method != "bm25":
        return _keep(c["sim"], c["lexical"], c["matched"])
    if c["sim"] >= config.RELEVANCE_FLOOR:
        return True
    if not c["lexical"]:
        return False
    # Below the dense floor: the chunk must carry a large share of the query's
    # IDF mass. Common words (access, park, toilet) add little; "audibl" adds a lot.
    return c["ratio"] >= BM25_RATIO_FLOOR or (
        c["ratio"] >= BM25_RATIO_SOFT and c["sim"] >= config.RELEVANCE_FLOOR - config.LEXICAL_MARGIN
    )


BM25_RATIO_FLOOR = 0.40
BM25_RATIO_SOFT = 0.30


def main() -> None:
    """Print the two tables."""
    import psycopg

    with psycopg.connect(config.require("DATABASE_URL")) as local:
        titles = dict(local.execute("select program_id, name from program").fetchall())
    methods = ("dense", "tsrank", "bm25")
    with vector_store() as conn:
        rank_stats = {m: {"hit1": 0, "hit4": 0, "rr": [], "ms": []} for m in methods}
        acc_stats = {m: {"recall": 0, "offtopic": 0, "offtopic_q": 0} for m in methods}
        print(f"{'question':64s} " + " ".join(f"{m:>12s}" for m in methods))
        for question, expect in RELEVANT:
            cells = []
            for m in methods:
                cands, ms = run_method(conn, m, question, titles)
                ranks = [i for i, c in enumerate(cands, 1) if expect.lower() in c["title"].lower()]
                first = ranks[0] if ranks else None
                s = rank_stats[m]
                s["hit1"] += first == 1
                s["hit4"] += bool(first and first <= 4)
                s["rr"].append(1 / first if first else 0)
                s["ms"].append(ms)
                kept = [c for c in cands if keep(m, c)][: config.RETRIEVAL_TOP_K]
                acc_stats[m]["recall"] += any(expect.lower() in c["title"].lower() for c in kept)
                cells.append(
                    f"r{first or '-'} k{len(kept)}{'*' if any(expect.lower() in c['title'].lower() for c in kept) else ' '}"
                )
            print(f"{question[:64]:64s} " + " ".join(f"{c:>12s}" for c in cells))
        print("\noff-topic (passages returned after the acceptance rule)")
        for question in OFF_TOPIC:
            cells = []
            for m in methods:
                cands, _ = run_method(conn, m, question, titles)
                kept = [c for c in cands if keep(m, c)][: config.RETRIEVAL_TOP_K]
                acc_stats[m]["offtopic"] += len(kept)
                acc_stats[m]["offtopic_q"] += bool(kept)
                cells.append(f"{len(kept)} " + ",".join(c["title"][:10] for c in kept[:2]))
            print(f"{question[:64]:64s} " + " ".join(f"{c:>12s}" for c in cells))
        n = len(RELEVANT)
        print(
            f"\n{'method':8s} {'hit@1':>6s} {'hit@4':>6s} {'MRR':>6s} {'recall(rule)':>13s} {'offtopic passages':>18s} {'offtopic q with any':>20s} {'median ms':>10s}"
        )
        for m in methods:
            s, a = rank_stats[m], acc_stats[m]
            print(
                f"{m:8s} {s['hit1']:>3d}/{n:<2d} {s['hit4']:>3d}/{n:<2d} {statistics.mean(s['rr']):6.3f} {a['recall']:>7d}/{n:<5d} {a['offtopic']:>18d} {a['offtopic_q']:>14d}/{len(OFF_TOPIC):<5d} {statistics.median(s['ms']):10.0f}"
            )


if __name__ == "__main__":
    main()
