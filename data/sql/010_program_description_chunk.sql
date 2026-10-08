BEGIN;

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE public.program_description_chunk (
    chunk_id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    program_id         text NOT NULL,
    chunk_index        integer NOT NULL,
    chunk_text         text NOT NULL,
    char_start         integer NOT NULL,
    char_end           integer NOT NULL,
    content_sha256     char(64) NOT NULL,
    embedding          public.vector(1024) NOT NULL,
    embedding_model_id text NOT NULL,
    source_id          text NOT NULL,
    load_run_id        bigint NOT NULL,
    embedded_at        timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT pdc_index_nonneg CHECK (chunk_index >= 0),
    CONSTRAINT pdc_span_ok      CHECK (char_end > char_start),
    CONSTRAINT pdc_sha_hex      CHECK (content_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT pdc_unique UNIQUE (program_id, chunk_index, embedding_model_id),
    CONSTRAINT pdc_program_fkey  FOREIGN KEY (program_id)
        REFERENCES public.program(program_id) ON DELETE CASCADE,
    CONSTRAINT pdc_source_fkey   FOREIGN KEY (source_id)
        REFERENCES public.source(source_id),
    CONSTRAINT pdc_load_run_fkey FOREIGN KEY (load_run_id)
        REFERENCES public.load_run(load_run_id)
);

CREATE INDEX pdc_sha_model_idx
    ON public.program_description_chunk (content_sha256, embedding_model_id);

CREATE INDEX pdc_embedding_hnsw
    ON public.program_description_chunk
    USING hnsw (embedding public.vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

COMMENT ON TABLE public.program_description_chunk IS
    'Retrieval index over publisher programme text. Every row traces to a publisher (source_id) and the dated run that loaded the text (load_run_id). Rebuildable from program.description; nothing a user types is ever stored here.';
COMMENT ON COLUMN public.program_description_chunk.char_start IS
    'Offset into program.description, so a quote can be shown in context.';
COMMENT ON COLUMN public.program_description_chunk.embedding_model_id IS
    'Query-time embeddings must use this exact model and dimension count, or similarity is meaningless.';

COMMIT;

-- ROLLBACK: DROP TABLE IF EXISTS public.program_description_chunk;