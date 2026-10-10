"""Is the vector store usable? Prints one verdict line per check."""

from lab import config
from lab.retrieval import ensure_store, vector_store


def main() -> None:
    """Extension present, table created, a cosine distance that computes, row counts."""
    with vector_store() as conn:
        row = conn.execute(
            "select default_version, installed_version from pg_available_extensions where name='vector'"
        ).fetchone()
        print(f"vector extension: {row}")
        ensure_store(conn)
        d = conn.execute("select '[1,0,0]'::vector <=> '[0,1,0]'::vector").fetchone()[0]
        print(f"cosine distance [1,0,0] vs [0,1,0] = {d} (expect 1.0)")
        counts = conn.execute(
            "select embedding_model_id, count(*), count(distinct program_id) from program_chunk group by 1"
        ).fetchall()
        print(f"program_chunk rows by model: {counts or 'none yet (run lab.index_programs)'}")
        print(f"embedding server: {config.EMBED_BASE or 'EMBED_BASE not set'}")


if __name__ == "__main__":
    main()
