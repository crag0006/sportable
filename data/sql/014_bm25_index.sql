-- 014_bm25_index.sql
-- BM25 tables for hybrid retrieval. Shapes match lab/assistant/lab/bm25.py (k1 = 1.2, b = 0.75).
-- Rebuilt whole by derive/bm25_index.py after every chunk run; nothing is written by hand.
BEGIN;

CREATE TABLE IF NOT EXISTS public.chunk_term (
    chunk_id bigint  NOT NULL,
    lexeme   text    NOT NULL,
    tf       integer NOT NULL,
    CONSTRAINT chunk_term_pkey PRIMARY KEY (chunk_id, lexeme),
    CONSTRAINT chunk_term_chunk_fkey FOREIGN KEY (chunk_id)
        REFERENCES public.program_description_chunk (chunk_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS chunk_term_lexeme ON public.chunk_term (lexeme);

CREATE TABLE IF NOT EXISTS public.chunk_stats (
    chunk_id bigint PRIMARY KEY,
    len      double precision NOT NULL,
    CONSTRAINT chunk_stats_chunk_fkey FOREIGN KEY (chunk_id)
        REFERENCES public.program_description_chunk (chunk_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS public.term_df (
    lexeme text   PRIMARY KEY,
    df     bigint NOT NULL
);

COMMENT ON TABLE public.chunk_term  IS 'Term frequency per chunk: to_tsvector(''english'', chunk_text). Derived, rebuilt whole.';
COMMENT ON TABLE public.chunk_stats IS 'Chunk length in lexemes, for BM25 length normalisation. Derived.';
COMMENT ON TABLE public.term_df     IS 'Document frequency per lexeme, for BM25 idf. Derived.';

COMMIT;

-- ROLLBACK: DROP TABLE IF EXISTS public.chunk_term, public.chunk_stats, public.term_df;