-- sql/003_load_run_scope_counts.sql
--
-- Separates geographic filtering from data-quality rejection.
--
-- 002 counted an out-of-scope row as a rejection, which made a national source
-- clipped to one metropolitan area look like a broken load: DS-02 reported a
-- 34.8% rejection rate purely because most Victorian public toilets are not in
-- Greater Melbourne. That is the clip doing its job.
--
-- The rejection alarm exists to catch contract failures — bad coordinates,
-- schema violations, duplicate keys. Rows excluded because they are somewhere
-- else are counted here instead, so the alarm keeps its meaning and the
-- coverage figure stays visible.

ALTER TABLE load_run
    ADD COLUMN rows_outside_scope integer;

COMMENT ON COLUMN load_run.rows_outside_scope IS 'Rows excluded by the spatial clip because they fall outside the 31 Greater Melbourne councils. Correct behaviour for a state or national source, not a rejection, and deliberately excluded from the quarantine rate.';
