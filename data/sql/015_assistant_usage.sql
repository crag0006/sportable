-- 015_assistant_usage.sql
-- One row per Melbourne day: how many assistant turns got past the scope gate
-- (contract 8.7, daily_invocation_cap). Written only by the assistant Lambda
-- through INSERT ... ON CONFLICT; counts only, never a question or an answer.
BEGIN;

CREATE TABLE IF NOT EXISTS public.assistant_usage (
    day   date    PRIMARY KEY,
    calls integer NOT NULL DEFAULT 0,
    CONSTRAINT assistant_usage_calls_nonneg CHECK (calls >= 0)
);

COMMENT ON TABLE public.assistant_usage IS 'Assistant turns past the scope gate, per Melbourne day. Counts only.';

COMMIT;
